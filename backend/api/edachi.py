from __future__ import annotations

import json
import os
import re
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
from .yf_client import get_fast_quote


DEFAULT_SYSTEM_PROMPT = (
    "You are EDACHI Assistant for PortfolioAnalyzer. "
    "Be concise, practical, educational, and data-driven. "
    "Never provide definitive investment advice. "
    "Prefer portfolio-specific insights, risk framing, and clear next steps."
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
                "I am EDACHI, your AI copilot for PortfolioAnalyzer. I can do conversational Q&A, explain features, "
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


def _intent_answer(question: str, ctx: EdachiContext) -> dict[str, Any] | None:
    q = _normalize_text(question)
    brief = build_quick_brief(ctx)

    if any(k in q for k in ["portfolio list", "my portfolios", "show portfolios", "portfolio names"]):
        lines = [f"{i + 1}. {p['name']} ({p['market']})" for i, p in enumerate(ctx.portfolios[:12])]
        txt = "Here are your portfolios:\n" + ("\n".join(lines) if lines else "No portfolios yet.")
        return {"answer": txt, "cards": [{"type": "portfolios", "items": ctx.portfolios[:12]}]}

    if any(k in q for k in ["stock list", "my stocks", "holdings list", "show holdings"]):
        rows = ctx.holdings[:20]
        if not rows:
            return {"answer": "You do not have holdings yet. Add your first trade to start insights.", "cards": []}
        lines = [f"- {h['symbol']} ({h['portfolio_name']}) qty {h['qty']}" for h in rows]
        return {"answer": "Current holdings snapshot:\n" + "\n".join(lines), "cards": [{"type": "holdings", "items": rows}]}

    if any(k in q for k in ["summary", "overview", "health", "status"]):
        answer = (
            f"You currently have {brief['portfolios']} portfolios and {brief['holdings']} holdings. "
            f"Estimated cost exposure is {brief['estimated_cost_exposure']:.2f}. "
            f"Top sectors: "
            + ", ".join([f"{x['name']} ({x['count']})" for x in brief["top_sectors"][:3]])
        )
        return {"answer": answer, "cards": [{"type": "summary", "data": brief}]}

    if any(k in q for k in ["recommend", "what to add", "suggest stock", "next stock"]) or _looks_like_buy_reco_request(question):
        # Lightweight recommendation based on user's top sector and market.
        market = (ctx.portfolios[0]["market"] if ctx.portfolios else "IN").upper()
        top_sector = (brief["top_sectors"][0]["name"] if brief["top_sectors"] else "Technology").lower()
        if market == "IN":
            base = ["INFY.NS", "TCS.NS", "HDFCBANK.NS", "ITC.NS", "SUNPHARMA.NS", "LT.NS"]
        else:
            base = ["MSFT", "AAPL", "NVDA", "AMZN", "JPM", "UNH"]
        held = {str(h["symbol"]).upper() for h in ctx.holdings}
        picks = [s for s in base if s.upper() not in held][:4]
        msg = (
            f"Top sector in your portfolio is {top_sector.title()}. "
            f"Shortlist for review: {', '.join(picks) if picks else 'No fresh symbols (already held)'}."
        )
        return {"answer": msg, "cards": [{"type": "recommendations", "items": picks}]}

    return None


def _build_learning_memory(user, question: str, answer: str) -> None:
    key = _faq_key(user.id)
    row, _ = CachedPayload.objects.get_or_create(key=key, defaults={"payload": {"pairs": []}})
    payload = dict(row.payload or {"pairs": []})
    pairs = list(payload.get("pairs") or [])
    pairs.append(
        {
            "q": question[:500],
            "a": answer[:1500],
            "at": timezone.now().isoformat(),
        }
    )
    payload["pairs"] = pairs[-40:]
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
    row = CachedPayload.objects.filter(key=_feedback_key(user.id)).first()
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
    key = _faq_key(user.id)
    row = CachedPayload.objects.filter(key=key).first()
    if not row:
        return None
    payload = dict(row.payload or {})
    pairs = payload.get("pairs") or []
    qn = _normalize_text(question)
    if len(qn) < 8:
        return None
    feedback_scores = _feedback_scores_for_user(user)
    best = None
    best_score = 0.0
    for p in reversed(pairs):
        q0 = _normalize_text(str(p.get("q") or ""))
        if not q0:
            continue
        if q0 == qn or q0 in qn or qn in q0:
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


def _openai_generate(question: str, ctx: EdachiContext, session_messages: list[dict[str, Any]]) -> str | None:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return None

    model_fast = (os.getenv("EDACHI_MODEL_FAST") or "gpt-5.4-mini").strip()
    model_reasoning = (os.getenv("EDACHI_MODEL_REASONING") or "gpt-5.4").strip()
    fallback_fast = (os.getenv("EDACHI_MODEL_FAST_FALLBACK") or "gpt-4.1-mini").strip()
    fallback_reasoning = (os.getenv("EDACHI_MODEL_REASONING_FALLBACK") or "gpt-4.1").strip()
    q_lower = question.lower()
    deep = (
        len(question) > 220
        or any(k in q_lower for k in ["strategy", "allocation", "rebalance", "risk model", "compare scenarios", "drawdown"])
    )
    primary = model_reasoning if deep else model_fast
    secondary = fallback_reasoning if deep else fallback_fast
    model_chain = [m for m in [primary, secondary] if m]
    recent = session_messages[-8:] if session_messages else []
    context_payload = {
        "user": {"id": ctx.user_id, "username": ctx.username},
        "portfolio_count": len(ctx.portfolios),
        "holding_count": len(ctx.holdings),
        "top_portfolios": ctx.portfolios[:6],
        "top_holdings": build_quick_brief(ctx).get("top_holdings", [])[:8],
        "top_sectors": build_quick_brief(ctx).get("top_sectors", [])[:6],
        "timestamp": timezone.now().isoformat(),
    }
    prompt = (
        f"System:\n{DEFAULT_SYSTEM_PROMPT}\n\n"
        f"Context JSON:\n{json.dumps(context_payload, ensure_ascii=True)}\n\n"
        f"Recent chat:\n{json.dumps(recent, ensure_ascii=True)}\n\n"
        f"User question:\n{question}\n\n"
        "Return concise markdown with: answer, rationale bullets, and one practical next step."
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
                    "max_output_tokens": 380,
                    "temperature": 0.2,
                },
                timeout=18,
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

    ctx = build_context(user)
    brief = build_quick_brief(ctx)
    session = get_or_init_session(user)
    messages = list(session.get("messages") or [])

    smalltalk = _smalltalk_intent_answer(question, is_authenticated=True, brief=brief)
    if smalltalk is not None:
        out = {**smalltalk, "source": "smalltalk"}
    else:
        action_out = _run_action_intent(user, question)
        if action_out is not None:
            out = action_out
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
                    intent = _intent_answer(question, ctx)
                    if intent is not None:
                        out = {**intent, "source": "rule"}
                    else:
                        llm_answer = _openai_generate(question, ctx, messages)
                        if llm_answer:
                            out = {"answer": llm_answer, "cards": [{"type": "llm", "data": {"provider": "openai"}}], "source": "llm"}
                        else:
                            out = {
                                "answer": (
                                    "I am here with you. I may not have a precise answer for that yet, but I can still help. "
                                    "Try one of these:\n"
                                    "- 'show my portfolio list'\n"
                                    "- 'portfolio sentiment summary'\n"
                                    "- 'add AAPL to watchlist'\n"
                                    "- 'create alert for INFY.NS above 1800'\n"
                                    "- 'recommend stocks based on my holdings'"
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

    return {
        "assistant_name": "EDACHI Assistant",
        "answer": out.get("answer", ""),
        "cards": out.get("cards", []),
        "source": out.get("source", "unknown"),
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


def _openai_generate_public(question: str, recent_messages: list[dict[str, Any]] | None = None) -> str | None:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return None
    model_fast = (os.getenv("EDACHI_MODEL_FAST") or "gpt-5.4-mini").strip()
    model_reasoning = (os.getenv("EDACHI_MODEL_REASONING") or "gpt-5.4").strip()
    fallback_fast = (os.getenv("EDACHI_MODEL_FAST_FALLBACK") or "gpt-4.1-mini").strip()
    fallback_reasoning = (os.getenv("EDACHI_MODEL_REASONING_FALLBACK") or "gpt-4.1").strip()
    q_lower = question.lower()
    deep = (
        len(question) > 220
        or any(k in q_lower for k in ["strategy", "allocation", "rebalance", "risk", "compare"])
    )
    primary = model_reasoning if deep else model_fast
    secondary = fallback_reasoning if deep else fallback_fast
    model_chain = [m for m in [primary, secondary] if m]
    prompt = (
        f"System:\n{DEFAULT_SYSTEM_PROMPT}\n\n"
        "User is not logged in. Give general educational guidance and feature discovery help.\n"
        f"Recent chat:\n{json.dumps((recent_messages or [])[-6:], ensure_ascii=True)}\n\n"
        f"Question:\n{question}\n\n"
        "Return concise markdown with practical app-focused guidance."
    )
    for model in model_chain:
        try:
            res = requests.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "input": prompt, "max_output_tokens": 280, "temperature": 0.2},
                timeout=16,
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


def answer_public_question(question: str, recent_messages: list[dict[str, Any]] | None = None) -> dict[str, Any]:
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
        return {"assistant_name": "EDACHI Assistant", **intent, "source": "rule"}

    llm_answer = _openai_generate_public(question, recent_messages=recent_messages or [])
    if llm_answer:
        return {
            "assistant_name": "EDACHI Assistant",
            "answer": llm_answer,
            "cards": [{"type": "llm", "data": {"provider": "openai"}}],
            "source": "llm",
        }

    return {
        "assistant_name": "EDACHI Assistant",
        "answer": (
            "I am here. I may not have the exact answer to that yet, but I can still help right now. "
            "Try: 'How to start?', 'What features do you have?', 'Show market snapshot', or 'How does sentiment work?'."
        ),
        "cards": [{"type": "features", "items": ctx.features}],
        "source": "fallback",
    }

