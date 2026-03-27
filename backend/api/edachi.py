from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from difflib import SequenceMatcher
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import requests
from django.utils import timezone

from portfolio.models import Holding, Portfolio, Stock
from watchlist.models import PriceAlert, WatchlistItem
from analysis.provider import get_portfolio_sentiment, get_quick_stock_sentiment
from .models import CachedPayload
from .yf_client import get_fast_quote, get_fundamentals
from .chat_tools import build_market_intel, compute_recommendations, log_chat_observability
from .finance_kb import lookup_finance_answer
try:
    from langgraph.graph import END, StateGraph  # type: ignore
    _LANGGRAPH_AVAILABLE = True
except Exception:
    END = "__end__"
    StateGraph = None
    _LANGGRAPH_AVAILABLE = False


DEFAULT_SYSTEM_PROMPT = (
    "You are EDACHI Assistant for PortfolioAnalyzer. "
    "Be concise, practical, educational, and data-driven. "
    "Never provide definitive investment advice. "
    "Prefer portfolio-specific insights, risk framing, and clear next steps."
)
ANALYST_STYLE_BLOCK = (
    "Style rules: be warm, professional, and conversational. "
    "When useful, think in clear steps and explain trade-offs. "
    "Do not claim certainty. If a user asks for stock picks, provide a review framework with risk checks and diversification reminders."
)


@dataclass
class EdachiContext:
    user_id: int
    username: str
    portfolios: list[dict[str, Any]]
    holdings: list[dict[str, Any]]
    watchlist_count: int


@dataclass
class GuestEdachiContext:
    markets: dict[str, Any]
    features: list[str]


def _session_key(user_id: int) -> str:
    return f"edachi:session:user:{user_id}"


def _faq_key(user_id: int) -> str:
    return f"edachi:faq:user:{user_id}"


def _guest_faq_key(client_id: str) -> str:
    return f"edachi:faq:guest:{client_id}"


def _feedback_key(user_id: int) -> str:
    return f"edachi:feedback:user:{user_id}"


def _guest_feedback_key(client_id: str) -> str:
    return f"edachi:feedback:guest:{client_id}"


def get_or_init_session(user) -> dict[str, Any]:
    key = _session_key(user.id)
    row, _ = CachedPayload.objects.get_or_create(key=key, defaults={"payload": {}})
    payload = dict(row.payload or {})
    if "messages" not in payload:
        payload = {
            "messages": [],
            "created_at": timezone.now().isoformat(),
            "updated_at": timezone.now().isoformat(),
            "assistant_name": "EDACHI Assistant",
        }
        row.payload = payload
        row.save(update_fields=["payload", "updated_at"])
    return payload


def save_session(user, payload: dict[str, Any]) -> None:
    payload["updated_at"] = timezone.now().isoformat()
    CachedPayload.objects.update_or_create(key=_session_key(user.id), defaults={"payload": payload})


def clear_session(user) -> None:
    CachedPayload.objects.filter(key=_session_key(user.id)).delete()


def _to_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def build_context(user) -> EdachiContext:
    portfolios_qs = Portfolio.objects.filter(user=user).order_by("-created_at")
    portfolios = [{"id": p.id, "name": p.name, "market": p.market} for p in portfolios_qs[:20]]

    holdings_qs = (
        Holding.objects.filter(portfolio__user=user)
        .select_related("stock", "stock__sector", "portfolio")
        .order_by("portfolio_id", "stock__symbol")
    )
    holdings = []
    for h in holdings_qs[:200]:
        holdings.append(
            {
                "portfolio_id": h.portfolio_id,
                "portfolio_name": h.portfolio.name,
                "symbol": h.stock.symbol,
                "stock_name": h.stock.name,
                "sector": h.stock.sector.name if h.stock.sector_id else "",
                "qty": _to_float(h.qty),
                "avg_buy_price": _to_float(h.avg_buy_price),
            }
        )

    watchlist_count = 0
    try:
        from watchlist.models import WatchlistItem

        watchlist_count = WatchlistItem.objects.filter(user=user).count()
    except Exception:
        watchlist_count = 0

    return EdachiContext(
        user_id=user.id,
        username=user.username,
        portfolios=portfolios,
        holdings=holdings,
        watchlist_count=watchlist_count,
    )


def _as_decimal(v) -> Decimal:
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


def _sector_distribution(holdings: list[dict[str, Any]]) -> list[tuple[str, int]]:
    m: dict[str, int] = {}
    for h in holdings:
        sec = (h.get("sector") or "Uncategorized").strip() or "Uncategorized"
        m[sec] = m.get(sec, 0) + 1
    return sorted(m.items(), key=lambda x: x[1], reverse=True)


def build_quick_brief(ctx: EdachiContext) -> dict[str, Any]:
    portfolio_count = len(ctx.portfolios)
    holding_count = len(ctx.holdings)
    sectors = _sector_distribution(ctx.holdings)

    exposure = Decimal("0")
    for h in ctx.holdings:
        qty = _as_decimal(h.get("qty") or 0)
        avg = _as_decimal(h.get("avg_buy_price") or 0)
        exposure += qty * avg

    top_holdings = sorted(
        ctx.holdings,
        key=lambda x: (_as_decimal(x.get("qty") or 0) * _as_decimal(x.get("avg_buy_price") or 0)),
        reverse=True,
    )[:5]

    return {
        "portfolios": portfolio_count,
        "holdings": holding_count,
        "watchlist_items": ctx.watchlist_count,
        "estimated_cost_exposure": float(exposure),
        "top_sectors": [{"name": name, "count": count} for name, count in sectors[:5]],
        "top_holdings": top_holdings,
    }


