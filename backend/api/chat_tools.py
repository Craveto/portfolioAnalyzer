from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from typing import Any

from django.utils import timezone

from analysis.provider import get_quick_stock_sentiment
from .models import CachedPayload
from .yf_client import get_52w_range, get_fast_quote, get_fundamentals, search_equities
from portfolio.models import Stock


def normalize_text(text: str) -> str:
    t = (text or "").lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def extract_symbol(question: str) -> str:
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
        "LATEST",
        "NEWS",
        "PRICE",
        "QUOTE",
        "STOCK",
        "MARKET",
        "TODAY",
        "UPDATE",
        "SUGGEST",
        "RECOMMEND",
        "AND",
    }
    for raw in candidates:
        sym = raw.upper()
        if sym not in stop:
            return sym
    return ""


def _round_or_none(v, nd: int = 2):
    try:
        return round(float(v), nd)
    except Exception:
        return None


def _sector_distribution(holdings: list[dict[str, Any]]) -> list[tuple[str, int]]:
    m: dict[str, int] = {}
    for h in holdings:
        sec = str(h.get("sector") or "Uncategorized").strip() or "Uncategorized"
        m[sec] = m.get(sec, 0) + 1
    return sorted(m.items(), key=lambda x: x[1], reverse=True)


def compute_recommendations(ctx, limit: int = 6) -> list[dict[str, Any]]:
    holdings = list(getattr(ctx, "holdings", []) or [])
    portfolios = list(getattr(ctx, "portfolios", []) or [])
    held_symbols = {str(h.get("symbol") or "").upper() for h in holdings}
    market = str((portfolios[0]["market"] if portfolios else "IN") or "IN").upper()
    sectors = _sector_distribution(holdings)
    allowed_sector_keys = {normalize_text(name) for name, _count in sectors if normalize_text(name) and normalize_text(name) != "uncategorized"}
    # Strict policy: recommend only from sectors already present in this portfolio.
    if not allowed_sector_keys:
        return []

    sector_queries = [name for name, _count in sectors[:6] if normalize_text(name) in allowed_sector_keys]
    queries = sector_queries[:6]
    merged: dict[str, dict[str, Any]] = {}

    for q in queries:
        try:
            rows = search_equities(q, max_results=18) or []
        except Exception:
            rows = []
        for item in rows:
            sym = str(item.get("symbol") or "").upper().strip()
            if not sym or sym in held_symbols or sym in merged:
                continue
            sec_obj = item.get("sector")
            if isinstance(sec_obj, dict):
                raw_sector = str(sec_obj.get("name") or "").strip()
            else:
                raw_sector = str(sec_obj or "").strip()
            if raw_sector and normalize_text(raw_sector) not in allowed_sector_keys:
                continue
            merged[sym] = item
            if len(merged) >= 18:
                break
        if len(merged) >= 18:
            break

    fallback_in = ["RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "LT.NS", "ITC.NS", "SUNPHARMA.NS", "BHARTIARTL.NS"]
    fallback_us = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "UNH"]
    for sym in (fallback_in if market == "IN" else fallback_us):
        if sym not in held_symbols and sym not in merged:
            merged[sym] = {"symbol": sym, "name": sym, "exchange": "NSE/BSE" if "." in sym else "US"}

    selected = list(merged.items())[:18]
    selected_symbols = [sym for sym, _item in selected]
    db_sector_map: dict[str, str] = {}
    if selected_symbols:
        qs = Stock.objects.filter(symbol__in=selected_symbols).select_related("sector")
        for s in qs:
            db_sector_map[str(s.symbol).upper()] = str(s.sector.name if s.sector_id else "")

    market_data: dict[str, dict[str, Any]] = {}

    def _fetch_market_pack(symbol: str) -> dict[str, Any]:
        out = {"quote": {}, "fundamentals": {}, "r52": {}}
        try:
            out["quote"] = get_fast_quote(symbol) or {}
        except Exception:
            out["quote"] = {}
        try:
            out["fundamentals"] = get_fundamentals(symbol) or {}
        except Exception:
            out["fundamentals"] = {}
        try:
            out["r52"] = get_52w_range(symbol) or {}
        except Exception:
            out["r52"] = {}
        return out

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_fetch_market_pack, sym): sym for sym, _item in selected}
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                market_data[sym] = fut.result() or {"quote": {}, "fundamentals": {}, "r52": {}}
            except Exception:
                market_data[sym] = {"quote": {}, "fundamentals": {}, "r52": {}}

    ranked: list[dict[str, Any]] = []
    for sym, item in selected:
        sector_label = ""
        if isinstance(item.get("sector"), dict):
            sector_label = str((item.get("sector") or {}).get("name") or "").strip()
        else:
            sector_label = str(item.get("sector") or "").strip()
        if not sector_label:
            sector_label = db_sector_map.get(sym, "")
        sector_key = normalize_text(sector_label)
        if sector_key not in allowed_sector_keys:
            continue

        pack = market_data.get(sym) or {}
        quote = dict(pack.get("quote") or {})
        fundamentals = dict(pack.get("fundamentals") or {})
        r52 = dict(pack.get("r52") or {})

        last = _round_or_none(quote.get("last_price"), 2)
        pe = _round_or_none(fundamentals.get("trailingPE") or fundamentals.get("forwardPE"), 2)
        high_52w = _round_or_none(r52.get("high_52w"), 2)
        discount = None
        if last is not None and high_52w and high_52w > 0:
            try:
                discount = round(((high_52w - last) / high_52w) * 100, 2)
            except Exception:
                discount = None

        score = 0.0
        if pe is not None and 8 <= pe <= 28:
            score += 18
        if discount is not None and 6 <= discount <= 35:
            score += 22
        if last is not None and last > 0:
            score += 8

        reasons = []
        if pe is not None and pe <= 22:
            reasons.append("Reasonable P/E")
        if discount is not None and discount >= 10:
            reasons.append("Pullback from 52W high")
        if not reasons:
            reasons.append("Liquid large-cap candidate")

        ranked.append(
            {
                "symbol": sym,
                "name": str(item.get("name") or sym),
                "exchange": str(item.get("exchange") or "--"),
                "sector": sector_label or "--",
                "score": round(score, 2),
                "last_price": last,
                "pe": pe,
                "discount_from_52w_high_pct": discount,
                "reasons": ["Sector aligned"] + reasons,
            }
        )

    ranked.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    return ranked[:limit]


