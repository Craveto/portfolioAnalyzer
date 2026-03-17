from __future__ import annotations

import math
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import yfinance as yf
import requests
from django.utils import timezone

from .models import CachedPayload


def _configure_yfinance_cache() -> None:
    try:
        cache_dir = Path(os.getenv("YFINANCE_CACHE_DIR") or (Path(__file__).resolve().parents[1] / ".cache" / "yfinance"))
        cache_dir.mkdir(parents=True, exist_ok=True)
        set_cache_dir = getattr(yf, "set_tz_cache_location", None)
        if callable(set_cache_dir):
            set_cache_dir(str(cache_dir))
    except Exception:
        pass


_configure_yfinance_cache()


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


def _fundamentals_snapshot_key(ticker: str) -> str:
    return f"fund_snapshot:{(ticker or '').strip().upper()}"


def _load_persistent_fundamentals(ticker: str, max_age_seconds: int | None = None) -> dict | None:
    try:
        snap = CachedPayload.objects.filter(key=_fundamentals_snapshot_key(ticker)).first()
        if not snap:
            return None
        if max_age_seconds is not None:
            age = (timezone.now() - snap.updated_at).total_seconds()
            if age > max_age_seconds:
                return None
        payload = snap.payload or {}
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _save_persistent_fundamentals(ticker: str, payload: dict) -> None:
    if not isinstance(payload, dict):
        return
    try:
        CachedPayload.objects.update_or_create(
            key=_fundamentals_snapshot_key(ticker),
            defaults={"payload": payload},
        )
    except Exception:
        pass

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


def _has_rapidapi_key() -> bool:
    return bool((os.getenv("RAPIDAPI_KEY") or "").strip())


def _merge_fundamentals(base: dict | None = None, extra: dict | None = None) -> dict:
    out = dict(base or {})
    for key, value in (extra or {}).items():
        if value is not None and value != "":
            out[key] = value
    return out


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
    summary_path = (os.getenv("RAPIDAPI_SUMMARY_PATH") or "/stock/v2/get-summary").strip() or "/stock/v2/get-summary"
    if not summary_path.startswith("/"):
        summary_path = f"/{summary_path}"

    url = f"https://{host}{summary_path}"
    headers = {"x-rapidapi-key": key, "x-rapidapi-host": host}
    params = {
        "symbol": ticker,
        "region": region,
        "lang": (os.getenv("RAPIDAPI_LANG") or "en-US").strip() or "en-US",
    }

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


def _fundamentals_yahoo_http(ticker: str) -> dict:
    url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
    params = {"modules": "summaryDetail,defaultKeyStatistics,financialData,price,assetProfile"}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, params=params, headers=headers, timeout=15)
        if res.status_code != 200:
            return {}
        data = res.json() if res.content else {}
        result = (((data or {}).get("quoteSummary") or {}).get("result") or [None])[0] or {}
    except Exception:
        return {}

    summary = result.get("summaryDetail") or {}
    stats = result.get("defaultKeyStatistics") or {}
    financial = result.get("financialData") or {}
    price = result.get("price") or {}
    profile = result.get("assetProfile") or {}

    trailing_pe = _normalize_pe(
        _extract_raw_number(
            summary.get("trailingPE")
            or stats.get("trailingPE")
            or financial.get("trailingPE")
            or price.get("trailingPE")
        )
    )
    forward_pe = _normalize_pe(
        _extract_raw_number(
            summary.get("forwardPE")
            or stats.get("forwardPE")
            or financial.get("forwardPE")
            or price.get("forwardPE")
        )
    )

    market_cap = _extract_raw_number(summary.get("marketCap") or stats.get("marketCap") or price.get("marketCap"))
    currency = price.get("currency")
    if isinstance(currency, dict):
        currency = currency.get("fmt") or currency.get("raw")

    return {
        "ticker": ticker,
        "trailingPE": trailing_pe,
        "forwardPE": forward_pe,
        "marketCap": market_cap,
        "sector": profile.get("sector"),
        "industry": profile.get("industry"),
        "currency": currency,
    }


def _quote_yahoo_http(ticker: str) -> dict:
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, params={"symbols": ticker}, headers=headers, timeout=15)
        if res.status_code != 200:
            return {}
        data = res.json() if res.content else {}
        result = (((data or {}).get("quoteResponse") or {}).get("result") or [None])[0] or {}
    except Exception:
        return {}

    trailing_pe = _normalize_pe(result.get("trailingPE"))
    forward_pe = _normalize_pe(result.get("forwardPE"))
    price = _to_float(result.get("regularMarketPrice"))
    trailing_eps = _to_float(result.get("epsTrailingTwelveMonths"))
    forward_eps = _to_float(result.get("epsForward"))

    if trailing_pe is None and price is not None and trailing_eps not in (None, 0):
        trailing_pe = _normalize_pe(price / trailing_eps)
    if forward_pe is None and price is not None and forward_eps not in (None, 0):
        forward_pe = _normalize_pe(price / forward_eps)

    return {
        "ticker": ticker,
        "trailingPE": trailing_pe,
        "forwardPE": forward_pe,
        "marketCap": _to_float(result.get("marketCap")),
        "currency": result.get("currency"),
        "regularMarketPrice": price,
        "trailingEps": trailing_eps,
        "forwardEps": forward_eps,
    }