def _extract_response_text(data: dict[str, Any]) -> str:
    text = data.get("output_text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    output = data.get("output") or []
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content") or []
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "output_text":
                t = c.get("text")
                if isinstance(t, str) and t.strip():
                    chunks.append(t.strip())
    return "\n".join(chunks).strip()


def _normalize_text(text: str) -> str:
    t = (text or "").lower()
    # Lightweight typo normalization for high-frequency chat terms.
    t = t.replace("stoct", "stock").replace("stcok", "stock").replace("portfollio", "portfolio")
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _looks_like_buy_reco_request(question: str) -> bool:
    q = _normalize_text(question)
    return ("stock" in q or "share" in q) and any(k in q for k in ["buy", "suggest", "recommend", "pick", "which"])


def _smalltalk_intent_answer(question: str, is_authenticated: bool, brief: dict[str, Any] | None = None) -> dict[str, Any] | None:
    q = (question or "").strip().lower()
    compact = re.sub(r"[^a-z0-9]+", " ", q).strip()
    tokens = set(compact.split())
    brief = brief or {}

    if compact in {"hi", "hii", "hiii", "hello", "hey", "yo", "hola", "namaste"} or any(
        k in q for k in ["good morning", "good afternoon", "good evening"]
    ):
        if is_authenticated:
            return {
                "answer": (
                    "Hey! I am here and ready. I can chat normally, analyze your portfolio, check sentiment, "
                    "and run actions like watchlist/alerts. What do you want to do first?"
                ),
                "cards": [{"type": "summary", "data": brief}],
            }
        return {
            "answer": (
                "Hey! Great to see you here. I can help with market snapshots, app guidance, and feature walkthroughs. "
                "Ask me anything."
            ),
            "cards": [],
        }

    if any(k in q for k in ["who are you", "what are you", "your name"]):
        return {
            "answer": (
                "I am EDACHI , your AI copilot for PortfolioAnalyzer. I can do conversational Q&A, explain features, "
                "analyze sentiment, and for logged-in users execute portfolio actions."
            ),
            "cards": [],
        }

    if any(k in q for k in ["what can you do", "help", "capabilities", "how can you help"]) or compact in {"help me", "help"}:
        if is_authenticated:
            return {
                "answer": (
                    "I can help with:\n"
                    "1) Portfolio summary and holdings breakdown\n"
                    "2) Portfolio/stock sentiment insights\n"
                    "3) Actions: add/remove watchlist, create portfolio, create price alerts\n"
                    "4) Conversational guidance and strategy framing"
                ),
                "cards": [{"type": "summary", "data": brief}],
            }
        return {
            "answer": (
                "I can help with:\n"
                "1) Market snapshot and platform walkthrough\n"
                "2) Feature discovery and onboarding guidance\n"
                "3) General investing education (non-advisory)\n"
                "Login unlocks personalized portfolio insights and actions."
            ),
            "cards": [],
        }

    if "thank" in q or compact in {"thx", "thanks", "ty"}:
        return {"answer": "You are welcome. Keep the questions coming.", "cards": []}

    if any(k in q for k in ["how are you", "how r u", "how are u"]):
        return {"answer": "Doing great and ready to help. What should we tackle next?", "cards": []}

    if any(k in q for k in ["joke", "funny"]):
        return {
            "answer": "Why did the portfolio break up with leverage? Too much emotional volatility.",
            "cards": [],
        }

    if compact in {"ok", "okay", "hmm", "hmmm", "huh"} or tokens.issubset({"ok", "okay", "hmm", "hmmm", "huh"}):
        return {
            "answer": "No rush. Tell me what you want: summary, sentiment, watchlist action, or market snapshot.",
            "cards": [],
        }

    return None


def _finance_basics_intent_answer(question: str) -> dict[str, Any] | None:
    q = _normalize_text(question)

    if any(k in q for k in ["what is stock market", "what is share market", "stock market meaning"]):
        return {
            "answer": (
                "The stock market is a marketplace where investors buy and sell ownership shares of companies. "
                "Prices move based on company performance, earnings expectations, news, interest rates, and demand/supply."
            ),
            "cards": [{"type": "education", "data": {"topic": "stock_market_basics"}}],
        }

    if any(k in q for k in ["what is pe ratio", "p e ratio", "price earnings ratio"]):
        return {
            "answer": (
                "P/E ratio = Share Price / Earnings Per Share. "
                "A high P/E often means growth expectations are high; a low P/E can indicate value or weaker growth outlook. "
                "Always compare P/E within the same sector."
            ),
            "cards": [{"type": "education", "data": {"topic": "pe_ratio"}}],
        }

    if any(k in q for k in ["what is market cap", "market capitalization"]):
        return {
            "answer": (
                "Market cap is total company value in the stock market: Share Price x Total Outstanding Shares. "
                "Large-cap stocks are usually more stable, while mid/small-caps can be more volatile."
            ),
            "cards": [{"type": "education", "data": {"topic": "market_cap"}}],
        }

    if any(k in q for k in ["what is beta", "beta in stock market", "stock beta meaning"]):
        return {
            "answer": (
                "Beta measures how much a stock tends to move compared to the overall market. "
                "Beta around 1 means similar volatility to market, above 1 means higher volatility, below 1 means lower volatility."
            ),
            "cards": [{"type": "education", "data": {"topic": "beta"}}],
        }

    if any(k in q for k in ["what is sip", "sip meaning"]):
        return {
            "answer": (
                "SIP means Systematic Investment Plan, where you invest a fixed amount regularly (usually monthly). "
                "It helps with discipline and reduces timing risk through rupee-cost averaging."
            ),
            "cards": [{"type": "education", "data": {"topic": "sip"}}],
        }

    if any(k in q for k in ["what is diversification", "diversification meaning"]):
        return {
            "answer": (
                "Diversification means spreading investments across sectors and asset types to reduce concentration risk. "
                "It helps protect your portfolio when one stock or sector underperforms."
            ),
            "cards": [{"type": "education", "data": {"topic": "diversification"}}],
        }

    if any(k in q for k in ["difference between nse and bse", "nse vs bse"]):
        return {
            "answer": (
                "NSE and BSE are India’s two main stock exchanges. NSE generally has higher liquidity for many active stocks, "
                "while BSE is older and has a larger number of listed companies."
            ),
            "cards": [{"type": "education", "data": {"topic": "nse_vs_bse"}}],
        }

    kb = lookup_finance_answer(question, min_score=0.73)
    if kb:
        return {
            "answer": str(kb.get("answer") or "").strip(),
            "cards": [{"type": "education_kb", "data": {"topic": kb.get("topic"), "score": kb.get("score")}}],
        }

    return None


def _extract_symbol(question: str) -> str:
    q = (question or "").strip()
    candidates = re.findall(r"\b[A-Za-z]{2,10}(?:\.(?:NS|BO))?\b", q)
    stop = {
        "ADD",
        "REMOVE",
        "DELETE",
        "WATCHLIST",
        "WATCH",
        "UNWATCH",
        "CREATE",
        "ALERT",
        "ABOVE",
        "BELOW",
        "PORTFOLIO",
        "SENTIMENT",
        "SUMMARY",
        "SHOW",
        "MY",
        "FOR",
        "TO",
        "FROM",
        "THE",
    }
    for raw in candidates:
        sym = raw.upper()
        if sym in stop:
            continue
        if Stock.objects.filter(symbol__iexact=sym).exists():
            return sym
    for raw in candidates:
        sym = raw.upper()
        if sym in stop:
            continue
        if "." in sym or len(sym) <= 5:
            return sym
    return ""


def _is_market_news_query(question: str) -> bool:
    q = _normalize_text(question)
    return any(k in q for k in ["news", "headline", "latest", "update", "market today", "what happening", "what happened"])


def _is_quote_query(question: str) -> bool:
    q = _normalize_text(question)
    return any(k in q for k in ["price", "quote", "last price", "cmp", "trading at"])


def _recommendation_candidates(ctx: EdachiContext, limit: int = 6) -> list[dict[str, Any]]:
    return compute_recommendations(ctx, limit=limit)


def _resolve_stock(token: str) -> Stock | None:
    t = (token or "").strip()
    if not t:
        return None
    stock = Stock.objects.filter(symbol__iexact=t).first()
    if stock:
        return stock
    return Stock.objects.filter(name__icontains=t).order_by("symbol").first()


def _run_action_intent(user, question: str) -> dict[str, Any] | None:
    q = (question or "").strip()
    ql = q.lower()
    symbol = _extract_symbol(q)

    wants_add_watch = ("watchlist" in ql and any(k in ql for k in ["add", "track", "watch"]))
    if wants_add_watch and not any(k in ql for k in ["remove", "delete", "unwatch"]):
        stock = _resolve_stock(symbol)
        if not stock:
            return {
                "answer": "I could not find that symbol. Please use a valid symbol like INFY.NS or AAPL.",
                "cards": [{"type": "action_error", "data": {"action": "watchlist_add"}}],
                "source": "action",
            }
        item, created = WatchlistItem.objects.get_or_create(user=user, stock=stock)
        return {
            "answer": f"{stock.symbol} {'added to' if created else 'is already in'} your watchlist.",
            "cards": [{"type": "action", "data": {"action": "watchlist_add", "created": created, "item_id": item.id, "symbol": stock.symbol}}],
            "source": "action",
        }

    wants_remove_watch = ("watchlist" in ql and any(k in ql for k in ["remove", "delete", "unwatch"]))
    if wants_remove_watch:
        stock = _resolve_stock(symbol)
        if not stock:
            return {
                "answer": "I could not identify which symbol to remove from watchlist.",
                "cards": [{"type": "action_error", "data": {"action": "watchlist_remove"}}],
                "source": "action",
            }
        deleted, _ = WatchlistItem.objects.filter(user=user, stock=stock).delete()
        return {
            "answer": f"{stock.symbol} removed from watchlist." if deleted else f"{stock.symbol} was not in your watchlist.",
            "cards": [{"type": "action", "data": {"action": "watchlist_remove", "deleted": bool(deleted), "symbol": stock.symbol}}],
            "source": "action",
        }

    if any(k in ql for k in ["create portfolio", "new portfolio"]):
        m = re.search(r"(?:create|new)\s+portfolio(?:\s+named|\s+called)?\s+(.+)$", q, flags=re.IGNORECASE)
        name = (m.group(1).strip() if m else "").strip(" .")
        if not name:
            name = f"My Portfolio {timezone.localtime().strftime('%Y-%m-%d %H:%M')}"
        portfolio = Portfolio.objects.create(user=user, name=name[:120], market="IN")
        return {
            "answer": f"Created portfolio '{portfolio.name}'.",
            "cards": [{"type": "action", "data": {"action": "portfolio_create", "portfolio_id": portfolio.id, "name": portfolio.name}}],
            "source": "action",
        }

    if any(k in ql for k in ["create alert", "set alert", "price alert"]):
        stock = _resolve_stock(symbol)
        if not stock:
            return {
                "answer": "Please include a valid symbol for the alert, for example: create alert for INFY.NS above 1800.",
                "cards": [{"type": "action_error", "data": {"action": "alert_create"}}],
                "source": "action",
            }
        direction = "ABOVE" if "above" in ql else ("BELOW" if "below" in ql else "")
        pm = re.search(r"(\d+(?:\.\d+)?)", q)
        price_text = pm.group(1) if pm else ""
        if not direction or not price_text:
            return {
                "answer": "Please specify direction and target, for example: create alert for AAPL below 175.",
                "cards": [{"type": "action_error", "data": {"action": "alert_create"}}],
                "source": "action",
            }
        target = _as_decimal(price_text)
        if target <= 0:
            return {
                "answer": "Target price must be greater than zero.",
                "cards": [{"type": "action_error", "data": {"action": "alert_create"}}],
                "source": "action",
            }
        alert = PriceAlert.objects.create(
            user=user,
            stock=stock,
            direction=direction,
            target_price=target,
        )
        return {
            "answer": f"Alert created: {stock.symbol} {direction} {target}.",
            "cards": [
                {
                    "type": "action",
                    "data": {
                        "action": "alert_create",
                        "alert_id": alert.id,
                        "symbol": stock.symbol,
                        "direction": direction,
                        "target_price": float(target),
                    },
                }
            ],
            "source": "action",
        }

    return None


def _sentiment_intent_answer(user, question: str, ctx: EdachiContext) -> dict[str, Any] | None:
    q = (question or "").strip().lower()
    if "sentiment" not in q:
        return None

    if "portfolio sentiment" in q or ("sentiment" in q and any(k in q for k in ["my portfolio", "overall", "summary"])):
        if not ctx.portfolios:
            return {
                "answer": "No portfolio found yet. Create a portfolio first to run sentiment analysis.",
                "cards": [],
            }
        portfolio = Portfolio.objects.filter(id=ctx.portfolios[0]["id"], user=user).first()
        if not portfolio:
            return None
        try:
            payload = get_portfolio_sentiment(portfolio, force_refresh=False)
            signal = ((payload.get("summary") or {}).get("portfolio_signal")) or "Neutral"
            score = ((payload.get("summary") or {}).get("portfolio_sentiment_score")) or 0.0
            risky = (payload.get("summary") or {}).get("most_risky_stock") or {}
            return {
                "answer": (
                    f"Portfolio sentiment is {signal} (score {score}). "
                    f"Most risky stock right now: {risky.get('symbol') or '--'}."
                ),
                "cards": [{"type": "sentiment_portfolio", "data": payload}],
            }
        except Exception:
            return {
                "answer": "Portfolio sentiment is temporarily unavailable. Try again in a minute.",
                "cards": [],
            }

    symbol = _extract_symbol(question)
    if symbol:
        try:
            payload = get_quick_stock_sentiment(symbol=symbol, company_name=None, force_refresh=False)
            overall = payload.get("overall_signal") or {}
            score = overall.get("sentiment_score", 0.0)
            label = overall.get("signal_label", "Neutral")
            reason = overall.get("reason") or "No detailed reason available."
            return {
                "answer": f"{symbol} sentiment is {label} (score {score}). {reason}",
                "cards": [{"type": "sentiment_stock", "data": payload}],
            }
        except Exception:
            return {
                "answer": f"I could not load sentiment for {symbol} right now.",
                "cards": [],
            }

    return {
        "answer": "Please specify a symbol (for example: 'sentiment for AAPL') or ask for 'portfolio sentiment summary'.",
        "cards": [],
    }


def _market_intelligence_answer(user, question: str, ctx: EdachiContext) -> dict[str, Any] | None:
    q = (question or "").strip()
    ql = q.lower()
    symbol = _extract_symbol(q)
    intel = build_market_intel(question=q, user=user, ctx=ctx, include_recommendations=False)

    if _is_quote_query(q):
        quote = dict(intel.get("quote") or {})
        if symbol and quote.get("last_price") is not None:
            return {
                "answer": (
                    f"{symbol} last price is {quote.get('last_price')} "
                    f"({quote.get('change_pct')}% today)."
                ),
                "cards": [{"type": "quote", "data": quote}],
            }
        return {
            "answer": "Share a symbol and I will fetch the latest quote. Example: 'price of TCS.NS'.",
            "cards": [],
        }

    if _is_market_news_query(q) or "market snapshot" in ql:
        news_symbol = symbol or str(intel.get("symbol") or (ctx.holdings[0].get("symbol") if ctx.holdings else ""))
        sent = dict(intel.get("sentiment") or {})
        overall = dict(sent.get("overall_signal") or {})
        top_news = list(sent.get("top_news") or [])[:3]
        if news_symbol and top_news:
            bullets = []
            for n in top_news:
                head = str(n.get("headline") or "Headline")
                label = str(n.get("sentiment_label") or "neutral").title()
                src = str(n.get("source") or "Source")
                bullets.append(f"- {head} ({label}, {src})")
            answer = (
                f"Latest read for {news_symbol}: {overall.get('signal_label', 'Neutral')} "
                f"(score {overall.get('sentiment_score', 0)}).\n"
                "Top headlines:\n" + "\n".join(bullets)
            )
            return {
                "answer": answer,
                "cards": [
                    {"type": "sentiment_stock", "data": sent},
                    {"type": "news", "items": top_news},
                ],
            }

        indices = dict(intel.get("indices") or {})
        nifty = dict(indices.get("nifty") or {})
        sensex = dict(indices.get("sensex") or {})
        return {
            "answer": (
                f"Market snapshot: Nifty {nifty.get('last_price', '--')} ({nifty.get('change_pct', '--')}%), "
                f"Sensex {sensex.get('last_price', '--')} ({sensex.get('change_pct', '--')}%). "
                "Ask a symbol to get headline-level sentiment."
            ),
            "cards": [{"type": "market", "data": {"nifty": nifty, "sensex": sensex}}],
        }
    return None


def _resolve_portfolio_filter(question: str, ctx: EdachiContext) -> tuple[int | None, str]:
    ql = (question or "").lower()
    for p in ctx.portfolios:
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        if name.lower() in ql:
            return int(p.get("id")), name
    m = re.search(r"(?:portfolio|pf)\s*(?:#|id)?\s*(\d+)", ql)
    if m:
        pid = int(m.group(1))
        for p in ctx.portfolios:
            if int(p.get("id") or 0) == pid:
                return pid, str(p.get("name") or f"#{pid}")
    return None, ""


def _resolve_sector_filter(question: str, ctx: EdachiContext) -> str:
    ql = (question or "").lower()
    sector_names = sorted({str(h.get("sector") or "").strip() for h in ctx.holdings if str(h.get("sector") or "").strip()}, key=len, reverse=True)
    for s in sector_names:
        if s.lower() in ql:
            return s
    m = re.search(r"([a-z][a-z\s&\-]{2,40})\s+sector", ql)
    if m:
        return m.group(1).strip().title()
    return ""


def _format_metric(v: float | None, nd: int = 2) -> str:
    if v is None:
        return "--"
    try:
        return f"{float(v):,.{nd}f}"
    except Exception:
        return "--"


def _holdings_metrics_answer(question: str, ctx: EdachiContext) -> dict[str, Any] | None:
    qn = _normalize_text(question)
    if not any(k in qn for k in ["holdings", "holding", "stocks in", "stock list", "my stocks", "positions"]):
        return None

    portfolio_id, portfolio_name = _resolve_portfolio_filter(question, ctx)
    sector = _resolve_sector_filter(question, ctx)
    rows = list(ctx.holdings or [])
    if portfolio_id is not None:
        rows = [h for h in rows if int(h.get("portfolio_id") or 0) == int(portfolio_id)]
    if sector:
        rows = [h for h in rows if str(h.get("sector") or "").strip().lower() == sector.lower()]

    if not rows:
        scope_bits = []
        if portfolio_name:
            scope_bits.append(f"portfolio '{portfolio_name}'")
        if sector:
            scope_bits.append(f"sector '{sector}'")
        scope = " and ".join(scope_bits) if scope_bits else "your current filters"
        return {"answer": f"No holdings found for {scope}.", "cards": []}

    # Keep response fast and readable for chat UI.
    rows = rows[:18]
    items = []
    for h in rows:
        sym = str(h.get("symbol") or "").upper()
        qty = _to_float(h.get("qty"))
        avg = _to_float(h.get("avg_buy_price"))
        invested = (qty * avg) if qty is not None and avg is not None else None
        quote = {}
        fundamentals = {}
        try:
            quote = get_fast_quote(sym) or {}
        except Exception:
            quote = {}
        try:
            fundamentals = get_fundamentals(sym) or {}
        except Exception:
            fundamentals = {}
        last = _to_float(quote.get("last_price"))
        pe = _to_float(fundamentals.get("trailingPE") or fundamentals.get("forwardPE"))
        current_value = (qty * last) if qty is not None and last is not None else None
        pnl = (current_value - invested) if current_value is not None and invested is not None else None
        pnl_pct = ((pnl / invested) * 100.0) if pnl is not None and invested not in (None, 0) else None
        items.append(
            {
                "symbol": sym,
                "portfolio_name": h.get("portfolio_name"),
                "sector": h.get("sector"),
                "qty": qty,
                "avg_buy_price": avg,
                "last_price": last,
                "pe": pe,
                "invested": invested,
                "current_value": current_value,
                "unrealized_pnl": pnl,
                "unrealized_pnl_pct": pnl_pct,
            }
        )

    answer_lines = []
    for it in items[:12]:
        invested = _to_float(it.get("invested"))
        pnl_pct = _to_float(it.get("unrealized_pnl_pct"))
        # Avoid misleading giant percentages when imported avg price is placeholder like 1.0.
        safe_pct = pnl_pct if (invested is not None and invested >= 100 and pnl_pct is not None and abs(pnl_pct) <= 500) else None
        pnl_text = _format_metric(it.get("unrealized_pnl"))
        pct_text = f" ({_format_metric(safe_pct)}%)" if safe_pct is not None else ""
        answer_lines.append(
            f"- {it['symbol']}: Qty {_format_metric(it.get('qty'), 0)}, Buy {_format_metric(it.get('avg_buy_price'))}, "
            f"Now {_format_metric(it.get('last_price'))}, P/E {_format_metric(it.get('pe'))}, "
            f"Unrealized P/L {pnl_text}{pct_text}"
        )
    header_bits = []
    if portfolio_name:
        header_bits.append(f"portfolio '{portfolio_name}'")
    if sector:
        header_bits.append(f"sector '{sector}'")
    header_scope = " in ".join(header_bits) if header_bits else "across your portfolios"
    answer = (
        f"I found {len(items)} holdings {header_scope}. "
        "Here is a simple view:\n" + "\n".join(answer_lines)
    )
    if any(_to_float(it.get("invested")) is not None and _to_float(it.get("invested")) < 100 for it in items):
        answer += "\nNote: Some percentage P/L values are hidden because imported buy price looks like a placeholder."
    if len(items) > 12:
        answer += f"\nShowing 12 of {len(items)} matching holdings."
    return {"answer": answer, "cards": [{"type": "holdings_metrics", "items": items}]}


def _intent_answer(question: str, ctx: EdachiContext) -> dict[str, Any] | None:
    q = _normalize_text(question)
    brief = build_quick_brief(ctx)

    if any(k in q for k in ["portfolio list", "my portfolios", "show portfolios", "portfolio names"]):
        lines = [f"{i + 1}. {p['name']} ({p['market']})" for i, p in enumerate(ctx.portfolios[:12])]
        txt = "Here are your portfolios:\n" + ("\n".join(lines) if lines else "No portfolios yet.")
        return {"answer": txt, "cards": [{"type": "portfolios", "items": ctx.portfolios[:12]}]}

    holdings_out = _holdings_metrics_answer(question, ctx)
    if holdings_out is not None:
        return holdings_out

    if any(k in q for k in ["summary", "overview", "health", "status"]):
        answer = (
            f"You currently have {brief['portfolios']} portfolios and {brief['holdings']} holdings. "
            f"Estimated cost exposure is {brief['estimated_cost_exposure']:.2f}. "
            f"Top sectors: "
            + ", ".join([f"{x['name']} ({x['count']})" for x in brief["top_sectors"][:3]])
        )
        return {"answer": answer, "cards": [{"type": "summary", "data": brief}]}

    if any(k in q for k in ["recommend", "what to add", "suggest stock", "next stock"]) or _looks_like_buy_reco_request(question):
        picks = _recommendation_candidates(ctx, limit=6)
        if not picks:
            return {"answer": "I could not build recommendations right now. Please try again shortly.", "cards": []}
        top_sector = (brief["top_sectors"][0]["name"] if brief["top_sectors"] else "Mixed")
        lead = picks[0]
        msg = (
            f"Recommendation shortlist based on your holdings/sectors ({top_sector} tilt): "
            f"{', '.join([p['symbol'] for p in picks[:4]])}. "
            f"Top fit right now is {lead['symbol']} (score {lead['score']})."
        )
        return {"answer": msg, "cards": [{"type": "recommendations", "items": picks}]}

    return None


def _build_learning_memory(user, question: str, answer: str) -> None:
    _build_learning_memory_for_key(_faq_key(user.id), question=question, answer=answer)


def _build_learning_memory_for_key(key: str, question: str, answer: str) -> None:
    if not key:
        return
    q = (question or "").strip()
    a = (answer or "").strip()
    if len(q) < 3 or len(a) < 8:
        return
    row, _ = CachedPayload.objects.get_or_create(key=key, defaults={"payload": {"pairs": []}})
    payload = dict(row.payload or {"pairs": []})
    pairs = list(payload.get("pairs") or [])
    pairs.append(
        {
            "q": q[:500],
            "a": a[:1800],
            "at": timezone.now().isoformat(),
        }
    )
    payload["pairs"] = pairs[-80:]
    row.payload = payload
    row.save(update_fields=["payload", "updated_at"])


def _record_feedback_payload(key: str, question: str, answer: str, helpful: bool, source: str = "") -> None:
    row, _ = CachedPayload.objects.get_or_create(key=key, defaults={"payload": {"items": [], "scores": {}}})
    payload = dict(row.payload or {"items": [], "scores": {}})
    items = list(payload.get("items") or [])
    scores = dict(payload.get("scores") or {})
    qn = _normalize_text(question)
    current = float(scores.get(qn, 0.0))
    current = current + (1.0 if helpful else -1.0)
    current = max(-6.0, min(6.0, current))
    scores[qn] = current
    items.append(
        {
            "q": (question or "")[:500],
            "a": (answer or "")[:1500],
            "helpful": bool(helpful),
            "source": (source or "")[:40],
            "at": timezone.now().isoformat(),
        }
    )
    payload["items"] = items[-120:]
    payload["scores"] = scores
    row.payload = payload
    row.save(update_fields=["payload", "updated_at"])


def save_feedback(user, question: str, answer: str, helpful: bool, source: str = "") -> None:
    _record_feedback_payload(_feedback_key(user.id), question=question, answer=answer, helpful=helpful, source=source)


def save_guest_feedback(client_id: str, question: str, answer: str, helpful: bool, source: str = "") -> None:
    if not client_id:
        return
    _record_feedback_payload(_guest_feedback_key(client_id), question=question, answer=answer, helpful=helpful, source=source)


def _feedback_scores_for_user(user) -> dict[str, float]:
    return _read_feedback_scores(_feedback_key(user.id))


def _feedback_scores_for_guest(client_id: str) -> dict[str, float]:
    if not client_id:
        return {}
    return _read_feedback_scores(_guest_feedback_key(client_id))


def _read_feedback_scores(key: str) -> dict[str, float]:
    if not key:
        return {}
    row = CachedPayload.objects.filter(key=key).first()
    if not row:
        return {}
    payload = dict(row.payload or {})
    raw = payload.get("scores") or {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = float(v)
        except Exception:
            continue
    return out


def _find_memory_hit(user, question: str) -> dict[str, Any] | None:
    return _find_memory_hit_by_key(_faq_key(user.id), question=question, feedback_scores=_feedback_scores_for_user(user))


def _find_guest_memory_hit(client_id: str, question: str) -> dict[str, Any] | None:
    if not client_id:
        return None
    return _find_memory_hit_by_key(_guest_faq_key(client_id), question=question, feedback_scores=_feedback_scores_for_guest(client_id))


def _find_memory_hit_by_key(key: str, question: str, feedback_scores: dict[str, float] | None = None) -> dict[str, Any] | None:
    if not key:
        return None
    row = CachedPayload.objects.filter(key=key).first()
    if not row:
        return None
    payload = dict(row.payload or {})
    pairs = payload.get("pairs") or []
    qn = _normalize_text(question)
    if len(qn) < 8:
        return None
    feedback_scores = feedback_scores or {}
    best = None
    best_score = 0.0
    for p in reversed(pairs):
        q0 = _normalize_text(str(p.get("q") or ""))
        if not q0:
            continue
        if q0 == qn:
            return p
        ratio = SequenceMatcher(None, q0, qn).ratio()
        overlap = 0.0
        q0_tokens = set(q0.split())
        qn_tokens = set(qn.split())
        if q0_tokens and qn_tokens:
            overlap = len(q0_tokens.intersection(qn_tokens)) / float(len(q0_tokens.union(qn_tokens)))
        score = (ratio * 0.7) + (overlap * 0.3)
        # Use user feedback to rank prior answers: helpful votes boost, unhelpful votes reduce.
        score += float(feedback_scores.get(q0, 0.0)) * 0.05
        if score > best_score:
            best_score = score
            best = p
    if best is not None and best_score >= 0.78:
        return best
    return None


def _find_curated_memory_hit(question: str) -> dict[str, Any] | None:
    row = CachedPayload.objects.filter(key="edachi:curated_memory:v1").first()
    if not row:
        return None
    items = list((row.payload or {}).get("items") or [])
    if not items:
        return None
    qn = _normalize_text(question)
    if len(qn) < 8:
        return None
    best = None
    best_score = 0.0
    qn_tokens = set(qn.split())
    for it in items:
        q0 = _normalize_text(str(it.get("q") or ""))
        if not q0:
            continue
        if q0 == qn:
            return it
        ratio = SequenceMatcher(None, q0, qn).ratio()
        q0_tokens = set(q0.split())
        overlap = 0.0
        if q0_tokens and qn_tokens:
            overlap = len(q0_tokens.intersection(qn_tokens)) / float(len(q0_tokens.union(qn_tokens)))
        score = (ratio * 0.65) + (overlap * 0.35)
        score += min(0.1, float(it.get("weight") or 0.0) * 0.01)
        if score > best_score:
            best_score = score
            best = it
    if best is not None and best_score >= 0.82:
        return best
    return None


def _ordered_model_chain(deep: bool, public: bool = False) -> list[str]:
    model_fast = (os.getenv("EDACHI_MODEL_FAST") or "gpt-5.4-mini").strip()
    model_reasoning = (os.getenv("EDACHI_MODEL_REASONING") or "gpt-5.4").strip()
    fallback_fast = (os.getenv("EDACHI_MODEL_FAST_FALLBACK") or "gpt-4.1-mini").strip()
    fallback_reasoning = (os.getenv("EDACHI_MODEL_REASONING_FALLBACK") or "gpt-4.1").strip()
    chain_env = (os.getenv("EDACHI_MODEL_CHAIN_PUBLIC" if public else "EDACHI_MODEL_CHAIN") or "").strip()
    if chain_env:
        parsed = [m.strip() for m in chain_env.split(",") if m.strip()]
        if parsed:
            return parsed
    primary = model_reasoning if deep else model_fast
    secondary = fallback_reasoning if deep else fallback_fast
    chain: list[str] = []
    for m in [primary, secondary]:
        if m and m not in chain:
            chain.append(m)
    return chain


def _openai_generate(
    question: str,
    ctx: EdachiContext,
    session_messages: list[dict[str, Any]],
    force_deep: bool = False,
) -> str | None:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return None

    q_lower = question.lower()
    deep = force_deep or (
        len(question) > 220
        or any(k in q_lower for k in ["strategy", "allocation", "rebalance", "risk model", "compare scenarios", "drawdown", "valuation"])
    )
    model_chain = _ordered_model_chain(deep=deep, public=False)
    recent = session_messages[-10:] if session_messages else []
    brief = build_quick_brief(ctx)
    symbol = _extract_symbol(question)
    live_context: dict[str, Any] = {}
    if symbol:
        try:
            live_context["symbol_quote"] = get_fast_quote(symbol) or {}
        except Exception:
            pass
        try:
            quick_sent = get_quick_stock_sentiment(symbol=symbol, company_name=None, force_refresh=False) or {}
            live_context["symbol_sentiment"] = {
                "overall_signal": quick_sent.get("overall_signal"),
                "score_breakdown": quick_sent.get("score_breakdown"),
                "top_news": list(quick_sent.get("top_news") or [])[:3],
            }
        except Exception:
            pass
    context_payload = {
        "user": {"id": ctx.user_id, "username": ctx.username},
        "portfolio_count": len(ctx.portfolios),
        "holding_count": len(ctx.holdings),
        "top_portfolios": ctx.portfolios[:6],
        "top_holdings": brief.get("top_holdings", [])[:10],
        "top_sectors": brief.get("top_sectors", [])[:8],
        "watchlist_items": int(brief.get("watchlist_items", 0) or 0),
        "live_context": live_context,
        "timestamp": timezone.now().isoformat(),
    }
    prompt = (
        f"System:\n{DEFAULT_SYSTEM_PROMPT}\n\n"
        f"Behavior:\n{ANALYST_STYLE_BLOCK}\n\n"
        f"Context JSON:\n{json.dumps(context_payload, ensure_ascii=True)}\n\n"
        f"Recent chat:\n{json.dumps(recent, ensure_ascii=True)}\n\n"
        f"User question:\n{question}\n\n"
        "Reply in markdown with sections: Answer, Why this matters, Next best step. "
        "If user asks for buy/sell calls, avoid direct advice and provide scenario-based checklist."
    )

    for model in model_chain:
        try:
            res = requests.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "input": prompt,
                    "max_output_tokens": 520,
                    "temperature": 0.2,
                },
                timeout=22,
            )
            if not res.ok:
                # Try the fallback model when the preferred model is unavailable.
                continue
            data = res.json() or {}
            text = _extract_response_text(data)
            if text:
                return text
        except Exception:
            continue
    return None


