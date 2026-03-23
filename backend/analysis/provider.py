from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal

from django.utils import timezone

from api.models import CachedPayload
from portfolio.models import Portfolio

from .databricks_client import DatabricksConfigError, DatabricksQueryError
from .databricks_provider import (
    get_portfolio_sentiment_from_databricks,
    get_stock_quick_sentiment_from_databricks,
    get_stock_insight_from_databricks,
)
from .insights import (
    build_stock_sentiment_quick,
    build_portfolio_sentiment_summary,
    build_stock_report_csv_rows,
    build_stock_report_markdown,
    build_stock_sentiment_insight,
)


class DatabricksProviderNotReadyError(NotImplementedError):
    pass


class DatabricksProviderRuntimeError(RuntimeError):
    pass


def _has_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"", "--", "not available", "n/a", "na", "null", "none"}:
            return False
    return True


def _market_context_complete(payload: dict) -> bool:
    market_context = (payload or {}).get("market_context") or {}
    if not isinstance(market_context, dict):
        return False
    return (
        _has_value(market_context.get("pe"))
        and _has_value(market_context.get("market_cap"))
        and _has_value(market_context.get("range_position_pct"))
    )


def _cache_key(kind: str, portfolio: Portfolio, symbol: str | None = None) -> str:
    parts = ["analysis", kind, str(portfolio.id)]
    if symbol:
        parts.append(symbol.upper())
    return ":".join(parts)


def _read_cached_payload(cache_key: str, fresh_seconds: int, allow_stale: bool = True) -> dict | None:
    snapshot = CachedPayload.objects.filter(key=cache_key).first()
    if not snapshot:
        return None
    payload = dict(snapshot.payload or {})
    age_seconds = (timezone.now() - snapshot.updated_at).total_seconds()
    stale = age_seconds > fresh_seconds
    if stale and not allow_stale:
        return None
    meta = dict(payload.get("meta") or {})
    meta.update(
        {
            "cache_key": cache_key,
            "cache_source": "snapshot",
            "cache_updated_at": snapshot.updated_at.isoformat(),
            "cache_age_seconds": round(age_seconds, 1),
            "cache_stale": stale,
        }
    )
    payload["meta"] = meta
    return payload


def _write_cached_payload(cache_key: str, payload: dict) -> dict:
    def _json_safe(value):
        if isinstance(value, dict):
            return {k: _json_safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_json_safe(item) for item in value]
        if isinstance(value, tuple):
            return [_json_safe(item) for item in value]
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        return value

    safe_payload = _json_safe(payload)
    snapshot, _ = CachedPayload.objects.update_or_create(key=cache_key, defaults={"payload": safe_payload})
    out = dict(safe_payload)
    meta = dict(out.get("meta") or {})
    meta.update(
        {
            "cache_key": cache_key,
            "cache_source": "fresh",
            "cache_updated_at": snapshot.updated_at.isoformat(),
            "cache_age_seconds": 0,
            "cache_stale": False,
        }
    )
    out["meta"] = meta
    return out


def get_stock_insight_provider() -> str:
    return (os.getenv("STOCK_INSIGHT_PROVIDER") or "demo").strip().lower()


def _portfolio_cache_ttl_seconds(default_seconds: int = 300) -> int:
    raw = (os.getenv("PORTFOLIO_SENTIMENT_CACHE_SECONDS") or str(default_seconds)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return default_seconds


def _stock_cache_ttl_seconds(default_seconds: int = 180) -> int:
    raw = (os.getenv("STOCK_INSIGHT_CACHE_SECONDS") or str(default_seconds)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return default_seconds


def get_portfolio_sentiment(portfolio: Portfolio, force_refresh: bool = False, fresh_seconds: int = 300) -> dict:
    fresh_seconds = _portfolio_cache_ttl_seconds(fresh_seconds)
    provider = get_stock_insight_provider()
    if provider == "databricks":
        cache_key = _cache_key("portfolio_sentiment", portfolio)
        if not force_refresh:
            cached = _read_cached_payload(cache_key, fresh_seconds=fresh_seconds, allow_stale=True)
            if cached:
                return cached
        try:
            payload = get_portfolio_sentiment_from_databricks(portfolio)
        except (DatabricksConfigError, DatabricksQueryError) as exc:
            cached = _read_cached_payload(cache_key, fresh_seconds=fresh_seconds, allow_stale=True)
            if cached:
                meta = dict(cached.get("meta") or {})
                meta["fallback_reason"] = str(exc)
                cached["meta"] = meta
                return cached
            raise DatabricksProviderRuntimeError(str(exc)) from exc
        return _write_cached_payload(cache_key, payload)
    return build_portfolio_sentiment_summary(portfolio)


def get_stock_insight(portfolio: Portfolio, symbol: str, force_refresh: bool = False, fresh_seconds: int = 180) -> dict:
    fresh_seconds = _stock_cache_ttl_seconds(fresh_seconds)
    provider = get_stock_insight_provider()
    if provider == "databricks":
        cache_key = _cache_key("stock_insight", portfolio, symbol)
        if not force_refresh:
            cached = _read_cached_payload(cache_key, fresh_seconds=fresh_seconds, allow_stale=True)
            if cached:
                if _market_context_complete(cached):
                    return cached
        try:
            payload = get_stock_insight_from_databricks(portfolio, symbol)
        except (DatabricksConfigError, DatabricksQueryError) as exc:
            cached = _read_cached_payload(cache_key, fresh_seconds=fresh_seconds, allow_stale=True)
            if cached:
                meta = dict(cached.get("meta") or {})
                meta["fallback_reason"] = str(exc)
                if not _market_context_complete(cached):
                    meta["market_context_note"] = "Some market fields are temporarily unavailable from both Databricks and fallback providers."
                cached["meta"] = meta
                return cached
            raise DatabricksProviderRuntimeError(str(exc)) from exc
        return _write_cached_payload(cache_key, payload)
    return build_stock_sentiment_insight(portfolio, symbol)


def get_stock_report_markdown(portfolio: Portfolio, symbol: str) -> str:
    insight = get_stock_insight(portfolio, symbol)
    return build_stock_report_markdown(insight)


def get_stock_report_csv_rows(portfolio: Portfolio, symbol: str) -> list[dict]:
    insight = get_stock_insight(portfolio, symbol)
    return build_stock_report_csv_rows(insight)


def get_quick_stock_sentiment(symbol: str, company_name: str | None = None, force_refresh: bool = False, fresh_seconds: int = 120) -> dict:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise ValueError("symbol is required")

    provider = get_stock_insight_provider()
    if provider == "databricks":
        cache_key = f"analysis:quick_stock_sentiment:{symbol}"
        if not force_refresh:
            cached = _read_cached_payload(cache_key, fresh_seconds=fresh_seconds, allow_stale=True)
            if cached:
                return cached
        try:
            payload = get_stock_quick_sentiment_from_databricks(symbol=symbol, company_name=company_name)
        except (DatabricksConfigError, DatabricksQueryError) as exc:
            cached = _read_cached_payload(cache_key, fresh_seconds=fresh_seconds, allow_stale=True)
            if cached:
                meta = dict(cached.get("meta") or {})
                meta["fallback_reason"] = str(exc)
                cached["meta"] = meta
                return cached
            raise DatabricksProviderRuntimeError(str(exc)) from exc
        return _write_cached_payload(cache_key, payload)

    return build_stock_sentiment_quick(symbol=symbol, company_name=company_name)