def _alternate_indian_listing(ticker: str) -> str | None:
    ticker = (ticker or "").strip().upper()
    if ticker.endswith(".BO"):
        return f"{ticker[:-3]}.NS"
    if ticker.endswith(".NS"):
        return f"{ticker[:-3]}.BO"
    return None


def _fundamentals_screener_in(ticker: str) -> dict:
    base = (ticker or "").strip().upper().split(".")[0]
    if not base:
        return {}

    headers = {"User-Agent": "Mozilla/5.0"}
    urls = [
        f"https://www.screener.in/company/{base}/consolidated/",
        f"https://www.screener.in/company/{base}/",
    ]
    patterns = [
        r"Stock P/E\s*</[^>]+>\s*<[^>]+>\s*([0-9]+(?:\.[0-9]+)?)",
        r"Stock P/E[^0-9]{0,120}([0-9]+(?:\.[0-9]+)?)",
        r"P/E[^0-9]{0,80}([0-9]+(?:\.[0-9]+)?)",
    ]

    for url in urls:
        try:
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code != 200 or not res.text:
                continue
            html = res.text
        except Exception:
            continue

        for pattern in patterns:
            m = re.search(pattern, html, flags=re.IGNORECASE)
            if not m:
                continue
            pe = _normalize_pe(m.group(1))
            if pe is not None:
                return {
                    "ticker": ticker,
                    "trailingPE": pe,
                    "forwardPE": None,
                    "source": "screener.in",
                }
    return {}


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

    persistent = _load_persistent_fundamentals(ticker, max_age_seconds=7 * 24 * 3600)

    provider = (os.getenv("FUNDAMENTALS_PROVIDER") or "auto").strip().lower()
    prefer_rapid = provider in ("rapidapi", "rapidapi_yahoo", "rapidapi_yahoo_finance") or (provider == "auto" and _has_rapidapi_key())
    prefer_yfinance_only = provider in ("yfinance", "yf")

    if prefer_rapid:
        rapid = _fundamentals_rapidapi_yahoo(ticker)
        if rapid and (rapid.get("trailingPE") is not None or rapid.get("forwardPE") is not None):
            _set_cached(key, rapid, ttl_seconds=3600)
            return rapid

    t = yf.Ticker(ticker)
    info: dict = {}
    if not prefer_rapid or prefer_yfinance_only:
        try:
            # Newer yfinance prefers get_info(); keep backwards compatible.
            get_info = getattr(t, "get_info", None)
            if callable(get_info):
                info = get_info() or {}
            else:
                info = t.info or {}
        except Exception:
            info = {}

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

    # Hosting fallback: direct Yahoo JSON endpoint is often more reliable than yfinance's info scraping.
    if trailing_pe is None and forward_pe is None:
        http_data = _fundamentals_yahoo_http(ticker)
        if http_data:
            trailing_pe = http_data.get("trailingPE")
            forward_pe = http_data.get("forwardPE")
            info = _merge_fundamentals(info, http_data)

    if trailing_pe is None and forward_pe is None:
        quote_http = _quote_yahoo_http(ticker)
        if quote_http:
            trailing_pe = quote_http.get("trailingPE")
            forward_pe = quote_http.get("forwardPE")
            info = _merge_fundamentals(info, quote_http)

    if trailing_pe is None and forward_pe is None:
        alternate = _alternate_indian_listing(ticker)
        if alternate:
            alt_http = _fundamentals_yahoo_http(alternate)
            if alt_http:
                trailing_pe = alt_http.get("trailingPE")
                forward_pe = alt_http.get("forwardPE")
                info = _merge_fundamentals(info, alt_http)
            if trailing_pe is None and forward_pe is None:
                alt_quote = _quote_yahoo_http(alternate)
                if alt_quote:
                    trailing_pe = alt_quote.get("trailingPE")
                    forward_pe = alt_quote.get("forwardPE")
                    info = _merge_fundamentals(info, alt_quote)

    if trailing_pe is None and forward_pe is None:
        screener_data = _fundamentals_screener_in(ticker)
        if screener_data:
            trailing_pe = screener_data.get("trailingPE")
            forward_pe = screener_data.get("forwardPE")
            info = _merge_fundamentals(info, screener_data)

    # Final fallback when auto mode is used and RapidAPI is configured:
    # if yfinance/HTTP gave no PE, try RapidAPI once more for hosted environments.
    if trailing_pe is None and forward_pe is None and not prefer_rapid and _has_rapidapi_key():
        rapid = _fundamentals_rapidapi_yahoo(ticker)
        if rapid:
            trailing_pe = rapid.get("trailingPE")
            forward_pe = rapid.get("forwardPE")
            info = _merge_fundamentals(info, rapid)

    fundamentals = {
        "ticker": ticker,
        "trailingPE": trailing_pe,
        "forwardPE": forward_pe,
        "marketCap": info.get("marketCap"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "currency": info.get("currency"),
    }

    if (fundamentals.get("trailingPE") is None and fundamentals.get("forwardPE") is None) and persistent:
        fundamentals = _merge_fundamentals(persistent, fundamentals)

    # Cache shorter when info is missing to avoid "sticky" zeros/nulls during transient Yahoo issues.
    ttl = 300 if (info and (trailing_pe is not None or forward_pe is not None)) else 60
    _set_cached(key, fundamentals, ttl_seconds=ttl)
    if fundamentals.get("trailingPE") is not None or fundamentals.get("forwardPE") is not None:
        _save_persistent_fundamentals(ticker, fundamentals)
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


def history_last_days(ticker: str, days: int = 7) -> list[dict]:
    """
    Small daily close series for quick UI widgets.
    Returns list of {"date": "YYYY-MM-DD", "close": float}.
    """
    days = max(3, min(30, int(days or 7)))
    key = f"hist:last:{days}:{ticker}"
    cached = _get_cached(key)
    if cached is not None:
        return cached

    t = yf.Ticker(ticker)
    out: list[dict] = []
    try:
        # Fetch a bit more than needed to cover non-trading days.
        df = t.history(period=f"{max(days + 5, 10)}d", interval="1d")
        closes = df.get("Close") if df is not None else None
        if closes is not None:
            s = closes.dropna()
            if len(s) >= 1:
                tail = s.tail(days)
                for idx, val in tail.items():
                    try:
                        d = getattr(idx, "date", None)
                        if callable(d):
                            ds = idx.date().isoformat()
                        else:
                            ds = str(idx)[:10]
                        out.append({"date": ds, "close": float(val)})
                    except Exception:
                        continue
    except Exception:
        out = []

    _set_cached(key, out, ttl_seconds=60)
    return out


def metals_summary(days: int = 7) -> dict:
    """
    Gold/Silver widget payload (fast, cached):
    - Last + prev close for gold & silver
    - 7d aligned close series
    - Simple metrics: corr, ratio, 7d returns
    """
    days = max(3, min(14, int(days or 7)))
    key = f"metals:summary:{days}"
    cached = _get_cached(key)
    if cached is not None:
        return cached

    # Prefer spot FX tickers; fall back to futures if needed (spot can be empty on some hosts).
    gold_t = os.getenv("METALS_GOLD_TICKER", "XAUUSD=X").strip() or "XAUUSD=X"
    silver_t = os.getenv("METALS_SILVER_TICKER", "XAGUSD=X").strip() or "XAGUSD=X"
    gold_fallback = os.getenv("METALS_GOLD_FALLBACK", "GC=F").strip() or "GC=F"
    silver_fallback = os.getenv("METALS_SILVER_FALLBACK", "SI=F").strip() or "SI=F"

    fetch_days = max(days + 7, 14)

    def _download_pair(gt: str, st: str):
        try:
            return yf.download(
                tickers=[gt, st],
                period=f"{fetch_days}d",
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=True,
            )
        except Exception:
            return None

    df = _download_pair(gold_t, silver_t)

    def _close_series(sym: str):
        try:
            if df is None or getattr(df, "empty", False):
                return []
            if hasattr(df, "columns") and hasattr(df.columns, "get_level_values"):
                # MultiIndex columns: (ticker, field)
                if sym in df.columns.get_level_values(0):
                    s = df[sym].get("Close")
                else:
                    s = None
            else:
                s = None
            if s is None:
                return []
            s = s.dropna()
            out = []
            for idx, val in s.tail(days).items():
                try:
                    ds = idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]
                    out.append({"date": ds, "close": float(val)})
                except Exception:
                    continue
            return out
        except Exception:
            return []

    gold_series = _close_series(gold_t)
    silver_series = _close_series(silver_t)

    # Fallback if spot tickers return empty series.
    used = {"gold": gold_t, "silver": silver_t}
    if (not gold_series or not silver_series) and (gold_fallback or silver_fallback):
        df = _download_pair(gold_fallback, silver_fallback)
        gold_series_fb = _close_series(gold_fallback)
        silver_series_fb = _close_series(silver_fallback)
        if gold_series_fb and silver_series_fb:
            gold_series = gold_series_fb
            silver_series = silver_series_fb
            used = {"gold": gold_fallback, "silver": silver_fallback}

    # Align by date
    gmap = {p["date"]: p.get("close") for p in gold_series}
    smap = {p["date"]: p.get("close") for p in silver_series}
    dates = sorted(set(gmap.keys()) & set(smap.keys()))
    series = []
    gvals = []
    svals = []
    for d in dates:
        gv = gmap.get(d)
        sv = smap.get(d)
        if gv is None or sv is None:
            continue
        series.append({"date": d, "gold": float(gv), "silver": float(sv)})
        gvals.append(float(gv))
        svals.append(float(sv))

    def pct_change(vals: list[float]):
        if len(vals) < 2:
            return None
        a = vals[0]
        b = vals[-1]
        if not a:
            return None
        return ((b - a) / a) * 100.0

    def quote_from_vals(sym: str, vals: list[float]):
        last = vals[-1] if len(vals) >= 1 else None
        prev = vals[-2] if len(vals) >= 2 else None
        return {"ticker": sym, "last_price": last, "previous_close": prev, "currency": None, "time_zone": None}

    gold_q = quote_from_vals(gold_t, gvals)
    silver_q = quote_from_vals(silver_t, svals)

    corr = None
    try:
        if len(gvals) >= 3 and len(svals) == len(gvals):
            gm = sum(gvals) / len(gvals)
            sm = sum(svals) / len(svals)
            num = sum((g - gm) * (s - sm) for g, s in zip(gvals, svals))
            den1 = sum((g - gm) ** 2 for g in gvals) ** 0.5
            den2 = sum((s - sm) ** 2 for s in svals) ** 0.5
            if den1 and den2:
                corr = num / (den1 * den2)
    except Exception:
        corr = None

    ratio = None
    try:
        gl = gold_q.get("last_price")
        sl = silver_q.get("last_price")
        if gl is not None and sl:
            ratio = float(gl) / float(sl)
    except Exception:
        ratio = None

    payload = {
        "tickers": used,
        "requested_tickers": {"gold": gold_t, "silver": silver_t},
        "gold": gold_q,
        "silver": silver_q,
        "series": series,
        "metrics": {
            "corr_7d": corr,
            "gold_silver_ratio": ratio,
            "gold_7d_return_pct": pct_change(gvals) if gvals else None,
            "silver_7d_return_pct": pct_change(svals) if svals else None,
        },
        "available": bool(series) and (gold_q.get("last_price") is not None or silver_q.get("last_price") is not None),
        "note": "Metals are best-effort quotes (cached). Educational only.",
    }

    _set_cached(key, payload, ttl_seconds=60)
    return payload