def _answer_question_legacy(user, question: str) -> dict[str, Any]:
    question = (question or "").strip()
    if not question:
        return {
            "answer": (
                "Ask me about portfolios, holdings, sentiment, or actions like "
                "'add AAPL to watchlist' and 'create alert for INFY.NS above 1800'."
            ),
            "cards": [],
        }

    ctx = build_context(user)
    brief = build_quick_brief(ctx)
    session = get_or_init_session(user)
    messages = list(session.get("messages") or [])

    smalltalk = _smalltalk_intent_answer(question, is_authenticated=True, brief=brief)
    if smalltalk is not None:
        out = {**smalltalk, "source": "smalltalk"}
    else:
        basics = _finance_basics_intent_answer(question)
        if basics is not None:
            out = {**basics, "source": "education"}
        else:
            action_out = _run_action_intent(user, question)
            if action_out is not None:
                out = action_out
            else:
                market_intel = _market_intelligence_answer(user, question, ctx)
                if market_intel is not None:
                    out = {**market_intel, "source": "market"}
                else:
                    sentiment = _sentiment_intent_answer(user, question, ctx)
                    if sentiment is not None:
                        out = {**sentiment, "source": "sentiment"}
                    else:
                        mem = _find_memory_hit(user, question)
                        if mem:
                            answer = str(mem.get("a") or "").strip()
                            out = {
                                "answer": answer,
                                "cards": [{"type": "memory_hit", "data": {"learned_at": mem.get("at")}}],
                                "source": "memory",
                            }
                        else:
                            curated = _find_curated_memory_hit(question)
                            if curated:
                                out = {
                                    "answer": str(curated.get("a") or "").strip(),
                                    "cards": [{"type": "curated_memory", "data": {"weight": curated.get("weight", 0)}}],
                                    "source": "curated_memory",
                                }
                            else:
                                intent = _intent_answer(question, ctx)
                                if intent is not None:
                                    out = {**intent, "source": "rule"}
                                else:
                                    llm_answer, llm_meta = _llm_with_guardrails(question, ctx, messages)
                                    if llm_answer:
                                        out = {
                                            "answer": llm_answer,
                                            "cards": [{"type": "llm", "data": {"provider": "openai", **llm_meta}}],
                                            "source": "llm",
                                        }
                                    else:
                                        out = {
                                            "answer": (
                                                "I can still help. Ask me about market basics, stock quotes, latest stock news, "
                                                "portfolio sentiment, recommendations, watchlist actions, or alerts.\n"
                                                "Examples:\n"
                                                "- what is stock market\n"
                                                "- latest news for INFY.NS\n"
                                                "- price of RELIANCE.NS\n"
                                                "- portfolio sentiment summary\n"
                                                "- recommend stocks based on my holdings"
                                            ),
                                            "cards": [{"type": "summary", "data": brief}],
                                            "source": "fallback",
                                        }

    user_msg = {"role": "user", "content": question, "at": timezone.now().isoformat()}
    bot_msg = {"role": "assistant", "content": out.get("answer", ""), "at": timezone.now().isoformat(), "source": out.get("source")}
    messages.extend([user_msg, bot_msg])
    session["messages"] = messages[-24:]
    save_session(user, session)
    _build_learning_memory(user, question, out.get("answer", ""))
    confidence = _response_confidence(question, out.get("answer", ""), out.get("source", "unknown"))
    log_chat_observability(
        question=question,
        source=out.get("source", "unknown"),
        confidence=confidence,
        mode="authenticated",
        answer=out.get("answer", ""),
    )

    return {
        "assistant_name": "EDACHI Assistant",
        "answer": out.get("answer", ""),
        "cards": out.get("cards", []),
        "source": out.get("source", "unknown"),
        "confidence": confidence,
        "messages": session.get("messages", []),
    }

