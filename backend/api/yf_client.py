from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass

import yfinance as yf
import requests


@dataclass(frozen=True)
class CacheEntry:
    expires_at: float
    value: object


_cache: dict[str, CacheEntry] = {}


def _get_cached(key: str):
    entry = _cache.get(key)
    if not entry:
        return None
    if time.time() >= entry.expires_at:
        _cache.pop(key, None)
        return None
    return entry.value


def _set_cached(key: str, value: object, ttl_seconds: int) -> None:
    _cache[key] = CacheEntry(expires_at=time.time() + ttl_seconds, value=value)

def _to_float(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except Exception:
        return None


def _normalize_pe(v):
    f = _to_float(v)
    if f is None:
        return None
    # yfinance/Yahoo sometimes returns 0 for missing; treat as unknown.
    if abs(f) < 1e-12:
        return None
    return f


def _extract_raw_number(v):
    """
    RapidAPI/Yahoo payloads often wrap numbers as {"raw": ..., "fmt": ...}.
    Accept plain numbers too.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return _to_float(v)
    if isinstance(v, dict):
        return _to_float(v.get("raw") if "raw" in v else v.get("value"))
    return _to_float(v)


def _fundamentals_rapidapi_yahoo(ticker: str) -> dict:
    """
    Fundamentals via RapidAPI Yahoo Finance (more reliable than scraping on some hosts).

    Requires env:
      - RAPIDAPI_KEY
      - (optional) RAPIDAPI_HOST (default apidojo-yahoo-finance-v1.p.rapidapi.com)
      - (optional) RAPIDAPI_REGION (default IN)
    """
    key = (os.getenv("RAPIDAPI_KEY") or "").strip()
    if not key:
        return {}

    host = (os.getenv("RAPIDAPI_HOST") or "apidojo-yahoo-finance-v1.p.rapidapi.com").strip()
    region = (os.getenv("RAPIDAPI_REGION") or "IN").strip()

    url = f"https://{host}/stock/v2/get-summary"
    headers = {"x-rapidapi-key": key, "x-rapidapi-host": host}
    params = {"symbol": ticker, "region": region}

    try:
        res = requests.get(url, headers=headers, params=params, timeout=15)
        if res.status_code != 200:
            return {}
        data = res.json() if res.content else {}
    except Exception:
        return {}

    # PE (best-effort across common modules)
    trailing_pe = _normalize_pe(
        _extract_raw_number(
            (data.get("summaryDetail") or {}).get("trailingPE")
            or (data.get("defaultKeyStatistics") or {}).get("trailingPE")
            or (data.get("price") or {}).get("trailingPE")
        )
    )
    forward_pe = _normalize_pe(
        _extract_raw_number(
            (data.get("summaryDetail") or {}).get("forwardPE")
            or (data.get("defaultKeyStatistics") or {}).get("forwardPE")
            or (data.get("price") or {}).get("forwardPE")
        )
    )

    market_cap = _extract_raw_number((data.get("summaryDetail") or {}).get("marketCap") or (data.get("price") or {}).get("marketCap"))

    asset_profile = data.get("assetProfile") or {}
    sector = asset_profile.get("sector")
    industry = asset_profile.get("industry")

    currency = None
    try:
        price = data.get("price") or {}
        currency = price.get("currency") or price.get("currencySymbol")
    except Exception:
        currency = None

    out = {
        "ticker": ticker,
        "trailingPE": trailing_pe,
        "forwardPE": forward_pe,
        "marketCap": market_cap,
        "sector": sector,
        "industry": industry,
        "currency": currency,
    }
    return out


def download_daily(tickers: list[str], days: int = 5):
    key = f"dl:daily:{','.join(tickers)}:{days}"
    cached = _get_cached(key)
    if cached is not None:
        return cached
    df = yf.download(tickers=tickers, period=f"{days}d", interval="1d", group_by="ticker", auto_adjust=False, progress=False, threads=True)
    _set_cached(key, df, ttl_seconds=30)
    return df


def get_fast_quote(ticker: str) -> dict:
    key = f"quote:{ticker}"
    cached = _get_cached(key)
    if cached is not None:
        return cached
    t = yf.Ticker(ticker)
    info = getattr(t, "fast_info", None) or {}
    quote = {
        "ticker": ticker,
        "last_price": info.get("last_price"),
        "previous_close": info.get("previous_close"),
        "currency": info.get("currency"),
        "time_zone": info.get("time_zone"),
    }

    if quote["last_price"] is None:
        try:
            hist = t.history(period="5d", interval="1d")
            closes = hist.get("Close") if hist is not None else None
            if closes is not None and len(closes.dropna()) >= 1:
                quote["last_price"] = float(closes.dropna().iloc[-1])
            if quote["previous_close"] is None and closes is not None and len(closes.dropna()) >= 2:
                quote["previous_close"] = float(closes.dropna().iloc[-2])
        except Exception:
            pass

    _set_cached(key, quote, ttl_seconds=30)
    return quote


def history_daily(ticker: str, period: str = "2y"):
    """
    Daily OHLCV history (best-effort). Cached because it's heavier than quotes.
    """
    key = f"hist:1d:{ticker}:{period}"
    cached = _get_cached(key)
    if cached is not None:
        return cached
    t = yf.Ticker(ticker)
    df = t.history(period=period, interval="1d")
    _set_cached(key, df, ttl_seconds=300)
    return df


def search_indian_equities(query: str, max_results: int = 25) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []

    key = f"search:in:{query}:{max_results}"
    cached = _get_cached(key)
    if cached is not None:
        return cached

    s = yf.Search(query, max_results=max_results)
    out: list[dict] = []
    for q in getattr(s, "quotes", []) or []:
        symbol = q.get("symbol")
        if not symbol:
            continue
        if not (symbol.endswith(".NS") or symbol.endswith(".BO")):
            continue
        if q.get("quoteType") not in (None, "EQUITY"):
            continue
        name = q.get("longname") or q.get("shortname") or symbol
        exch = q.get("exchDisp") or q.get("exchange")
        out.append({"symbol": symbol, "name": name, "exchange": exch})

    # de-dupe by symbol (keep first)
    seen: set[str] = set()
    deduped: list[dict] = []
    for item in out:
        sym = item["symbol"]
        if sym in seen:
            continue
        seen.add(sym)
        deduped.append(item)

    _set_cached(key, deduped, ttl_seconds=30)
    return deduped


def get_fundamentals(ticker: str) -> dict:
    """
    Best-effort fundamentals fetch via yfinance.
    Keep this cached longer than quotes because fundamentals change slower.
    """
    key = f"fund:{ticker}"
    cached = _get_cached(key)
    if cached is not None:
        return cached

    provider = (os.getenv("FUNDAMENTALS_PROVIDER") or "yfinance").strip().lower()
    if provider in ("rapidapi", "rapidapi_yahoo", "rapidapi_yahoo_finance"):
        rapid = _fundamentals_rapidapi_yahoo(ticker)
        if rapid and (rapid.get("trailingPE") is not None or rapid.get("forwardPE") is not None):
            # Cache longer to reduce paid API calls.
            _set_cached(key, rapid, ttl_seconds=3600)
            return rapid

    t = yf.Ticker(ticker)
    info: dict = {}
    try:
        # Newer yfinance prefers get_info(); keep backwards compatible.
        get_info = getattr(t, "get_info", None)
        if callable(get_info):
            info = get_info() or {}
        else:
            info = t.info or {}
    except Exception:
        info = {}

    # Try a second time via the other method if we got nothing (transient failures happen).
    if not info:
        try:
            get_info = getattr(t, "get_info", None)
            if not callable(get_info):
                info = getattr(t, "info", None) or {}
            else:
                info = t.info or {}
        except Exception:
            info = {}

    trailing_pe = _normalize_pe(
        info.get("trailingPE")
        or info.get("trailingPe")
        or info.get("priceToEarnings")
        or info.get("peRatio")
    )
    forward_pe = _normalize_pe(info.get("forwardPE") or info.get("forwardPe"))

    # Fallback: compute from price / EPS if possible.
    if trailing_pe is None and forward_pe is None:
        price = _to_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        if price is None:
            try:
                price = _to_float(get_fast_quote(ticker).get("last_price"))
            except Exception:
                price = None
        eps = _to_float(info.get("trailingEps") or info.get("epsTrailingTwelveMonths") or info.get("epsTTM"))
        if price is not None and eps is not None and eps != 0:
            trailing_pe = _normalize_pe(price / eps)

    fundamentals = {
        "ticker": ticker,
        "trailingPE": trailing_pe,
        "forwardPE": forward_pe,
        "marketCap": info.get("marketCap"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "currency": info.get("currency"),
    }

    # Cache shorter when info is missing to avoid "sticky" zeros/nulls during transient Yahoo issues.
    ttl = 300 if (info and (trailing_pe is not None or forward_pe is not None)) else 60
    _set_cached(key, fundamentals, ttl_seconds=ttl)
    return fundamentals


def get_52w_range(ticker: str) -> dict:
    """
    Best-effort 52-week (1y) low/high from daily history.
    Cached to avoid repeated heavy calls.
    """
    key = f"range52w:{ticker}"
    cached = _get_cached(key)
    if cached is not None:
        return cached

    t = yf.Ticker(ticker)
    low = None
    high = None
    try:
        hist = t.history(period="1y", interval="1d")
        if hist is not None and not hist.empty:
            lows = hist.get("Low")
            highs = hist.get("High")
            if lows is not None and len(lows.dropna()) >= 1:
                low = float(lows.dropna().min())
            if highs is not None and len(highs.dropna()) >= 1:
                high = float(highs.dropna().max())
    except Exception:
        low = None
        high = None

    out = {"ticker": ticker, "low_52w": low, "high_52w": high}
    _set_cached(key, out, ttl_seconds=600)
    return out
