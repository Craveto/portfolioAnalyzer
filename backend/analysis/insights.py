from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
import math
import re

import yfinance as yf
from django.utils import timezone

from api.yf_client import get_52w_range, get_fast_quote, get_fundamentals
from portfolio.models import Holding, Portfolio


POSITIVE_TERMS = {
    "beat": 0.9,
    "beats": 0.9,
    "growth": 0.7,
    "surge": 0.85,
    "strong": 0.55,
    "expands": 0.65,
    "expansion": 0.65,
    "upgrade": 0.85,
    "bullish": 0.9,
    "profit": 0.75,
    "record": 0.75,
    "partnership": 0.55,
    "order win": 0.7,
    "wins": 0.7,
    "approval": 0.65,
    "dividend": 0.45,
    "buyback": 0.55,
}

NEGATIVE_TERMS = {
    "miss": -0.95,
    "misses": -0.95,
    "weak": -0.55,
    "fall": -0.7,
    "falls": -0.7,
    "drops": -0.7,
    "decline": -0.75,
    "downgrade": -0.9,
    "lawsuit": -1.0,
    "probe": -0.9,
    "fraud": -1.0,
    "risk": -0.65,
    "warning": -0.85,
    "cuts": -0.75,
    "cut": -0.75,
    "loss": -0.85,
    "pressure": -0.6,
    "delay": -0.55,
    "resigns": -0.8,
}

EVENT_PATTERNS = {
    "earnings": ["earnings", "q1", "q2", "q3", "q4", "results", "profit", "revenue"],
    "analyst_rating": ["upgrade", "downgrade", "target price", "brokerage", "rating"],
    "guidance": ["guidance", "outlook", "forecast", "margin", "demand outlook"],
    "legal": ["lawsuit", "court", "probe", "regulator", "penalty", "compliance"],
    "product": ["launch", "product", "deal", "contract", "order", "platform"],
    "management": ["ceo", "cfo", "management", "resigns", "appoints", "board"],
    "macro": ["rates", "inflation", "rupee", "usd", "oil", "macro", "economy"],
    "merger_acquisition": ["acquisition", "merger", "stake", "buyout"],
    "dividend": ["dividend", "buyback", "payout", "bonus"],
}

RISK_EVENT_TYPES = {"legal", "guidance", "management", "analyst_rating", "macro"}


def _safe_float(value) -> float | None:
    try:
        out = float(value)
        return out if math.isfinite(out) else None
    except Exception:
        return None


def _to_iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=dt_timezone.utc).isoformat()
        except Exception:
            return None
    if isinstance(value, str):
        try:
            return parsedate_to_datetime(value).isoformat()
        except Exception:
            return value
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        return value.isoformat()
    return None


def _parse_published(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=dt_timezone.utc)
        except Exception:
            return None
    if isinstance(value, str):
        try:
            dt = parsedate_to_datetime(value)
        except Exception:
            return None
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return dt.astimezone(dt_timezone.utc)
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        return value.astimezone(dt_timezone.utc)
    return None


def _clean_text(*parts: str | None) -> str:
    text = " ".join((part or "").strip() for part in parts if part)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _event_type(text: str) -> str:
    lowered = text.lower()
    for event_type, keywords in EVENT_PATTERNS.items():
        if any(keyword in lowered for keyword in keywords):
            return event_type
    return "other"


def _impact_level(text: str, score: float, event_type: str) -> str:
    if event_type in {"earnings", "legal", "guidance", "merger_acquisition"} or abs(score) >= 0.85:
        return "high"
    if event_type in {"analyst_rating", "management", "macro", "product"} or abs(score) >= 0.45:
        return "medium"
    return "low"


def _relevance_score(text: str, ticker: str, company_name: str) -> float:
    lowered = text.lower()
    score = 0.35
    if ticker.lower().split(".")[0] in lowered:
        score += 0.35
    if company_name and company_name.lower() in lowered:
        score += 0.3
    return round(min(score, 1.0), 2)