def build_guest_context() -> GuestEdachiContext:
    nifty = {}
    sensex = {}
    try:
        nifty = get_fast_quote("^NSEI")
    except Exception:
        nifty = {}
    try:
        sensex = get_fast_quote("^BSESN")
    except Exception:
        sensex = {}

    return GuestEdachiContext(
        markets={"nifty": nifty, "sensex": sensex},
        features=[
            "Portfolio tracking",
            "Trade management",
            "P/E and discount EDA charts",
            "Forecast and clustering",
            "Sentiment and report modules",
            "CSV import and auto portfolio creation",
        ],
    )


def _public_intent_answer(question: str, ctx: GuestEdachiContext) -> dict[str, Any] | None:
    q = (question or "").strip().lower()
    smalltalk = _smalltalk_intent_answer(question, is_authenticated=False)
    if smalltalk is not None:
        return smalltalk
    basics = _finance_basics_intent_answer(question)
    if basics is not None:
        return basics

    if _is_quote_query(question):
        symbol = _extract_symbol(question)
        if not symbol:
            return {"answer": "Share a symbol to fetch quote. Example: 'price of AAPL' or 'price of INFY.NS'.", "cards": []}
        try:
            quote = get_fast_quote(symbol)
        except Exception:
            quote = {}
        if quote.get("last_price") is not None:
            return {
                "answer": f"{symbol} last price is {quote.get('last_price')} ({quote.get('change_pct')}% today).",
                "cards": [{"type": "quote", "data": quote}],
            }
        return {"answer": f"I could not fetch live quote for {symbol} right now.", "cards": []}

    if _is_market_news_query(question):
        symbol = _extract_symbol(question)
        if symbol:
            try:
                payload = get_quick_stock_sentiment(symbol=symbol, company_name=None, force_refresh=False) or {}
            except Exception:
                payload = {}
            top_news = list(payload.get("top_news") or [])[:3]
            overall = payload.get("overall_signal") or {}
            if top_news:
                lines = [
                    f"- {str(n.get('headline') or 'Headline')} ({str(n.get('sentiment_label') or 'neutral').title()})"
                    for n in top_news
                ]
                return {
                    "answer": (
                        f"{symbol} sentiment snapshot: {overall.get('signal_label', 'Neutral')} "
                        f"(score {overall.get('sentiment_score', 0)}).\nTop news:\n" + "\n".join(lines)
                    ),
                    "cards": [{"type": "sentiment_stock", "data": payload}, {"type": "news", "items": top_news}],
                }

    if _looks_like_buy_reco_request(question):
        return {
            "answer": (
                "Great question. I cannot give direct investment advice, but I can share a review shortlist: "
                "INFY.NS, HDFCBANK.NS, TCS.NS, ITC.NS (India) or MSFT, AAPL, NVDA, JPM (US). "
                "If you login, I will personalize this using your holdings and risk exposure."
            ),
            "cards": [{"type": "recommendations", "items": ["INFY.NS", "HDFCBANK.NS", "TCS.NS", "ITC.NS", "MSFT", "AAPL", "NVDA", "JPM"]}],
        }

    if any(k in q for k in ["add to watchlist", "create alert", "new portfolio", "create portfolio", "remove from watchlist"]):
        return {
            "answer": "Action commands require login. Sign in to add watchlist items, create alerts, and create portfolios.",
            "cards": [{"type": "auth_required", "items": ["Login", "Add to watchlist", "Create alerts", "Create portfolios"]}],
        }

    if any(k in q for k in ["what is this", "about", "how it works", "platform"]):
        return {
            "answer": (
                "PortfolioAnalyzer helps retail investors track portfolios, run EDA (P/E, discount, forecast, cluster), "
                "and generate sentiment-driven insights."
            ),
            "cards": [{"type": "features", "items": ctx.features}],
        }

    if any(k in q for k in ["market", "nifty", "sensex", "today"]):
        n = ctx.markets.get("nifty") or {}
        s = ctx.markets.get("sensex") or {}
        return {
            "answer": (
                f"Nifty: {n.get('last_price', '--')} ({n.get('change_pct', '--')}%), "
                f"Sensex: {s.get('last_price', '--')} ({s.get('change_pct', '--')}%)."
            ),
            "cards": [{"type": "market", "data": ctx.markets}],
        }

    if any(k in q for k in ["login", "signup", "start", "create portfolio"]):
        return {
            "answer": (
                "Quick start: 1) Sign up / Login, 2) Create portfolio or import CSV, "
                "3) Add trades, 4) Open Analysis for sentiment + insights."
            ),
            "cards": [{"type": "onboarding", "items": ["Login", "Create portfolio", "Add trades", "Run analysis"]}],
        }

    return None