def metals_quote_fast(ttl_seconds: int = 20) -> dict:
    """
    Very small payload for polling (fast UI updates).
    Returns last + previous close for gold/silver only.
    Cached aggressively to avoid hammering yfinance.
    """
    ttl_seconds = max(10, min(60, int(ttl_seconds or 20)))
    key = f"metals:quote:{ttl_seconds}"
    cached = _get_cached(key)
    if cached is not None:
        return cached

    gold_t = os.getenv("METALS_GOLD_TICKER", "XAUUSD=X").strip() or "XAUUSD=X"
    silver_t = os.getenv("METALS_SILVER_TICKER", "XAGUSD=X").strip() or "XAGUSD=X"
    gold_fallback = os.getenv("METALS_GOLD_FALLBACK", "GC=F").strip() or "GC=F"
    silver_fallback = os.getenv("METALS_SILVER_FALLBACK", "SI=F").strip() or "SI=F"

    def _download_pair(gt: str, st: str):
        try:
            return yf.download(
                tickers=[gt, st],
                period="10d",
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=True,
            )
        except Exception:
            return None

    df = _download_pair(gold_t, silver_t)

    def last_prev(sym: str):
        try:
            if df is None or getattr(df, "empty", False):
                return {"ticker": sym, "last_price": None, "previous_close": None}
            if sym not in df.columns.get_level_values(0):
                return {"ticker": sym, "last_price": None, "previous_close": None}
            s = df[sym].get("Close")
            if s is None:
                return {"ticker": sym, "last_price": None, "previous_close": None}
            s = s.dropna()
            last = float(s.iloc[-1]) if len(s) >= 1 else None
            prev = float(s.iloc[-2]) if len(s) >= 2 else None
            return {"ticker": sym, "last_price": last, "previous_close": prev}
        except Exception:
            return {"ticker": sym, "last_price": None, "previous_close": None}

    out = {"gold": last_prev(gold_t), "silver": last_prev(silver_t), "cached_for_s": ttl_seconds, "tickers": {"gold": gold_t, "silver": silver_t}}
    if (out["gold"]["last_price"] is None or out["silver"]["last_price"] is None) and (gold_fallback or silver_fallback):
        df = _download_pair(gold_fallback, silver_fallback)
        out = {
            "gold": last_prev(gold_fallback),
            "silver": last_prev(silver_fallback),
            "cached_for_s": ttl_seconds,
            "tickers": {"gold": gold_fallback, "silver": silver_fallback},
            "requested_tickers": {"gold": gold_t, "silver": silver_t},
        }
    _set_cached(key, out, ttl_seconds=ttl_seconds)
    return out


