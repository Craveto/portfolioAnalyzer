from __future__ import annotations

import time
from dataclasses import dataclass

import yfinance as yf


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

    t = yf.Ticker(ticker)
    info = {}
    try:
        info = t.info or {}
    except Exception:
        info = {}

    fundamentals = {
        "ticker": ticker,
        "trailingPE": info.get("trailingPE"),
        "forwardPE": info.get("forwardPE"),
        "marketCap": info.get("marketCap"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "currency": info.get("currency"),
    }

    _set_cached(key, fundamentals, ttl_seconds=300)
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