def _openai_generate_public(
    question: str,
    recent_messages: list[dict[str, Any]] | None = None,
    force_deep: bool = False,
) -> str | None:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return None
    q_lower = question.lower()
    deep = force_deep or (
        len(question) > 220
        or any(k in q_lower for k in ["strategy", "allocation", "rebalance", "risk", "compare", "valuation"])
    )
    model_chain = _ordered_model_chain(deep=deep, public=True)
    symbol = _extract_symbol(question)
    market_ctx: dict[str, Any] = {}
    if symbol:
        try:
            market_ctx["symbol_quote"] = get_fast_quote(symbol) or {}
        except Exception:
            pass
        try:
            sent = get_quick_stock_sentiment(symbol=symbol, company_name=None, force_refresh=False) or {}
            market_ctx["symbol_sentiment"] = {
                "overall_signal": sent.get("overall_signal"),
                "top_news": list(sent.get("top_news") or [])[:2],
            }
        except Exception:
            pass
    prompt = (
        f"System:\n{DEFAULT_SYSTEM_PROMPT}\n\n"
        f"Behavior:\n{ANALYST_STYLE_BLOCK}\n\n"
        "User is not logged in. Give general educational guidance and feature discovery help.\n"
        f"Market context:\n{json.dumps(market_ctx, ensure_ascii=True)}\n\n"
        f"Recent chat:\n{json.dumps((recent_messages or [])[-6:], ensure_ascii=True)}\n\n"
        f"Question:\n{question}\n\n"
        "Reply in markdown with sections: Direct answer, Practical steps, Optional follow-up question."
    )
    for model in model_chain:
        try:
            res = requests.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "input": prompt, "max_output_tokens": 420, "temperature": 0.25},
                timeout=20,
            )
            if not res.ok:
                continue
            data = res.json() or {}
            text = _extract_response_text(data)
            if text:
                return text
        except Exception:
            continue
    return None