def metals_news(limit: int = 6) -> list[dict]:
    """
    Best-effort metals news via yfinance Ticker.news.
    Cached longer to keep landing fast.
    """
    limit = max(3, min(12, int(limit or 6)))
    key = f"metals:news:{limit}"
    cached = _get_cached(key)
    if cached is not None:
        return cached

    gold_t = os.getenv("METALS_GOLD_TICKER", "XAUUSD=X").strip() or "XAUUSD=X"
    silver_t = os.getenv("METALS_SILVER_TICKER", "XAGUSD=X").strip() or "XAGUSD=X"

    items: list[dict] = []
    for sym in (gold_t, silver_t):
        try:
            t = yf.Ticker(sym)
            news = getattr(t, "news", None) or []
            for n in news:
                title = n.get("title") or ""
                link = n.get("link") or n.get("url") or ""
                if not title or not link:
                    continue
                items.append(
                    {
                        "title": title,
                        "publisher": n.get("publisher") or "",
                        "link": link,
                        "published_at": n.get("providerPublishTime"),
                        "source": sym,
                    }
                )
        except Exception:
            continue

    # De-dupe by title and sort by publish time (desc)
    seen = set()
    deduped = []
    for it in sorted(items, key=lambda x: x.get("published_at") or 0, reverse=True):
        t = it.get("title") or ""
        if t in seen:
            continue
        seen.add(t)
        deduped.append(it)
        if len(deduped) >= limit:
            break

    _set_cached(key, deduped, ttl_seconds=600)
    return deduped