def _keyword_sentiment(text: str) -> tuple[str, float, int]:
    lowered = text.lower()
    score = 0.0
    for term, weight in POSITIVE_TERMS.items():
        if term in lowered:
            score += weight
    for term, weight in NEGATIVE_TERMS.items():
        if term in lowered:
            score += weight

    if score >= 0.3:
        return "positive", min(abs(score) / 2.3, 0.99), 1
    if score <= -0.3:
        return "negative", min(abs(score) / 2.3, 0.99), -1
    return "neutral", min((abs(score) + 0.15) / 1.2, 0.7), 0


def _short_explanation(event_type: str, sentiment_label: str) -> str:
    event_labels = {
        "earnings": "Earnings commentary is driving the tone",
        "analyst_rating": "Broker sentiment is influencing the move",
        "guidance": "Forward outlook is shaping near-term expectations",
        "legal": "Regulatory or legal headlines are adding risk",
        "product": "Business execution news is influencing sentiment",
        "management": "Leadership developments are affecting confidence",
        "macro": "Macro conditions are shaping the near-term mood",
        "merger_acquisition": "Deal activity is moving the narrative",
        "dividend": "Shareholder return signals are supporting interest",
        "other": "General market commentary is shaping the tone",
    }
    prefix = {"positive": "Positive:", "negative": "Caution:", "neutral": "Watch:"}.get(sentiment_label, "Watch:")
    return f"{prefix} {event_labels.get(event_type, event_labels['other'])}"


def _fallback_news(symbol: str, company_name: str, market_context: dict) -> list[dict]:
    change_pct = market_context.get("daily_change_pct")
    pe = market_context.get("pe")
    last_price = market_context.get("last_price")
    score = 0.35 if (change_pct or 0) > 0 else (-0.35 if (change_pct or 0) < 0 else 0.0)
    headline = (
        f"{company_name or symbol} market snapshot shows price at {last_price or 'N/A'} with daily move "
        f"{round(change_pct, 2) if change_pct is not None else 'N/A'}%"
    )
    extra = f"P/E context currently sits near {round(pe, 2)}." if pe is not None else "Valuation context is limited right now."
    return [
        {
            "headline": headline,
            "summary": extra,
            "publisher": "PortfolioAnalyzer",
            "link": "",
            "providerPublishTime": timezone.now().timestamp(),
            "_fallback_score": score,
        }
    ]


def _stock_market_context(symbol: str) -> dict:
    quote = get_fast_quote(symbol)
    fundamentals = get_fundamentals(symbol)
    range_52w = get_52w_range(symbol)

    last_price = _safe_float(quote.get("last_price"))
    previous_close = _safe_float(quote.get("previous_close"))
    day_change_pct = None
    if last_price is not None and previous_close not in (None, 0):
        day_change_pct = ((last_price - previous_close) / previous_close) * 100.0

    low_52w = _safe_float(range_52w.get("low_52w"))
    high_52w = _safe_float(range_52w.get("high_52w"))
    range_position_pct = None
    if last_price is not None and low_52w is not None and high_52w is not None and high_52w != low_52w:
        range_position_pct = ((last_price - low_52w) / (high_52w - low_52w)) * 100.0

    return {
        "last_price": last_price,
        "previous_close": previous_close,
        "daily_change_pct": day_change_pct,
        "pe": _safe_float(fundamentals.get("trailingPE") or fundamentals.get("forwardPE")),
        "market_cap": _safe_float(fundamentals.get("marketCap")),
        "sector": fundamentals.get("sector"),
        "industry": fundamentals.get("industry"),
        "low_52w": low_52w,
        "high_52w": high_52w,
        "range_position_pct": range_position_pct,
    }