def _response_confidence(question: str, answer: str, source: str) -> float:
    qn = _normalize_text(question)
    an = _normalize_text(answer)
    if not an:
        return 0.0
    base_map = {
        "llm": 0.74,
        "sentiment": 0.86,
        "market": 0.84,
        "action": 0.92,
        "rule": 0.78,
        "education": 0.8,
        "memory": 0.62,
        "curated_memory": 0.72,
        "fallback": 0.26,
        "unknown": 0.42,
    }
    score = float(base_map.get(source or "unknown", 0.5))
    if len(an) >= 60:
        score += 0.05
    if len(an) >= 140:
        score += 0.04
    q_tokens = set(qn.split())
    a_tokens = set(an.split())
    if q_tokens and a_tokens:
        overlap = len(q_tokens.intersection(a_tokens)) / float(max(1, len(q_tokens)))
        score += min(0.09, overlap * 0.15)
    if any(p in an for p in ["i may not", "try one of these", "cannot give direct"]):
        score -= 0.12
    return max(0.0, min(0.98, round(score, 4)))


def _llm_with_guardrails(question: str, ctx: EdachiContext, messages: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any]]:
    first = _openai_generate(question, ctx, messages, force_deep=False)
    first_conf = _response_confidence(question, first or "", "llm") if first else 0.0
    if first and first_conf >= 0.58:
        return first, {"retry_used": False, "confidence": first_conf}
    retry = _openai_generate(question, ctx, messages, force_deep=True)
    retry_conf = _response_confidence(question, retry or "", "llm") if retry else 0.0
    if retry and retry_conf >= first_conf:
        return retry, {"retry_used": True, "confidence": retry_conf}
    return first, {"retry_used": False, "confidence": first_conf}