def build_market_intel(question: str, user=None, ctx=None, include_recommendations: bool = True) -> dict[str, Any]:
    symbol = extract_symbol(question)
    snapshot: dict[str, Any] = {
        "question": question,
        "symbol": symbol,
        "generated_at": timezone.now().isoformat(),
    }
    try:
        snapshot["indices"] = {"nifty": get_fast_quote("^NSEI"), "sensex": get_fast_quote("^BSESN")}
    except Exception:
        snapshot["indices"] = {"nifty": {}, "sensex": {}}

    if symbol:
        try:
            snapshot["quote"] = get_fast_quote(symbol) or {}
        except Exception:
            snapshot["quote"] = {}
        try:
            sentiment = get_quick_stock_sentiment(symbol=symbol, company_name=None, force_refresh=False) or {}
        except Exception:
            sentiment = {}
        snapshot["sentiment"] = {
            "overall_signal": sentiment.get("overall_signal"),
            "score_breakdown": sentiment.get("score_breakdown"),
            "top_news": list(sentiment.get("top_news") or [])[:5],
        }

    if include_recommendations and user is not None and ctx is not None:
        try:
            snapshot["recommendations"] = compute_recommendations(ctx, limit=6)
        except Exception:
            snapshot["recommendations"] = []

    return snapshot


def _obs_events_key() -> str:
    return "edachi:obs:events"


def _obs_gaps_key() -> str:
    return "edachi:obs:gaps"


def log_chat_observability(question: str, source: str, confidence: float, mode: str, answer: str) -> None:
    qn = normalize_text(question)
    item = {
        "q": (question or "")[:500],
        "qn": qn[:500],
        "source": (source or "")[:24],
        "confidence": round(float(confidence or 0.0), 4),
        "mode": (mode or "guest")[:24],
        "answer_len": len((answer or "").strip()),
        "at": timezone.now().isoformat(),
    }

    row, _ = CachedPayload.objects.get_or_create(key=_obs_events_key(), defaults={"payload": {"items": []}})
    payload = dict(row.payload or {"items": []})
    items = list(payload.get("items") or [])
    items.append(item)
    payload["items"] = items[-1200:]
    row.payload = payload
    row.save(update_fields=["payload", "updated_at"])

    unresolved = source in {"fallback", "unknown"} or float(confidence or 0.0) < 0.42
    if unresolved and qn:
        gap_row, _ = CachedPayload.objects.get_or_create(key=_obs_gaps_key(), defaults={"payload": {"counts": {}}})
        gp = dict(gap_row.payload or {"counts": {}})
        counts = dict(gp.get("counts") or {})
        counts[qn] = int(counts.get(qn, 0) or 0) + 1
        gp["counts"] = counts
        gap_row.payload = gp
        gap_row.save(update_fields=["payload", "updated_at"])