def build_stock_sentiment_insight(portfolio: Portfolio, symbol: str) -> dict:
    holding = (
        Holding.objects.filter(portfolio=portfolio, stock__symbol=symbol)
        .select_related("stock", "stock__sector")
        .first()
    )
    if holding is None:
        raise Holding.DoesNotExist(f"No holding found for {symbol} in portfolio {portfolio.id}")

    company_name = holding.stock.name or symbol
    market_context = _stock_market_context(symbol)

    try:
        raw_news = list(getattr(yf.Ticker(symbol), "news", None) or [])
    except Exception:
        raw_news = []
    if not raw_news:
        raw_news = _fallback_news(symbol, company_name, market_context)

    now = timezone.now().astimezone(dt_timezone.utc)
    scored_news = []
    seen = set()
    for item in raw_news[:15]:
        headline = _clean_text(item.get("title") or item.get("headline"), item.get("summary"))
        if not headline:
            continue
        dedupe_key = headline.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        summary = _clean_text(item.get("summary") or item.get("description"))
        text = _clean_text(headline, summary)
        event_type = _event_type(text)
        sentiment_label, confidence_score, normalized_score = _keyword_sentiment(text)

        fallback_score = item.get("_fallback_score")
        if fallback_score is not None and normalized_score == 0:
            normalized_score = 1 if fallback_score > 0.12 else (-1 if fallback_score < -0.12 else 0)
            sentiment_label = "positive" if normalized_score > 0 else ("negative" if normalized_score < 0 else "neutral")
            confidence_score = max(confidence_score, abs(float(fallback_score)))

        published_dt = _parse_published(item.get("providerPublishTime") or item.get("published_at"))
        hours_old = ((now - published_dt).total_seconds() / 3600.0) if published_dt else 72.0
        recency_weight = 1.0 if hours_old <= 24 else (0.72 if hours_old <= 72 else 0.5)
        relevance_score = _relevance_score(text, symbol, company_name)
        impact_level = _impact_level(text, float(normalized_score), event_type)
        impact_weight = {"low": 0.7, "medium": 1.0, "high": 1.35}[impact_level]
        weighted_score = normalized_score * confidence_score * recency_weight * relevance_score * impact_weight

        scored_news.append(
            {
                "ticker": symbol,
                "headline": headline,
                "source": item.get("publisher") or item.get("provider") or "Yahoo Finance",
                "url": item.get("link") or item.get("url") or "",
                "published_at": _to_iso(published_dt),
                "sentiment_label": sentiment_label,
                "confidence_score": round(float(confidence_score), 2),
                "normalized_score": int(normalized_score),
                "relevance_score": round(float(relevance_score), 2),
                "impact_level": impact_level,
                "event_type": event_type,
                "weighted_score": round(float(weighted_score), 4),
                "hours_old": round(float(hours_old), 2),
                "short_explanation_tag": _short_explanation(event_type, sentiment_label),
            }
        )

    scored_news.sort(key=lambda item: (item["hours_old"], -abs(item["weighted_score"])))

    in_24h = [item for item in scored_news if item["hours_old"] <= 24]
    in_7d = [item for item in scored_news if item["hours_old"] <= 24 * 7]
    active_window = in_7d or scored_news
    news_count = len(active_window)

    score_24h = round(sum(item["weighted_score"] for item in in_24h), 3) if in_24h else 0.0
    score_7d = round(sum(item["weighted_score"] for item in active_window), 3) if active_window else 0.0
    positive_count = sum(1 for item in active_window if item["sentiment_label"] == "positive")
    negative_count = sum(1 for item in active_window if item["sentiment_label"] == "negative")
    neutral_count = sum(1 for item in active_window if item["sentiment_label"] == "neutral")
    high_impact_count = sum(1 for item in active_window if item["impact_level"] == "high")
    dominant_event_type = Counter(item["event_type"] for item in active_window).most_common(1)
    dominant_event_type = dominant_event_type[0][0] if dominant_event_type else "other"

    if score_7d >= 1.0:
        signal_label = "Bullish"
    elif score_7d <= -1.0:
        signal_label = "Bearish"
    else:
        signal_label = "Neutral"

    trend_direction = "improving" if score_24h > score_7d else ("weakening" if score_24h < score_7d else "steady")
    confidence = round(min(0.98, 0.42 + min(news_count, 8) * 0.06 + min(abs(score_7d), 1.5) * 0.14), 2)

    drivers = []
    if positive_count:
        drivers.append(f"{positive_count} positive article{'s' if positive_count != 1 else ''} supported the outlook.")
    if high_impact_count:
        drivers.append(f"{high_impact_count} high-impact headline{'s' if high_impact_count != 1 else ''} shaped the signal.")
    if negative_count:
        drivers.append(f"{negative_count} negative article{'s' if negative_count != 1 else ''} kept risk in view.")
    if not drivers:
        drivers.append("News flow is limited, so the view is being driven more by market context than headline volume.")

    risk_flags = []
    for item in active_window:
        if item["event_type"] in RISK_EVENT_TYPES and item["sentiment_label"] != "positive":
            risk_flags.append(f"{item['event_type'].replace('_', ' ').title()} risk")
    if market_context.get("daily_change_pct") is not None and market_context["daily_change_pct"] <= -2.0:
        risk_flags.append("Sharp daily price pressure")
    if market_context.get("range_position_pct") is not None and market_context["range_position_pct"] <= 25:
        risk_flags.append("Trading near lower end of 52-week range")
    risk_flags = list(dict.fromkeys(risk_flags))[:4]

    summary_bits = [
        f"Recent news flow around {company_name} is {signal_label.lower()} overall.",
        f"The signal is being driven mainly by {dominant_event_type.replace('_', ' ')} headlines.",
        f"{news_count} relevant article{'s were' if news_count != 1 else ' was'} analyzed across the last 7 days.",
    ]
    if risk_flags:
        summary_bits.append(f"Main risk watch: {', '.join(risk_flags[:2]).lower()}.")

    return {
        "portfolio": {"id": portfolio.id, "name": portfolio.name},
        "stock": {
            "symbol": holding.stock.symbol,
            "name": company_name,
            "sector": holding.stock.sector.name if holding.stock.sector_id else market_context.get("sector"),
            "exchange": holding.stock.exchange,
            "quantity": str(holding.qty),
            "avg_buy_price": str(holding.avg_buy_price),
        },
        "overall_signal": {
            "label": signal_label,
            "sentiment_score": score_7d,
            "confidence": confidence,
            "window": "7d",
            "based_on": f"{news_count} relevant article{'s' if news_count != 1 else ''}",
        },
        "score_breakdown": {
            "score_24h": score_24h,
            "score_7d": score_7d,
            "trend_direction": trend_direction,
            "news_count": news_count,
            "positive_count": positive_count,
            "negative_count": negative_count,
            "neutral_count": neutral_count,
            "high_impact_news_count": high_impact_count,
            "dominant_event_type": dominant_event_type,
        },
        "why_it_changed": drivers[:3],
        "top_news": scored_news[:5],
        "risk_flags": risk_flags,
        "analyst_summary": " ".join(summary_bits),
        "verdict": {
            "label": signal_label,
            "reason": f"Verdict is based on 7-day sentiment score ({score_7d}) and dominant event type ({dominant_event_type.replace('_', ' ')}).",
        },
        "market_context": market_context,
        "meta": {
            "source": "yfinance_news_plus_heuristics",
            "databricks_ready": True,
            "gold_table_targets": [
                "gold_stock_insight_current",
                "gold_stock_news_view",
                "gold_portfolio_summary",
                "gold_stock_report_dataset",
            ],
        },
    }