def _llm_with_guardrails_public(question: str, recent_messages: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any]]:
    first = _openai_generate_public(question, recent_messages=recent_messages, force_deep=False)
    first_conf = _response_confidence(question, first or "", "llm") if first else 0.0
    if first and first_conf >= 0.58:
        return first, {"retry_used": False, "confidence": first_conf}
    retry = _openai_generate_public(question, recent_messages=recent_messages, force_deep=True)
    retry_conf = _response_confidence(question, retry or "", "llm") if retry else 0.0
    if retry and retry_conf >= first_conf:
        return retry, {"retry_used": True, "confidence": retry_conf}
    return first, {"retry_used": False, "confidence": first_conf}


def _answer_public_question_legacy(
    question: str,
    recent_messages: list[dict[str, Any]] | None = None,
    client_id: str = "",
) -> dict[str, Any]:
    question = (question or "").strip()
    if not question:
        return {
            "assistant_name": "EDACHI Assistant",
            "answer": "Ask me about markets, portfolio features, or how to start using this platform.",
            "cards": [],
            "source": "fallback",
        }

    ctx = build_guest_context()
    intent = _public_intent_answer(question, ctx)
    if intent is not None:
        out = {"assistant_name": "EDACHI Assistant", **intent, "source": "rule"}
    else:
        mem = _find_guest_memory_hit(client_id=client_id, question=question)
        if mem:
            out = {
                "assistant_name": "EDACHI Assistant",
                "answer": str(mem.get("a") or "").strip(),
                "cards": [{"type": "memory_hit", "data": {"learned_at": mem.get("at")}}],
                "source": "memory",
            }
        else:
            curated = _find_curated_memory_hit(question)
            if curated:
                out = {
                    "assistant_name": "EDACHI Assistant",
                    "answer": str(curated.get("a") or "").strip(),
                    "cards": [{"type": "curated_memory", "data": {"weight": curated.get("weight", 0)}}],
                    "source": "curated_memory",
                }
            else:
                llm_answer, llm_meta = _llm_with_guardrails_public(question, recent_messages=recent_messages or [])
                if llm_answer:
                    out = {
                        "assistant_name": "EDACHI Assistant",
                        "answer": llm_answer,
                        "cards": [{"type": "llm", "data": {"provider": "openai", **llm_meta}}],
                        "source": "llm",
                    }
                else:
                    out = {
                        "assistant_name": "EDACHI Assistant",
                        "answer": (
                            "I can still help even without a live model response. "
                            "Tell me your goal (learn investing basics, compare sectors, build first portfolio, or set risk rules), "
                            "and I will guide you step by step."
                        ),
                        "cards": [{"type": "features", "items": ctx.features}],
                        "source": "fallback",
                    }

    if client_id:
        _build_learning_memory_for_key(_guest_faq_key(client_id), question=question, answer=out.get("answer", ""))
    confidence = _response_confidence(question, out.get("answer", ""), out.get("source", "unknown"))
    out["confidence"] = confidence
    log_chat_observability(
        question=question,
        source=out.get("source", "unknown"),
        confidence=confidence,
        mode="guest",
        answer=out.get("answer", ""),
    )

    return out


def _use_langgraph() -> bool:
    flag = (os.getenv("EDACHI_USE_LANGGRAPH") or "1").strip().lower()
    return _LANGGRAPH_AVAILABLE and flag not in {"0", "false", "no", "off"}


def _route_out_or(next_node: str):
    def _route(state: dict[str, Any]) -> str:
        return END if state.get("out") else next_node

    return _route


def _auth_smalltalk_node(state: dict[str, Any]) -> dict[str, Any]:
    out = _smalltalk_intent_answer(state["question"], is_authenticated=True, brief=state.get("brief") or {})
    if out is not None:
        state["out"] = {**out, "source": "smalltalk"}
    return state


def _auth_basics_node(state: dict[str, Any]) -> dict[str, Any]:
    out = _finance_basics_intent_answer(state["question"])
    if out is not None:
        state["out"] = {**out, "source": "education"}
    return state


def _auth_action_node(state: dict[str, Any]) -> dict[str, Any]:
    out = _run_action_intent(state["user"], state["question"])
    if out is not None:
        state["out"] = out
    return state


def _auth_market_node(state: dict[str, Any]) -> dict[str, Any]:
    out = _market_intelligence_answer(state["user"], state["question"], state["ctx"])
    if out is not None:
        state["out"] = {**out, "source": "market"}
    return state


def _auth_sentiment_node(state: dict[str, Any]) -> dict[str, Any]:
    out = _sentiment_intent_answer(state["user"], state["question"], state["ctx"])
    if out is not None:
        state["out"] = {**out, "source": "sentiment"}
    return state


def _auth_memory_node(state: dict[str, Any]) -> dict[str, Any]:
    mem = _find_memory_hit(state["user"], state["question"])
    if mem:
        state["out"] = {
            "answer": str(mem.get("a") or "").strip(),
            "cards": [{"type": "memory_hit", "data": {"learned_at": mem.get("at")}}],
            "source": "memory",
        }
    return state


def _auth_curated_node(state: dict[str, Any]) -> dict[str, Any]:
    curated = _find_curated_memory_hit(state["question"])
    if curated:
        state["out"] = {
            "answer": str(curated.get("a") or "").strip(),
            "cards": [{"type": "curated_memory", "data": {"weight": curated.get("weight", 0)}}],
            "source": "curated_memory",
        }
    return state


def _auth_rule_node(state: dict[str, Any]) -> dict[str, Any]:
    out = _intent_answer(state["question"], state["ctx"])
    if out is not None:
        state["out"] = {**out, "source": "rule"}
    return state


def _auth_llm_node(state: dict[str, Any]) -> dict[str, Any]:
    llm_answer, llm_meta = _llm_with_guardrails(state["question"], state["ctx"], state.get("messages") or [])
    if llm_answer:
        state["out"] = {
            "answer": llm_answer,
            "cards": [{"type": "llm", "data": {"provider": "openai", **llm_meta}}],
            "source": "llm",
        }
    return state