def chat_observability_dashboard() -> dict[str, Any]:
    ev_row = CachedPayload.objects.filter(key=_obs_events_key()).first()
    gap_row = CachedPayload.objects.filter(key=_obs_gaps_key()).first()
    events = list((ev_row.payload or {}).get("items") or []) if ev_row else []
    counts = dict((gap_row.payload or {}).get("counts") or {}) if gap_row else {}

    total = len(events)
    unresolved = [e for e in events if str(e.get("source") or "") in {"fallback", "unknown"} or float(e.get("confidence") or 0) < 0.42]
    low_conf = [e for e in events if float(e.get("confidence") or 0) < 0.55]

    by_source: dict[str, int] = {}
    for e in events:
        s = str(e.get("source") or "unknown")
        by_source[s] = by_source.get(s, 0) + 1

    top_gaps = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:15]

    return {
        "summary": {
            "total_events": total,
            "unresolved_events": len(unresolved),
            "low_confidence_events": len(low_conf),
            "source_mix": by_source,
        },
        "top_knowledge_gaps": [{"question_norm": k, "count": v} for k, v in top_gaps],
        "recent_unresolved": unresolved[-20:],
        "updated_at": timezone.now().isoformat(),
    }


def curate_chat_memory(min_helpful: int = 1, max_items: int = 800) -> dict[str, Any]:
    min_helpful = max(1, int(min_helpful or 1))
    max_items = max(100, int(max_items or 800))
    weighted: dict[str, dict[str, Any]] = {}
    helpful_votes: dict[str, int] = defaultdict(int)
    unhelpful_votes: dict[str, int] = defaultdict(int)

    feedback_rows = CachedPayload.objects.filter(key__startswith="edachi:feedback:")
    for row in feedback_rows:
        items = list((row.payload or {}).get("items") or [])
        for it in items:
            q = str(it.get("q") or "").strip()
            a = str(it.get("a") or "").strip()
            src = str(it.get("source") or "").strip().lower()
            if len(q) < 6 or len(a) < 20:
                continue
            qn = normalize_text(q)
            if not qn:
                continue
            if bool(it.get("helpful")):
                helpful_votes[qn] += 1
            else:
                unhelpful_votes[qn] += 1
            if src in {"fallback", "unknown"}:
                continue
            cur = weighted.get(qn)
            candidate = {
                "q": q[:500],
                "a": a[:1800],
                "source": src[:40],
                "at": str(it.get("at") or timezone.now().isoformat()),
            }
            if cur is None or len(candidate["a"]) > len(str(cur.get("a") or "")):
                weighted[qn] = candidate

    faq_rows = CachedPayload.objects.filter(key__startswith="edachi:faq:")
    for row in faq_rows:
        pairs = list((row.payload or {}).get("pairs") or [])
        for p in pairs:
            q = str(p.get("q") or "").strip()
            a = str(p.get("a") or "").strip()
            if len(q) < 8 or len(a) < 40:
                continue
            qn = normalize_text(q)
            if not qn or qn in weighted:
                continue
            weighted[qn] = {
                "q": q[:500],
                "a": a[:1800],
                "source": "faq_memory",
                "at": str(p.get("at") or timezone.now().isoformat()),
            }

    curated: list[dict[str, Any]] = []
    for qn, row in weighted.items():
        ups = int(helpful_votes.get(qn, 0))
        downs = int(unhelpful_votes.get(qn, 0))
        net = ups - downs
        if ups < min_helpful and row.get("source") != "faq_memory":
            continue
        if net < -1:
            continue
        curated.append(
            {
                "q": row["q"],
                "a": row["a"],
                "qn": qn,
                "source": row.get("source", ""),
                "weight": max(0, net + ups),
                "helpful": ups,
                "unhelpful": downs,
                "at": row.get("at"),
            }
        )

    curated.sort(key=lambda x: (int(x.get("weight") or 0), int(x.get("helpful") or 0), len(str(x.get("a") or ""))), reverse=True)
    curated = curated[:max_items]
    payload = {
        "items": curated,
        "meta": {
            "generated_at": timezone.now().isoformat(),
            "count": len(curated),
            "min_helpful": min_helpful,
            "max_items": max_items,
        },
    }
    CachedPayload.objects.update_or_create(key="edachi:curated_memory:v1", defaults={"payload": payload})
    return {"ok": True, "count": len(curated), "min_helpful": min_helpful, "max_items": max_items}