def metals_forecast(horizon: str = "1w") -> dict:
    """
    Educational metals forecast (fast + cached).

    Horizons:
      - 1h: next 60 minutes (5m steps)
      - 1w: next 7 days (daily steps)
      - 1m: next 30 days (daily steps)
      - 1y: next 12 months (monthly steps)

    Method:
      - Estimate mean log-return (mu) and volatility (sigma) from recent history
      - Expected path: P(t) = P0 * exp(mu * t)
      - Band: ± 1σ * sqrt(t)

    Not investment advice.
    """
    h = (horizon or "1w").strip().lower()
    if h not in ("1h", "1w", "1m", "1y"):
        h = "1w"

    ttl = {"1h": 30, "1w": 120, "1m": 600, "1y": 1800}.get(h, 120)
    key = f"metals:forecast:{h}"
    cached = _get_cached(key)
    if cached is not None:
        return cached

    gold_req = os.getenv("METALS_GOLD_TICKER", "XAUUSD=X").strip() or "XAUUSD=X"
    silver_req = os.getenv("METALS_SILVER_TICKER", "XAGUSD=X").strip() or "XAGUSD=X"
    gold_fb = os.getenv("METALS_GOLD_FALLBACK", "GC=F").strip() or "GC=F"
    silver_fb = os.getenv("METALS_SILVER_FALLBACK", "SI=F").strip() or "SI=F"

    if h == "1h":
        interval = "5m"
        period = "5d"
        steps = 12
        step_seconds = 5 * 60
    elif h == "1w":
        interval = "1d"
        period = "3mo"
        steps = 7
        step_seconds = 24 * 3600
    elif h == "1m":
        interval = "1d"
        period = "6mo"
        steps = 30
        step_seconds = 24 * 3600
    else:
        interval = "1wk"
        period = "5y"
        steps = 12
        step_seconds = 30 * 24 * 3600

    def _download_pair(gt: str, st: str):
        try:
            return yf.download(
                tickers=[gt, st],
                period=period,
                interval=interval,
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=True,
            )
        except Exception:
            return None

    df = _download_pair(gold_req, silver_req)

    def _close_list(sym: str):
        try:
            if df is None or getattr(df, "empty", False):
                return []
            if sym not in df.columns.get_level_values(0):
                return []
            s = df[sym].get("Close")
            if s is None:
                return []
            s = s.dropna()
            return [float(x) for x in s.values if x is not None]
        except Exception:
            return []

    gold_vals = _close_list(gold_req)
    silver_vals = _close_list(silver_req)
    used = {"gold": gold_req, "silver": silver_req}
    if (len(gold_vals) < 10 or len(silver_vals) < 10) and (gold_fb or silver_fb):
        df = _download_pair(gold_fb, silver_fb)
        gold_vals = _close_list(gold_fb)
        silver_vals = _close_list(silver_fb)
        if len(gold_vals) >= 10 and len(silver_vals) >= 10:
            used = {"gold": gold_fb, "silver": silver_fb}

    def _mu_sigma(vals: list[float]):
        if len(vals) < 8:
            return None, None, None
        rets = []
        for a, b in zip(vals[:-1], vals[1:]):
            if a and b and a > 0 and b > 0:
                rets.append(math.log(b / a))
        if len(rets) < 5:
            return vals[-1] if vals else None, None, None
        mu = sum(rets) / len(rets)
        m = mu
        var = sum((r - m) ** 2 for r in rets) / max(1, (len(rets) - 1))
        sigma = math.sqrt(var)
        return vals[-1], mu, sigma

    def _forecast_series(last: float | None, mu: float | None, sigma: float | None):
        if last is None or mu is None or sigma is None:
            return {"end": None, "series": []}
        out = []
        for i in range(steps + 1):
            t = i
            exp = math.exp(mu * t)
            base = last * exp
            band = math.exp(sigma * math.sqrt(max(t, 1e-9)))
            lo = base / band
            hi = base * band
            out.append({"t": i, "base": base, "low": lo, "high": hi})
        return {"end": out[-1]["base"] if out else None, "series": out}

    g_last, g_mu, g_sigma = _mu_sigma(gold_vals)
    s_last, s_mu, s_sigma = _mu_sigma(silver_vals)

    g_out = _forecast_series(g_last, g_mu, g_sigma)
    s_out = _forecast_series(s_last, s_mu, s_sigma)

    payload = {
        "horizon": h,
        "used_tickers": used,
        "requested_tickers": {"gold": gold_req, "silver": silver_req},
        "step_seconds": step_seconds,
        "gold": {"last": g_last, "predicted_end": g_out["end"], "series": g_out["series"]},
        "silver": {"last": s_last, "predicted_end": s_out["end"], "series": s_out["series"]},
        "disclaimer": "Educational forecast using simple drift/volatility from recent prices. Not investment advice.",
    }
    _set_cached(key, payload, ttl_seconds=ttl)
    return payload