def _auth_fallback_node(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("out"):
        return state
    state["out"] = {
        "answer": (
            "I can still help. Ask me about market basics, stock quotes, latest stock news, "
            "portfolio sentiment, recommendations, watchlist actions, or alerts.\n"
            "Examples:\n"
            "- what is stock market\n"
            "- latest news for INFY.NS\n"
            "- price of RELIANCE.NS\n"
            "- portfolio sentiment summary\n"
            "- recommend stocks based on my holdings"
        ),
        "cards": [{"type": "summary", "data": state.get("brief") or {}}],
        "source": "fallback",
    }
    return state


def _public_intent_node(state: dict[str, Any]) -> dict[str, Any]:
    out = _public_intent_answer(state["question"], state["ctx"])
    if out is not None:
        state["out"] = {"assistant_name": "EDACHI Assistant", **out, "source": "rule"}
    return state


def _public_memory_node(state: dict[str, Any]) -> dict[str, Any]:
    mem = _find_guest_memory_hit(client_id=state.get("client_id", ""), question=state["question"])
    if mem:
        state["out"] = {
            "assistant_name": "EDACHI Assistant",
            "answer": str(mem.get("a") or "").strip(),
            "cards": [{"type": "memory_hit", "data": {"learned_at": mem.get("at")}}],
            "source": "memory",
        }
    return state


def _public_curated_node(state: dict[str, Any]) -> dict[str, Any]:
    curated = _find_curated_memory_hit(state["question"])
    if curated:
        state["out"] = {
            "assistant_name": "EDACHI Assistant",
            "answer": str(curated.get("a") or "").strip(),
            "cards": [{"type": "curated_memory", "data": {"weight": curated.get("weight", 0)}}],
            "source": "curated_memory",
        }
    return state


def _public_llm_node(state: dict[str, Any]) -> dict[str, Any]:
    llm_answer, llm_meta = _llm_with_guardrails_public(state["question"], recent_messages=state.get("recent_messages") or [])
    if llm_answer:
        state["out"] = {
            "assistant_name": "EDACHI Assistant",
            "answer": llm_answer,
            "cards": [{"type": "llm", "data": {"provider": "openai", **llm_meta}}],
            "source": "llm",
        }
    return state


def _public_fallback_node(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("out"):
        return state
    state["out"] = {
        "assistant_name": "EDACHI Assistant",
        "answer": (
            "I can still help even without a live model response. "
            "Tell me your goal (learn investing basics, compare sectors, build first portfolio, or set risk rules), "
            "and I will guide you step by step."
        ),
        "cards": [{"type": "features", "items": state["ctx"].features}],
        "source": "fallback",
    }
    return state


@lru_cache(maxsize=1)
def _build_auth_graph():
    if not _use_langgraph() or StateGraph is None:
        return None
    g = StateGraph(dict)
    g.add_node("smalltalk", _auth_smalltalk_node)
    g.add_node("basics", _auth_basics_node)
    g.add_node("action", _auth_action_node)
    g.add_node("market", _auth_market_node)
    g.add_node("sentiment", _auth_sentiment_node)
    g.add_node("memory", _auth_memory_node)
    g.add_node("curated", _auth_curated_node)
    g.add_node("rule", _auth_rule_node)
    g.add_node("llm", _auth_llm_node)
    g.add_node("fallback", _auth_fallback_node)
    g.set_entry_point("smalltalk")
    g.add_conditional_edges("smalltalk", _route_out_or("basics"))
    g.add_conditional_edges("basics", _route_out_or("action"))
    g.add_conditional_edges("action", _route_out_or("market"))
    g.add_conditional_edges("market", _route_out_or("sentiment"))
    g.add_conditional_edges("sentiment", _route_out_or("memory"))
    g.add_conditional_edges("memory", _route_out_or("curated"))
    g.add_conditional_edges("curated", _route_out_or("rule"))
    g.add_conditional_edges("rule", _route_out_or("llm"))
    g.add_conditional_edges("llm", _route_out_or("fallback"))
    g.add_edge("fallback", END)
    return g.compile()


@lru_cache(maxsize=1)
def _build_public_graph():
    if not _use_langgraph() or StateGraph is None:
        return None
    g = StateGraph(dict)
    g.add_node("intent", _public_intent_node)
    g.add_node("memory", _public_memory_node)
    g.add_node("curated", _public_curated_node)
    g.add_node("llm", _public_llm_node)
    g.add_node("fallback", _public_fallback_node)
    g.set_entry_point("intent")
    g.add_conditional_edges("intent", _route_out_or("memory"))
    g.add_conditional_edges("memory", _route_out_or("curated"))
    g.add_conditional_edges("curated", _route_out_or("llm"))
    g.add_conditional_edges("llm", _route_out_or("fallback"))
    g.add_edge("fallback", END)
    return g.compile()


def answer_question(user, question: str) -> dict[str, Any]:
    question = (question or "").strip()
    if not question:
        return {
            "answer": (
                "Ask me about portfolios, holdings, sentiment, or actions like "
                "'add AAPL to watchlist' and 'create alert for INFY.NS above 1800'."
            ),
            "cards": [],
        }
    if not _use_langgraph():
        return _answer_question_legacy(user, question)

    try:
        ctx = build_context(user)
        brief = build_quick_brief(ctx)
        session = get_or_init_session(user)
        messages = list(session.get("messages") or [])
        graph = _build_auth_graph()
        if graph is None:
            return _answer_question_legacy(user, question)
        final_state = graph.invoke(
            {
                "question": question,
                "user": user,
                "ctx": ctx,
                "brief": brief,
                "messages": messages,
            }
        )
        out = dict(final_state.get("out") or {})
        if not out:
            return _answer_question_legacy(user, question)

        user_msg = {"role": "user", "content": question, "at": timezone.now().isoformat()}
        bot_msg = {"role": "assistant", "content": out.get("answer", ""), "at": timezone.now().isoformat(), "source": out.get("source")}
        messages.extend([user_msg, bot_msg])
        session["messages"] = messages[-24:]
        save_session(user, session)
        _build_learning_memory(user, question, out.get("answer", ""))
        confidence = _response_confidence(question, out.get("answer", ""), out.get("source", "unknown"))
        log_chat_observability(
            question=question,
            source=out.get("source", "unknown"),
            confidence=confidence,
            mode="authenticated",
            answer=out.get("answer", ""),
        )
        return {
            "assistant_name": "EDACHI Assistant",
            "answer": out.get("answer", ""),
            "cards": out.get("cards", []),
            "source": out.get("source", "unknown"),
            "confidence": confidence,
            "messages": session.get("messages", []),
            "orchestrator": "langgraph",
        }
    except Exception:
        return _answer_question_legacy(user, question)


def answer_public_question(
    question: str,
    recent_messages: list[dict[str, Any]] | None = None,
    client_id: str = "",
) -> dict[str, Any]:
    question = (question or "").strip()
    if not question:
        return {
            "assistant_name": "EDACHI Assistant",
            "answer": "Ask me about markets, portfolio features, or how to start using this platform.",
            "cards": [],
            "source": "fallback",
        }
    if not _use_langgraph():
        return _answer_public_question_legacy(question, recent_messages=recent_messages, client_id=client_id)

    try:
        ctx = build_guest_context()
        graph = _build_public_graph()
        if graph is None:
            return _answer_public_question_legacy(question, recent_messages=recent_messages, client_id=client_id)
        final_state = graph.invoke(
            {
                "question": question,
                "ctx": ctx,
                "recent_messages": list(recent_messages or []),
                "client_id": client_id,
            }
        )
        out = dict(final_state.get("out") or {})
        if not out:
            return _answer_public_question_legacy(question, recent_messages=recent_messages, client_id=client_id)
        if client_id:
            _build_learning_memory_for_key(_guest_faq_key(client_id), question=question, answer=out.get("answer", ""))
        confidence = _response_confidence(question, out.get("answer", ""), out.get("source", "unknown"))
        out["confidence"] = confidence
        out["orchestrator"] = "langgraph"
        log_chat_observability(
            question=question,
            source=out.get("source", "unknown"),
            confidence=confidence,
            mode="guest",
            answer=out.get("answer", ""),
        )
        return out
    except Exception:
        return _answer_public_question_legacy(question, recent_messages=recent_messages, client_id=client_id)