def build_stock_sentiment_quick(symbol: str, company_name: str | None = None) -> dict:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise ValueError("symbol is required")
    company_name = (company_name or symbol).strip()
    market_context = _stock_market_context(symbol)

    try:
        raw_news = list(getattr(yf.Ticker(symbol), "news", None) or [])
    except Exception:
        raw_news = []
    if not raw_news:
        raw_news = _fallback_news(symbol, company_name, market_context)

    now = timezone.now().astimezone(dt_timezone.utc)
    scored_news = []
    seen = set()
    for item in raw_news[:15]:
        headline = _clean_text(item.get("title") or item.get("headline"), item.get("summary"))
        if not headline:
            continue
        dedupe_key = headline.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        summary = _clean_text(item.get("summary") or item.get("description"))
        text = _clean_text(headline, summary)
        event_type = _event_type(text)
        sentiment_label, confidence_score, normalized_score = _keyword_sentiment(text)

        fallback_score = item.get("_fallback_score")
        if fallback_score is not None and normalized_score == 0:
            normalized_score = 1 if fallback_score > 0.12 else (-1 if fallback_score < -0.12 else 0)
            sentiment_label = "positive" if normalized_score > 0 else ("negative" if normalized_score < 0 else "neutral")
            confidence_score = max(confidence_score, abs(float(fallback_score)))

        published_dt = _parse_published(item.get("providerPublishTime") or item.get("published_at"))
        hours_old = ((now - published_dt).total_seconds() / 3600.0) if published_dt else 72.0
        recency_weight = 1.0 if hours_old <= 24 else (0.72 if hours_old <= 72 else 0.5)
        relevance_score = _relevance_score(text, symbol, company_name)
        impact_level = _impact_level(text, float(normalized_score), event_type)
        impact_weight = {"low": 0.7, "medium": 1.0, "high": 1.35}[impact_level]
        weighted_score = normalized_score * confidence_score * recency_weight * relevance_score * impact_weight

        scored_news.append(
            {
                "ticker": symbol,
                "headline": headline,
                "source": item.get("publisher") or item.get("provider") or "Yahoo Finance",
                "url": item.get("link") or item.get("url") or "",
                "published_at": _to_iso(published_dt),
                "sentiment_label": sentiment_label,
                "confidence_score": round(float(confidence_score), 2),
                "normalized_score": int(normalized_score),
                "relevance_score": round(float(relevance_score), 2),
                "impact_level": impact_level,
                "event_type": event_type,
                "weighted_score": round(float(weighted_score), 4),
                "hours_old": round(float(hours_old), 2),
                "short_explanation_tag": _short_explanation(event_type, sentiment_label),
            }
        )

    scored_news.sort(key=lambda item: (item["hours_old"], -abs(item["weighted_score"])))

    in_24h = [item for item in scored_news if item["hours_old"] <= 24]
    in_7d = [item for item in scored_news if item["hours_old"] <= 24 * 7]
    active_window = in_7d or scored_news
    news_count = len(active_window)

    score_24h = round(sum(item["weighted_score"] for item in in_24h), 3) if in_24h else 0.0
    score_7d = round(sum(item["weighted_score"] for item in active_window), 3) if active_window else 0.0
    high_impact_count = sum(1 for item in active_window if item["impact_level"] == "high")
    dominant_event_type = Counter(item["event_type"] for item in active_window).most_common(1)
    dominant_event_type = dominant_event_type[0][0] if dominant_event_type else "other"

    if score_7d >= 1.0:
        signal_label = "Bullish"
    elif score_7d <= -1.0:
        signal_label = "Bearish"
    else:
        signal_label = "Neutral"

    confidence = round(min(0.98, 0.42 + min(news_count, 8) * 0.06 + min(abs(score_7d), 1.5) * 0.14), 2)
    risk_flags = []
    for item in active_window:
        if item["event_type"] in RISK_EVENT_TYPES and item["sentiment_label"] != "positive":
            risk_flags.append(f"{item['event_type'].replace('_', ' ').title()} risk")
    if market_context.get("daily_change_pct") is not None and market_context["daily_change_pct"] <= -2.0:
        risk_flags.append("Sharp daily price pressure")
    if market_context.get("range_position_pct") is not None and market_context["range_position_pct"] <= 25:
        risk_flags.append("Trading near lower end of 52-week range")
    risk_flags = list(dict.fromkeys(risk_flags))[:4]

    verdict_reason = (
        f"{signal_label} view from 7-day sentiment score {score_7d} with {news_count} relevant "
        f"headline{'s' if news_count != 1 else ''}; dominant theme is {dominant_event_type.replace('_', ' ')}."
    )

    return {
        "stock": {
            "symbol": symbol,
            "name": company_name,
        },
        "overall_signal": {
            "label": signal_label,
            "sentiment_score": score_7d,
            "confidence": confidence,
            "window": "7d",
            "based_on": f"{news_count} relevant article{'s' if news_count != 1 else ''}",
        },
        "score_breakdown": {
            "score_24h": score_24h,
            "score_7d": score_7d,
            "news_count": news_count,
            "high_impact_news_count": high_impact_count,
            "dominant_event_type": dominant_event_type,
        },
        "risk_flags": risk_flags,
        "verdict": {
            "label": signal_label,
            "reason": verdict_reason,
        },
        "market_context": {
            "last_price": market_context.get("last_price"),
            "daily_change_pct": market_context.get("daily_change_pct"),
            "pe": market_context.get("pe"),
            "market_cap": market_context.get("market_cap"),
            "range_position_pct": market_context.get("range_position_pct"),
        },
        "top_news": scored_news[:3],
        "meta": {"source": "yfinance_news_plus_heuristics_quick"},
    }