def _series_close(sym: str, period: str, interval: str = "1d", limit: int | None = None) -> list[dict]:
    out: list[dict] = []
    try:
        df = yf.Ticker(sym).history(period=period, interval=interval)
        closes = df.get("Close") if df is not None else None
        if closes is None:
            return []
        s = closes.dropna()
        if limit:
            s = s.tail(limit)
        for idx, val in s.items():
            try:
                ds = idx.isoformat() if hasattr(idx, "isoformat") else str(idx)
                out.append({"date": ds, "close": float(val)})
            except Exception:
                continue
    except Exception:
        return []
    return out


def _simple_returns(vals: list[float]) -> list[float]:
    out: list[float] = []
    for a, b in zip(vals[:-1], vals[1:]):
        try:
            if a:
                out.append((b - a) / a)
        except Exception:
            continue
    return out


def _mean(vals: list[float]) -> float | None:
    return (sum(vals) / len(vals)) if vals else None


def _std(vals: list[float]) -> float | None:
    if len(vals) < 2:
        return None
    m = _mean(vals)
    if m is None:
        return None
    var = sum((v - m) ** 2 for v in vals) / (len(vals) - 1)
    return var ** 0.5


def _pearson(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3 or len(a) != len(b):
        return None
    ma = _mean(a)
    mb = _mean(b)
    if ma is None or mb is None:
        return None
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den_a = sum((x - ma) ** 2 for x in a) ** 0.5
    den_b = sum((y - mb) ** 2 for y in b) ** 0.5
    if not den_a or not den_b:
        return None
    return num / (den_a * den_b)


def btc_quote_fast(ttl_seconds: int = 20) -> dict:
    ttl_seconds = max(10, min(60, int(ttl_seconds or 20)))
    key = f"btc:quote:{ttl_seconds}"
    cached = _get_cached(key)
    if cached is not None:
        return cached

    sym = (os.getenv("BTC_TICKER") or "BTC-USD").strip() or "BTC-USD"
    q = get_fast_quote(sym)
    out = {
        "ticker": sym,
        "last_price": q.get("last_price"),
        "previous_close": q.get("previous_close"),
        "currency": q.get("currency") or "USD",
        "time_zone": q.get("time_zone"),
        "cached_for_s": ttl_seconds,
    }
    _set_cached(key, out, ttl_seconds=ttl_seconds)
    return out


def btc_news(limit: int = 6) -> list[dict]:
    limit = max(3, min(12, int(limit or 6)))
    key = f"btc:news:{limit}"
    cached = _get_cached(key)
    if cached is not None:
        return cached

    sym = (os.getenv("BTC_TICKER") or "BTC-USD").strip() or "BTC-USD"
    items: list[dict] = []
    try:
        news = getattr(yf.Ticker(sym), "news", None) or []
        for n in news:
            title = n.get("title") or ""
            link = n.get("link") or n.get("url") or ""
            if not title or not link:
                continue
            items.append(
                {
                    "title": title,
                    "publisher": n.get("publisher") or "",
                    "link": link,
                    "published_at": n.get("providerPublishTime"),
                    "source": sym,
                }
            )
    except Exception:
        items = []

    deduped = []
    seen: set[str] = set()
    for it in sorted(items, key=lambda x: x.get("published_at") or 0, reverse=True):
        title = it.get("title") or ""
        if title in seen:
            continue
        seen.add(title)
        deduped.append(it)
        if len(deduped) >= limit:
            break

    _set_cached(key, deduped, ttl_seconds=600)
    return deduped


def btc_summary(days: int = 30) -> dict:
    days = max(7, min(90, int(days or 30)))
    key = f"btc:summary:{days}"
    cached = _get_cached(key)
    if cached is not None:
        return cached

    sym = (os.getenv("BTC_TICKER") or "BTC-USD").strip() or "BTC-USD"
    quote = btc_quote_fast(ttl_seconds=20)
    series = _series_close(sym, period=f"{max(days + 15, 45)}d", interval="1d", limit=days)
    vals = [p["close"] for p in series if p.get("close") is not None]

    intraday = _series_close(sym, period="5d", interval="1h", limit=36)
    intra_vals = [p["close"] for p in intraday if p.get("close") is not None]
    y52 = _series_close(sym, period="1y", interval="1d")
    y52_vals = [p["close"] for p in y52 if p.get("close") is not None]
    long_hist = _series_close(sym, period="5y", interval="1d")
    long_vals = [p["close"] for p in long_hist if p.get("close") is not None]

    returns = _simple_returns(vals)
    last = quote.get("last_price")
    prev = quote.get("previous_close")
    day_change_pct = ((last - prev) / prev) * 100.0 if last is not None and prev not in (None, 0) else None
    vol_30d = (_std(returns) or 0.0) * (365 ** 0.5) * 100.0 if returns else None

    # correlations against common risk/barometer assets
    bench_syms = {
        "gold": (os.getenv("METALS_GOLD_FALLBACK") or "GC=F").strip() or "GC=F",
        "silver": (os.getenv("METALS_SILVER_FALLBACK") or "SI=F").strip() or "SI=F",
        "nasdaq": "^IXIC",
        "nifty": "^NSEI",
    }
    corr_rows = []
    for label, bsym in bench_syms.items():
        bench = _series_close(bsym, period="90d", interval="1d", limit=60)
        bmap = {p["date"][:10]: p["close"] for p in bench}
        smap = {p["date"][:10]: p["close"] for p in series}
        dates = sorted(set(bmap.keys()) & set(smap.keys()))
        btc_aligned = [float(smap[d]) for d in dates if smap.get(d) is not None and bmap.get(d) is not None]
        bench_aligned = [float(bmap[d]) for d in dates if smap.get(d) is not None and bmap.get(d) is not None]
        corr = None
        if len(btc_aligned) >= 5 and len(btc_aligned) == len(bench_aligned):
            corr = _pearson(_simple_returns(btc_aligned), _simple_returns(bench_aligned))
        corr_rows.append({"label": label.title(), "symbol": bsym, "correlation": corr})

    payload = {
        "ticker": sym,
        "quote": quote,
        "series": series,
        "records": {
            "day_high": max(intra_vals) if intra_vals else None,
            "day_low": min(intra_vals) if intra_vals else None,
            "high_30d": max(vals) if vals else None,
            "low_30d": min(vals) if vals else None,
            "high_52w": max(y52_vals) if y52_vals else None,
            "low_52w": min(y52_vals) if y52_vals else None,
            "ath_5y": max(long_vals) if long_vals else None,
        },
        "metrics": {
            "day_change_pct": day_change_pct,
            "return_30d_pct": (((vals[-1] - vals[0]) / vals[0]) * 100.0) if len(vals) >= 2 and vals[0] else None,
            "volatility_30d_annualized_pct": vol_30d,
            "support_zone": min(vals[-10:]) if len(vals) >= 10 else (min(vals) if vals else None),
            "resistance_zone": max(vals[-10:]) if len(vals) >= 10 else (max(vals) if vals else None),
        },
        "correlations": corr_rows,
        "available": bool(series) and (quote.get("last_price") is not None),
        "note": "BTC data is best-effort via Yahoo Finance. Educational only.",
    }
    _set_cached(key, payload, ttl_seconds=60)
    return payload


def btc_predictions(horizon: str = "1m") -> dict:
    h = (horizon or "1m").strip().lower()
    if h not in ("1w", "1m", "3m"):
        h = "1m"

    ttl = {"1w": 120, "1m": 300, "3m": 600}.get(h, 300)
    key = f"btc:predictions:{h}"
    cached = _get_cached(key)
    if cached is not None:
        return cached

    sym = (os.getenv("BTC_TICKER") or "BTC-USD").strip() or "BTC-USD"
    hist = _series_close(sym, period="2y", interval="1d")
    vals = [float(p["close"]) for p in hist if p.get("close") is not None]
    dates = [str(p["date"])[:10] for p in hist if p.get("close") is not None]
    if len(vals) < 40:
        payload = {"ticker": sym, "horizon": h, "algorithms": {}, "correlations": [], "disclaimer": "Not enough BTC history yet."}
        _set_cached(key, payload, ttl_seconds=ttl)
        return payload

    if h == "1w":
        steps = 7
    elif h == "3m":
        steps = 90
    else:
        steps = 30

    last = vals[-1]
    recent = vals[-120:]
    recent_rets = _simple_returns(recent)
    mu = _mean(recent_rets) or 0.0
    sigma = _std(recent_rets) or 0.0
    mean_price = _mean(recent[-30:]) or last

    def _future_points(out_vals: list[float]) -> list[dict]:
        return [{"t": i, "xLabel": "Now" if i == 0 else ("End" if i == len(out_vals) - 1 else ""), "price": float(v)} for i, v in enumerate(out_vals)]

    # Linear regression on recent prices
    x = list(range(len(recent)))
    x_mean = _mean(x) or 0.0
    y_mean = _mean(recent) or last
    den = sum((xi - x_mean) ** 2 for xi in x) or 1.0
    slope = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, recent)) / den
    linear_vals = [last] + [max(0.0, last + slope * i) for i in range(1, steps + 1)]

    # Logistic trend classifier -> expected drift from probability of up move
    ema12 = recent[0]
    ema26 = recent[0]
    a12 = 2 / (12 + 1)
    a26 = 2 / (26 + 1)
    for p in recent[1:]:
        ema12 = a12 * p + (1 - a12) * ema12
        ema26 = a26 * p + (1 - a26) * ema26
    ret7 = ((recent[-1] - recent[-8]) / recent[-8]) if len(recent) >= 8 and recent[-8] else 0.0
    score = 10.0 * ret7 + 8.0 * ((ema12 - ema26) / max(last, 1e-9))
    prob_up = 1.0 / (1.0 + math.exp(-score))
    logistic_drift = (prob_up - 0.5) * 2.0 * max(sigma, 0.004) * 0.8
    logistic_vals = [last]
    lv = last
    for _ in range(steps):
        lv = max(0.0, lv * (1.0 + logistic_drift))
        logistic_vals.append(lv)

    # ARIMA-lite on first differences: ARIMA(1,1,0)-style
    diffs = [b - a for a, b in zip(recent[:-1], recent[1:])]
    d_mean = _mean(diffs) or 0.0
    prev_d = diffs[-1] if diffs else 0.0
    num = sum((a - d_mean) * (b - d_mean) for a, b in zip(diffs[:-1], diffs[1:])) if len(diffs) > 2 else 0.0
    den_d = sum((a - d_mean) ** 2 for a in diffs[:-1]) if len(diffs) > 2 else 0.0
    phi = (num / den_d) if den_d else 0.0
    phi = max(-0.95, min(0.95, phi))
    arima_vals = [last]
    av = last
    for _ in range(steps):
        prev_d = d_mean + phi * (prev_d - d_mean)
        av = max(0.0, av + prev_d)
        arima_vals.append(av)

    # Momentum drift from log-return mean
    momentum_vals = [last]
    mv = last
    for _ in range(steps):
        mv = max(0.0, mv * math.exp(mu))
        momentum_vals.append(mv)

    # Mean reversion to rolling mean
    k = 0.12
    mean_rev_vals = [last]
    rv = last
    for _ in range(steps):
        rv = max(0.0, rv + k * (mean_price - rv))
        mean_rev_vals.append(rv)

    # EMA trend projection
    ema_gap = (ema12 - ema26) / max(last, 1e-9)
    ema_drift = ema_gap * 0.9
    ema_vals = [last]
    ev = last
    for _ in range(steps):
        ev = max(0.0, ev * (1.0 + ema_drift))
        ema_vals.append(ev)

    correlations = btc_summary(days=30).get("correlations", [])
    payload = {
        "ticker": sym,
        "horizon": h,
        "algorithms": {
            "linear": {
                "label": "Linear Regression",
                "summary": "Projects the current price trend as a straight line.",
                "predicted_end": linear_vals[-1],
                "series": _future_points(linear_vals),
            },
            "logistic": {
                "label": "Logistic Trend",
                "summary": "Uses momentum and EMA spread to estimate probability of upside continuation.",
                "probability_up": prob_up,
                "predicted_end": logistic_vals[-1],
                "series": _future_points(logistic_vals),
            },
            "arima": {
                "label": "ARIMA-lite (1,1,0)",
                "summary": "Lightweight autoregressive model on daily price changes.",
                "predicted_end": arima_vals[-1],
                "series": _future_points(arima_vals),
            },
            "momentum": {
                "label": "Momentum Drift",
                "summary": "Extends recent average return as a smooth drift path.",
                "predicted_end": momentum_vals[-1],
                "series": _future_points(momentum_vals),
            },
            "mean_reversion": {
                "label": "Mean Reversion",
                "summary": "Assumes price gradually reverts toward the recent average.",
                "predicted_end": mean_rev_vals[-1],
                "series": _future_points(mean_rev_vals),
            },
            "ema_trend": {
                "label": "EMA Trend",
                "summary": "Uses the gap between short and long EMAs as directional bias.",
                "predicted_end": ema_vals[-1],
                "series": _future_points(ema_vals),
            },
            "correlation": {
                "label": "Correlation View",
                "summary": "Shows how BTC has been moving versus risk and commodity benchmarks.",
                "predicted_end": None,
                "series": [],
                "correlations": correlations,
            },
        },
        "correlations": correlations,
        "history_points": [{"date": d, "close": v} for d, v in zip(dates[-90:], vals[-90:])],
        "disclaimer": "Educational only. These are lightweight models, not investment advice.",
    }
    _set_cached(key, payload, ttl_seconds=ttl)
    return payload