def build_portfolio_sentiment_summary(portfolio: Portfolio) -> dict:
    holdings = (
        Holding.objects.filter(portfolio=portfolio)
        .select_related("stock", "stock__sector")
        .order_by("stock__symbol")
    )

    stock_insights = []
    for holding in holdings:
        try:
            stock_insights.append(build_stock_sentiment_insight(portfolio, holding.stock.symbol))
        except Exception:
            continue

    if not stock_insights:
        return {
            "portfolio": {"id": portfolio.id, "name": portfolio.name},
            "portfolio_summary": {
                "portfolio_signal": "Neutral",
                "portfolio_sentiment_score": 0.0,
                "most_positive_stock": None,
                "most_risky_stock": None,
                "most_mentioned_stock": None,
                "sector_sentiment_mix": [],
            },
            "stocks": [],
            "meta": {"source": "yfinance_news_plus_heuristics", "databricks_ready": True},
        }

    score_map = [
        {
            "symbol": item["stock"]["symbol"],
            "name": item["stock"]["name"],
            "sector": item["stock"].get("sector") or "Unknown",
            "sentiment_score": item["overall_signal"]["sentiment_score"],
            "news_count": item["score_breakdown"]["news_count"],
            "risk_flags": item["risk_flags"],
            "signal": item["overall_signal"]["label"],
        }
        for item in stock_insights
    ]

    avg_score = round(sum(item["sentiment_score"] for item in score_map) / len(score_map), 3)
    portfolio_signal = "Bullish" if avg_score >= 0.75 else ("Bearish" if avg_score <= -0.75 else "Neutral")
    most_positive = max(score_map, key=lambda item: item["sentiment_score"], default=None)
    most_risky = max(score_map, key=lambda item: (len(item["risk_flags"]), -item["sentiment_score"]), default=None)
    most_mentioned = max(score_map, key=lambda item: item["news_count"], default=None)

    sector_buckets: dict[str, list[float]] = {}
    for item in score_map:
        sector_buckets.setdefault(item["sector"], []).append(item["sentiment_score"])
    sector_mix = [
        {"sector": sector, "avg_sentiment_score": round(sum(values) / len(values), 3), "stock_count": len(values)}
        for sector, values in sorted(sector_buckets.items())
    ]

    return {
        "portfolio": {"id": portfolio.id, "name": portfolio.name},
        "portfolio_summary": {
            "portfolio_signal": portfolio_signal,
            "portfolio_sentiment_score": avg_score,
            "most_positive_stock": most_positive,
            "most_risky_stock": most_risky,
            "most_mentioned_stock": most_mentioned,
            "sector_sentiment_mix": sector_mix,
        },
        "stocks": score_map,
        "meta": {"source": "yfinance_news_plus_heuristics", "databricks_ready": True},
    }


def build_stock_report_markdown(insight: dict) -> str:
    stock = insight["stock"]
    overall = insight["overall_signal"]
    breakdown = insight["score_breakdown"]
    market = insight["market_context"]
    news_rows = insight["top_news"]
    risks = insight["risk_flags"] or ["No major risk flags detected from current headline scan."]

    def _fmt_num(value, digits: int = 2) -> str:
        try:
            return f"{float(value):,.{digits}f}"
        except Exception:
            return "Not available"

    def _fmt_pct(value, digits: int = 2) -> str:
        try:
            return f"{float(value):.{digits}f}%"
        except Exception:
            return "Not available"

    lines = [
        f"# {stock['symbol']} Stock Insight Report",
        "",
        "## Executive Summary",
        "| Metric | Value |",
        "|---|---|",
        f"| Signal | {overall['label']} |",
        f"| Sentiment score (7d) | {_fmt_num(overall['sentiment_score'])} |",
        f"| Confidence | {_fmt_pct((overall.get('confidence') or 0) * 100)} |",
        f"| Coverage | {overall['based_on']} |",
        f"| Verdict | {(insight.get('verdict') or {}).get('label', overall['label'])} |",
        "",
        "## Verdict",
        (insight.get("verdict") or {}).get("reason") or "Verdict is derived from the latest sentiment and market context.",
        "",
        "## Sentiment Analysis",
        "| Indicator | Value |",
        "|---|---|",
        f"| 24h score | {_fmt_num(breakdown['score_24h'])} |",
        f"| 7d score | {_fmt_num(breakdown['score_7d'])} |",
        f"| Trend direction | {breakdown['trend_direction']} |",
        f"| Dominant event type | {str(breakdown['dominant_event_type']).replace('_', ' ')} |",
        "",
        "## Why This Changed",
    ]
    for item in insight["why_it_changed"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Key News Drivers"])
    if news_rows:
        lines.extend(
            [
                "| Headline | Sentiment | Impact | Source |",
                "|---|---|---|---|",
            ]
        )
    for item in news_rows:
        headline = str(item.get("headline") or "").replace("|", "\\|")
        lines.append(
            f"| {headline} | {item['sentiment_label']} | {item['impact_level']} | {item['source']} |"
        )
    lines.extend(["", "## Risk Assessment"])
    for item in risks:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Market Context",
            "| Metric | Value |",
            "|---|---|",
            f"| Last price | {_fmt_num(market.get('last_price'))} |",
            f"| Daily change % | {_fmt_pct(market.get('daily_change_pct'))} |",
            f"| P/E | {_fmt_num(market.get('pe'))} |",
            f"| Market cap | {_fmt_num(market.get('market_cap'), 0)} |",
            f"| 52W position | {_fmt_pct(market.get('range_position_pct'))} |",
            "",
            "## Analyst Summary",
            insight["analyst_summary"],
            "",
            "## Disclaimer",
            "Educational use only. This report is generated from current market context and headline heuristics.",
            "",
        ]
    )
    return "\n".join(lines)


def build_stock_report_csv_rows(insight: dict) -> list[dict]:
    rows = []
    for item in insight["top_news"]:
        rows.append(
            {
                "ticker": insight["stock"]["symbol"],
                "headline": item.get("headline"),
                "source": item.get("source"),
                "published_at": item.get("published_at"),
                "sentiment_label": item.get("sentiment_label"),
                "impact_level": item.get("impact_level"),
                "event_type": item.get("event_type"),
                "confidence_score": item.get("confidence_score"),
                "weighted_score": item.get("weighted_score"),
            }
        )
    return rows
