from __future__ import annotations

import csv
import difflib
import io
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import close_old_connections
from django.db import transaction as db_transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.authtoken.models import Token
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserProfile
from .models import CachedPayload
from .edachi import (
    answer_public_question,
    answer_question,
    build_context,
    build_guest_context,
    build_quick_brief,
    clear_session,
    get_or_init_session,
    save_feedback,
    save_guest_feedback,
)
from .chat_tools import build_market_intel, chat_observability_dashboard, compute_recommendations, curate_chat_memory
from portfolio.models import Holding, Portfolio, Sector, Stock, Transaction
from watchlist.models import PriceAlert, WatchlistItem

from .serializers import (
    AccountSerializer,
    HoldingSerializer,
    PasswordChangeSerializer,
    PortfolioSerializer,
    PriceAlertCreateSerializer,
    PriceAlertSerializer,
    ProfileUpdateSerializer,
    RegisterSerializer,
    StockSerializer,
    TradeCreateSerializer,
    TransactionSerializer,
    UserSerializer,
    WatchlistAddSerializer,
    WatchlistItemSerializer,
)
from .yf_client import (
    btc_news,
    btc_predictions,
    btc_quote_fast,
    btc_summary,
    download_daily,
    get_52w_range,
    get_fast_quote,
    get_fundamentals,
    metals_forecast,
    metals_news,
    metals_quote_fast,
    metals_summary,
    search_equities,
)


_refresh_flags: dict[str, bool] = {}
_refresh_lock = threading.Lock()


def _client_ip(request) -> str:
    xff = str(request.META.get("HTTP_X_FORWARDED_FOR") or "").strip()
    if xff:
        return xff.split(",")[0].strip()
    return str(request.META.get("REMOTE_ADDR") or "unknown")


def _edachi_guest_limit(request) -> tuple[bool, dict]:
    # Guest policy: lower throughput than logged-in users.
    per_min_limit = int(os.getenv("EDACHI_GUEST_PER_MINUTE", "5") or "5")
    per_day_limit = int(os.getenv("EDACHI_GUEST_PER_DAY", "40") or "40")
    per_min_limit = int(os.getenv("EDACHI_GUEST_PER_MINUTE", "15") or "15")
    per_day_limit = int(os.getenv("EDACHI_GUEST_PER_DAY", "250") or "250")
    ip = _client_ip(request)
    key_min = f"edachi:guest:min:{ip}"
    key_day = f"edachi:guest:day:{ip}:{timezone.now().date().isoformat()}"

    per_min = cache.get(key_min, 0)
    per_day = cache.get(key_day, 0)
    blocked = per_min >= per_min_limit or per_day >= per_day_limit
    meta = {
        "remaining_minute": max(0, per_min_limit - per_min),
        "remaining_day": max(0, per_day_limit - per_day),
        "limits": {"per_minute": per_min_limit, "per_day": per_day_limit},
    }
    if blocked:
        return False, meta

    cache.set(key_min, per_min + 1, timeout=60)
    cache.set(key_day, per_day + 1, timeout=60 * 60 * 24)
    return True, meta


def _infer_exchange(symbol: str, exchange_hint: str | None = None) -> str:
    symbol = (symbol or "").strip().upper()
    hint = (exchange_hint or "").strip().upper()
    if symbol.endswith(".NS") or "NSE" in hint:
        return "NSE"
    if symbol.endswith(".BO") or "BSE" in hint:
        return "BSE"
    if "NASDAQ" in hint:
        return "NASDAQ"
    if "NYSE" in hint:
        return "NYSE"
    return "US"


def _get_or_create_stock(symbol: str, name_hint: str | None = None, exchange_hint: str | None = None) -> Stock:
    symbol = (symbol or "").strip().upper()
    name_hint = (name_hint or "").strip()
    exchange = _infer_exchange(symbol, exchange_hint)
    stock, created = Stock.objects.get_or_create(
        symbol=symbol,
        defaults={"name": name_hint or symbol, "exchange": exchange},
    )
    if not created and name_hint and stock.name != name_hint:
        stock.name = name_hint
        stock.exchange = exchange
        stock.save(update_fields=["name", "exchange"])
    return stock


def _normalize_csv_header(name: str) -> str:
    text = (name or "").strip().lower()
    return "".join(ch for ch in text if ch.isalnum() or ch == "_")


def _csv_pick(row: dict, keys: list[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _decimal_or_none(value: str) -> Decimal | None:
    text = (value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        num = Decimal(text)
        return num
    except Exception:
        return None


def _looks_like_symbol(value: str) -> bool:
    text = (value or "").strip().upper()
    if not text or text.startswith("^"):
        return False
    if text.endswith(".NS") or text.endswith(".BO"):
        return True
    # US-like symbols: AAPL, MSFT, BRK-B, TCS.TO
    return bool(text) and all(ch.isalnum() or ch in {".", "-"} for ch in text)


def _normalize_name_key(value: str) -> str:
    text = (value or "").strip().lower()
    return "".join(ch for ch in text if ch.isalnum())


def _portfolio_match_keys(label: str) -> list[str]:
    """
    Build multiple matching keys so sector labels can map to existing compact portfolio names
    (for example: "Information Technology" -> "it", "tech", "technology").
    """
    base = _normalize_name_key(label)
    keys = {base}

    if "informationtechnology" in base or base in {"technology", "tech"}:
        keys.update({"it", "tech", "technology", "informationtechnology"})
    if "healthcare" in base or "pharma" in base:
        keys.update({"healthcare", "pharma", "pharmaceutical", "pharmaceuticals"})
    if "financialservices" in base or "bank" in base or "finance" in base:
        keys.update({"financialservices", "finance", "banking", "bank"})
    if "consumerdurables" in base or "fmcg" in base or "consumer" in base:
        keys.update({"consumerdurables", "consumer", "fmcg"})
    if "telecommunication" in base or "telecom" in base:
        keys.update({"telecom", "telecommunication"})
    if "metals" in base or "mining" in base:
        keys.update({"metals", "mining", "metalsmining"})

    return [k for k in keys if k]


def _parse_import_csv(uploaded_file) -> list[dict]:
    raw = uploaded_file.read()
    text = ""
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except Exception:
            continue
    if not text:
        return []

    sample = text[:4096]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter or ","
    except Exception:
        delimiter = ","

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        return []

    field_map = {name: _normalize_csv_header(name) for name in reader.fieldnames}
    rows: list[dict] = []
    for src_row in reader:
        normalized = {}
        for orig_name, norm_name in field_map.items():
            normalized[norm_name] = src_row.get(orig_name)
        rows.append(normalized)
    return rows


def _compute_market_summary(top_universe: list[str]) -> dict:
    nifty = get_fast_quote("^NSEI")
    sensex = get_fast_quote("^BSESN")

    df = download_daily(top_universe, days=5)
    movers = []
    for symbol in top_universe:
        try:
            hist = df[symbol] if symbol in df.columns.get_level_values(0) else None
            if hist is None or hist.empty:
                continue
            closes = hist["Close"].dropna()
            if len(closes) < 1:
                continue
            last = float(closes.iloc[-1])
            prev = float(closes.iloc[-2]) if len(closes) >= 2 else last
            chg_pct = ((last - prev) / prev) * 100 if prev else 0.0
            movers.append({"symbol": symbol, "last": last, "changePct": chg_pct})
        except Exception:
            continue

    movers.sort(key=lambda x: abs(x["changePct"]), reverse=True)
    top10 = movers[:10]

    return {
        "indices": {"nifty": nifty, "sensex": sensex},
        "top10": top10,
        "note": "Top10 is computed from a fixed Nifty-like universe for Day-1 demo.",
    }


def warm_market_summary_cache(cache_key: str, top_universe: list[str], force: bool = False, fresh_seconds: int = 45) -> dict:
    now = timezone.now()
    snapshot = CachedPayload.objects.filter(key=cache_key).first()
    if snapshot and not force:
        age_seconds = (now - snapshot.updated_at).total_seconds()
        if age_seconds <= fresh_seconds:
            payload = dict(snapshot.payload or {})
            payload["meta"] = {
                "source": "snapshot",
                "updated_at": snapshot.updated_at.isoformat(),
                "stale": False,
                "age_seconds": round(age_seconds, 1),
            }
            return payload

    try:
        payload = _compute_market_summary(top_universe)
        snapshot, _ = CachedPayload.objects.update_or_create(key=cache_key, defaults={"payload": payload})
        payload["meta"] = {
            "source": "fresh",
            "updated_at": snapshot.updated_at.isoformat(),
            "stale": False,
            "age_seconds": 0,
        }
        return payload
    except Exception:
        if snapshot:
            age_seconds = (now - snapshot.updated_at).total_seconds()
            payload = dict(snapshot.payload or {})
            payload["meta"] = {
                "source": "snapshot",
                "updated_at": snapshot.updated_at.isoformat(),
                "stale": True,
                "age_seconds": round(age_seconds, 1),
            }
            return payload
        return {
            "indices": {"nifty": {}, "sensex": {}},
            "top10": [],
            "note": "Market data temporarily unavailable. Last snapshot will appear after first successful refresh.",
            "meta": {
                "source": "unavailable",
                "updated_at": now.isoformat(),
                "stale": True,
                "age_seconds": None,
            },
        }


def _compute_dashboard_summary(user) -> dict:
    portfolios = Portfolio.objects.filter(user=user).order_by("-created_at")
    portfolio_ids = list(portfolios.values_list("id", flat=True))

    holdings_qs = Holding.objects.filter(portfolio_id__in=portfolio_ids).select_related("stock")
    holdings_count = holdings_qs.count()

    realized_total = Transaction.objects.filter(portfolio_id__in=portfolio_ids, side="SELL").values_list("realized_pnl", flat=True)
    try:
        realized_pnl_total = str(sum((Decimal(str(x)) for x in realized_total), Decimal("0")))
    except Exception:
        realized_pnl_total = "0"

    watch_items = WatchlistItem.objects.filter(user=user).select_related("stock")[:8]
    watchlist_count = WatchlistItem.objects.filter(user=user).count()

    watchlist_preview = []
    for wi in watch_items:
        last = None
        try:
            last = get_fast_quote(wi.stock.symbol).get("last_price")
        except Exception:
            last = None
        watchlist_preview.append({"id": wi.id, "symbol": wi.stock.symbol, "name": wi.stock.name, "last_price": last})

    alerts = PriceAlert.objects.filter(user=user)
    alerts_active = alerts.filter(is_active=True, triggered_at__isnull=True).count()
    alerts_triggered = alerts.filter(triggered_at__isnull=False).count()

    recent_txs = (
        Transaction.objects.filter(portfolio_id__in=portfolio_ids)
        .select_related("stock", "portfolio")
        .order_by("-executed_at", "-id")[:8]
    )
    recent = [
        {
            "id": t.id,
            "portfolio_id": t.portfolio_id,
            "portfolio_name": t.portfolio.name,
            "symbol": t.stock.symbol,
            "side": t.side,
            "qty": str(t.qty),
            "price": str(t.price),
            "realized_pnl": str(t.realized_pnl),
            "executed_at": t.executed_at.isoformat() if t.executed_at else None,
        }
        for t in recent_txs
    ]

    profile, _ = UserProfile.objects.get_or_create(user=user)
    default_portfolio = None
    if profile.default_portfolio_id:
        default_portfolio = {"id": profile.default_portfolio_id, "name": profile.default_portfolio.name}

    nifty = get_fast_quote("^NSEI")
    sensex = get_fast_quote("^BSESN")

    return {
        "user": UserSerializer(user).data,
        "profile": {
            "default_redirect": profile.default_redirect,
            "default_portfolio": default_portfolio,
        },
        "kpis": {
            "portfolios": portfolios.count(),
            "holdings": holdings_count,
            "realized_pnl_total": realized_pnl_total,
            "watchlist": watchlist_count,
            "alerts_active": alerts_active,
            "alerts_triggered": alerts_triggered,
        },
        "portfolios": [
            {
                "id": p.id,
                "name": p.name,
                "market": p.market,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in portfolios[:20]
        ],
        "watchlist_preview": watchlist_preview,
        "recent_transactions": recent,
        "market": {"nifty": nifty, "sensex": sensex},
    }


def _minimal_dashboard_summary(user, note: str | None = None) -> dict:
    portfolios = list(Portfolio.objects.filter(user=user).order_by("-created_at")[:20])
    profile, _ = UserProfile.objects.get_or_create(user=user)
    default_portfolio = None
    if profile.default_portfolio_id:
        default_portfolio = {"id": profile.default_portfolio_id, "name": profile.default_portfolio.name}

    return {
        "user": UserSerializer(user).data,
        "profile": {
            "default_redirect": profile.default_redirect,
            "default_portfolio": default_portfolio,
        },
        "kpis": {
            "portfolios": len(portfolios),
            "holdings": Holding.objects.filter(portfolio__user=user).count(),
            "realized_pnl_total": "0",
            "watchlist": WatchlistItem.objects.filter(user=user).count(),
            "alerts_active": PriceAlert.objects.filter(user=user, is_active=True, triggered_at__isnull=True).count(),
            "alerts_triggered": PriceAlert.objects.filter(user=user, triggered_at__isnull=False).count(),
        },
        "portfolios": [
            {
                "id": p.id,
                "name": p.name,
                "market": p.market,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in portfolios
        ],
        "watchlist_preview": [],
        "recent_transactions": [],
        "market": {"nifty": {}, "sensex": {}},
        "note": note or "Dashboard loaded with reduced data because live refresh is unavailable.",
    }


def warm_dashboard_summary_cache(user, force: bool = False, fresh_seconds: int = 45) -> dict:
    now = timezone.now()
    cache_key = f"dashboard_summary:user:{user.id}"
    snapshot = CachedPayload.objects.filter(key=cache_key).first()
    if snapshot and not force:
        age_seconds = (now - snapshot.updated_at).total_seconds()
        if age_seconds <= fresh_seconds:
            payload = dict(snapshot.payload or {})
            payload["meta"] = {
                "source": "snapshot",
                "updated_at": snapshot.updated_at.isoformat(),
                "stale": False,
                "age_seconds": round(age_seconds, 1),
            }
            return payload

    try:
        payload = _compute_dashboard_summary(user)
        snapshot, _ = CachedPayload.objects.update_or_create(key=cache_key, defaults={"payload": payload})
        payload["meta"] = {
            "source": "fresh",
            "updated_at": snapshot.updated_at.isoformat(),
            "stale": False,
            "age_seconds": 0,
        }
        return payload
    except Exception:
        if snapshot:
            age_seconds = (now - snapshot.updated_at).total_seconds()
            payload = dict(snapshot.payload or {})
            payload["meta"] = {
                "source": "snapshot",
                "updated_at": snapshot.updated_at.isoformat(),
                "stale": True,
                "age_seconds": round(age_seconds, 1),
            }
            return payload
        payload = _minimal_dashboard_summary(user)
        payload["meta"] = {
            "source": "fallback",
            "updated_at": now.isoformat(),
            "stale": True,
            "age_seconds": None,
        }
        return payload


def _refresh_cached_dashboard_summary(user_id: int, fresh_seconds: int = 45) -> None:
    close_old_connections()
    try:
        user = User.objects.filter(id=user_id).first()
        if user:
            warm_dashboard_summary_cache(user=user, force=True, fresh_seconds=fresh_seconds)
    except Exception:
        pass
    finally:
        cache_key = f"dashboard_summary:user:{user_id}"
        with _refresh_lock:
            _refresh_flags[cache_key] = False
        close_old_connections()


def _start_dashboard_refresh(user_id: int, fresh_seconds: int = 45) -> None:
    cache_key = f"dashboard_summary:user:{user_id}"
    with _refresh_lock:
        if _refresh_flags.get(cache_key):
            return
        _refresh_flags[cache_key] = True
    t = threading.Thread(target=_refresh_cached_dashboard_summary, args=(user_id, fresh_seconds), daemon=True)
    t.start()


def _refresh_cached_market_summary(cache_key: str, top_universe: list[str]) -> None:
    close_old_connections()
    try:
        payload = _compute_market_summary(top_universe)
        CachedPayload.objects.update_or_create(key=cache_key, defaults={"payload": payload})
    except Exception:
        pass
    finally:
        with _refresh_lock:
            _refresh_flags[cache_key] = False
        close_old_connections()


def _compute_portfolio_snapshot(portfolio: Portfolio) -> dict:
    data = PortfolioSerializer(portfolio).data
    holdings = Holding.objects.filter(portfolio=portfolio).select_related("stock", "stock__sector").order_by("stock__symbol")
    holdings_data = HoldingSerializer(holdings, many=True).data

    realized_total = Transaction.objects.filter(portfolio=portfolio, side="SELL").values_list("realized_pnl", flat=True)
    try:
        data["realized_pnl_total"] = str(sum((Decimal(str(x)) for x in realized_total), Decimal("0")))
    except Exception:
        data["realized_pnl_total"] = "0"

    symbols = [h.stock.symbol for h in holdings]
    quotes: dict[str, dict] = {}
    unique_symbols = list(dict.fromkeys([s for s in symbols if s]))
    if unique_symbols:
        max_workers = max(2, min(10, len(unique_symbols)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(get_fast_quote, sym): sym for sym in unique_symbols}
            for future in as_completed(future_map):
                sym = future_map[future]
                try:
                    quotes[sym] = future.result() or {"ticker": sym, "last_price": None}
                except Exception:
                    quotes[sym] = {"ticker": sym, "last_price": None}

    for item in holdings_data:
        symbol = item.get("stock", {}).get("symbol")
        quote = quotes.get(symbol or "", {})
        last_price = quote.get("last_price")
        item["last_price"] = last_price
        try:
            qty = Decimal(str(item.get("qty", "0")))
            avg = Decimal(str(item.get("avg_buy_price", "0")))
            if last_price is None:
                item["unrealized_pnl"] = None
            else:
                lp = Decimal(str(last_price))
                item["unrealized_pnl"] = str((lp - avg) * qty)
        except Exception:
            item["unrealized_pnl"] = None

    data["holdings"] = holdings_data
    return data


def warm_portfolio_snapshot_cache(portfolio: Portfolio, force: bool = False, fresh_seconds: int = 45) -> dict:
    now = timezone.now()
    cache_key = f"portfolio_snapshot:{portfolio.id}"
    snapshot = CachedPayload.objects.filter(key=cache_key).first()
    if snapshot and not force:
        age_seconds = (now - snapshot.updated_at).total_seconds()
        payload = dict(snapshot.payload or {})
        payload["meta"] = {
            "source": "snapshot",
            "updated_at": snapshot.updated_at.isoformat(),
            "stale": age_seconds > fresh_seconds,
            "age_seconds": round(age_seconds, 1),
        }
        return payload

    try:
        payload = _compute_portfolio_snapshot(portfolio)
        snapshot, _ = CachedPayload.objects.update_or_create(key=cache_key, defaults={"payload": payload})
        payload["meta"] = {
            "source": "fresh",
            "updated_at": snapshot.updated_at.isoformat(),
            "stale": False,
            "age_seconds": 0,
        }
        return payload
    except Exception:
        if snapshot:
            age_seconds = (now - snapshot.updated_at).total_seconds()
            payload = dict(snapshot.payload or {})
            payload["meta"] = {
                "source": "snapshot",
                "updated_at": snapshot.updated_at.isoformat(),
                "stale": True,
                "age_seconds": round(age_seconds, 1),
            }
            return payload
        raise


def _refresh_cached_portfolio_snapshot(portfolio_id: int, user_id: int, fresh_seconds: int = 45) -> None:
    close_old_connections()
    try:
        portfolio = Portfolio.objects.filter(id=portfolio_id, user_id=user_id).first()
        if portfolio:
            warm_portfolio_snapshot_cache(portfolio=portfolio, force=True, fresh_seconds=fresh_seconds)
    except Exception:
        pass
    finally:
        cache_key = f"portfolio_snapshot:{portfolio_id}"
        with _refresh_lock:
            _refresh_flags[cache_key] = False
        close_old_connections()


def _start_portfolio_snapshot_refresh(portfolio_id: int, user_id: int, fresh_seconds: int = 45) -> None:
    cache_key = f"portfolio_snapshot:{portfolio_id}"
    with _refresh_lock:
        if _refresh_flags.get(cache_key):
            return
        _refresh_flags[cache_key] = True
    t = threading.Thread(target=_refresh_cached_portfolio_snapshot, args=(portfolio_id, user_id, fresh_seconds), daemon=True)
    t.start()


def _start_market_refresh(cache_key: str, top_universe: list[str]) -> None:
    with _refresh_lock:
        if _refresh_flags.get(cache_key):
            return
        _refresh_flags[cache_key] = True
    t = threading.Thread(target=_refresh_cached_market_summary, args=(cache_key, top_universe), daemon=True)
    t.start()


class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        username = request.data.get("username", "")
        password = request.data.get("password", "")
        user = authenticate(username=username, password=password)
        if user is None:
            return Response({"detail": "Invalid credentials"}, status=status.HTTP_400_BAD_REQUEST)
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "user": UserSerializer(user).data})


class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)


class AccountView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        return Response(
            {
                "user": UserSerializer(request.user).data,
                "profile": {
                    "full_name": profile.full_name,
                    "bio": profile.bio,
                    "default_redirect": profile.default_redirect,
                    "default_portfolio": {"id": profile.default_portfolio_id, "name": profile.default_portfolio.name}
                    if profile.default_portfolio_id
                    else None,
                    "updated_at": profile.updated_at,
                },
            }
        )

    def patch(self, request):
        serializer = ProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Update user
        user = request.user
        if "username" in data and data["username"] != user.username:
            if User.objects.filter(username=data["username"]).exclude(id=user.id).exists():
                return Response({"username": ["This username is already taken."]}, status=status.HTTP_400_BAD_REQUEST)
            user.username = data["username"]
        if "email" in data:
            user.email = data["email"] or ""
        user.save()

        # Update profile
        profile, _ = UserProfile.objects.get_or_create(user=user)
        if "full_name" in data:
            profile.full_name = data["full_name"] or ""
        if "bio" in data:
            profile.bio = data["bio"] or ""
        if "default_redirect" in data:
            profile.default_redirect = data["default_redirect"]
        if "default_portfolio_id" in data:
            pid = data["default_portfolio_id"]
            if pid is None:
                profile.default_portfolio = None
            else:
                p = Portfolio.objects.filter(id=pid, user=user).first()
                if p is None:
                    return Response({"default_portfolio_id": ["Invalid portfolio."]}, status=status.HTTP_400_BAD_REQUEST)
                profile.default_portfolio = p
        profile.save()

        return self.get(request)


class PasswordChangeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        old_password = serializer.validated_data["old_password"]
        new_password = serializer.validated_data["new_password"]

        user = request.user
        if not user.check_password(old_password):
            return Response({"old_password": ["Incorrect password."]}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(new_password)
        user.save()

        # Invalidate token by deleting it (forces re-login).
        Token.objects.filter(user=user).delete()
        return Response({"detail": "Password changed. Please login again."})


class StocksListView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        q = request.query_params.get("q", "").strip()
        qs = Stock.objects.all().order_by("symbol")
        if q:
            qs = qs.filter(Q(symbol__icontains=q) | Q(name__icontains=q))
        return Response(StockSerializer(qs[:200], many=True).data)


class StocksLiveSearchView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        q = request.query_params.get("q", "").strip()
        if not q:
            return Response([])

        db_qs = Stock.objects.filter(Q(symbol__icontains=q) | Q(name__icontains=q)).order_by("symbol")[:50]
        db_items = {s.symbol: {"id": s.id, "symbol": s.symbol, "name": s.name, "exchange": s.exchange} for s in db_qs}

        try:
            live = search_equities(q, max_results=40)
        except Exception:
            live = []

        merged = []
        seen = set()

        for sym, item in db_items.items():
            if sym in seen:
                continue
            seen.add(sym)
            merged.append(item)

        for item in live:
            sym = item["symbol"]
            if sym in seen:
                continue
            seen.add(sym)
            merged.append({"id": None, **item})

        return Response(merged[:50])


class QuoteView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        symbol = request.query_params.get("symbol", "").strip()
        if not symbol:
            return Response({"detail": "symbol is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            return Response(get_fast_quote(symbol))
        except Exception:
            return Response({"detail": "Failed to fetch quote"}, status=status.HTTP_502_BAD_GATEWAY)


class StockDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        symbol = request.query_params.get("symbol", "").strip()
        if not symbol:
            return Response({"detail": "symbol is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            quote = get_fast_quote(symbol)
            fundamentals = get_fundamentals(symbol)
            r52w = get_52w_range(symbol)
        except Exception:
            return Response({"detail": "Failed to fetch stock detail"}, status=status.HTTP_502_BAD_GATEWAY)

        pe = fundamentals.get("trailingPE") or fundamentals.get("forwardPE")
        return Response(
            {
                "symbol": symbol,
                "quote": quote,
                "fundamentals": fundamentals,
                "pe": pe,
                "range_52w": r52w,
            }
        )


class StocksPreviewView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        raw = request.query_params.get("symbols", "").strip()
        if not raw:
            return Response({"detail": "symbols is required"}, status=status.HTTP_400_BAD_REQUEST)

        parts = [p.strip().upper() for p in raw.split(",") if p.strip()]
        # hard-limit to keep yfinance calls bounded
        symbols = []
        seen = set()
        for s in parts:
            if s in seen:
                continue
            seen.add(s)
            symbols.append(s)
            if len(symbols) >= 12:
                break

        out = []
        for symbol in symbols:
            try:
                quote = get_fast_quote(symbol)
            except Exception:
                quote = {"ticker": symbol, "last_price": None}

            try:
                fundamentals = get_fundamentals(symbol)
            except Exception:
                fundamentals = {}

            try:
                r52w = get_52w_range(symbol)
            except Exception:
                r52w = {"ticker": symbol, "low_52w": None, "high_52w": None}

            last = quote.get("last_price")
            pe = fundamentals.get("trailingPE") or fundamentals.get("forwardPE")
            high_52w = r52w.get("high_52w")
            discount_from_high_pct = None
            try:
                if last is not None and high_52w:
                    discount_from_high_pct = float(
                        ((Decimal(str(high_52w)) - Decimal(str(last))) / Decimal(str(high_52w))) * 100
                    )
            except Exception:
                discount_from_high_pct = None

            out.append(
                {
                    "symbol": symbol,
                    "last_price": last,
                    "pe": pe,
                    "high_52w": high_52w,
                    "discount_from_52w_high_pct": discount_from_high_pct,
                }
            )

        return Response(out)


class PortfoliosListCreateView(APIView):
    def get(self, request):
        qs = Portfolio.objects.filter(user=request.user).order_by("-created_at")
        return Response(PortfolioSerializer(qs, many=True).data)

    def post(self, request):
        serializer = PortfolioSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        portfolio = Portfolio.objects.create(user=request.user, **serializer.validated_data)
        return Response(PortfolioSerializer(portfolio).data, status=status.HTTP_201_CREATED)


class PortfolioCsvImportView(APIView):
    """
    CSV-driven quick portfolio import.

    Expected CSV columns (flexible headers):
    - symbol/ticker/stock_symbol
    - name/stock_name/company
    - qty/quantity/shares (optional, default 1)
    - price/avg_buy_price/buy_price (optional; falls back to quote, then 1)
    - sector/industry (optional)
    """

    def post(self, request):
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return Response({"detail": "CSV file is required in field 'file'."}, status=status.HTTP_400_BAD_REQUEST)

        mode = (request.data.get("mode") or "import").strip().lower()
        if mode not in {"preview", "import"}:
            return Response({"detail": "mode must be 'preview' or 'import'."}, status=status.HTTP_400_BAD_REQUEST)

        group_by_sector = str(request.data.get("group_by_sector", "false")).strip().lower() in {"1", "true", "yes", "on"}
        requested_base_name = (request.data.get("base_name") or "").strip()
        base_name = requested_base_name or f"Imported Portfolio {timezone.localtime().strftime('%Y-%m-%d %H:%M')}"

        rows = _parse_import_csv(uploaded)
        if not rows:
            return Response({"detail": "No rows found in CSV."}, status=status.HTTP_400_BAD_REQUEST)

        symbol_keys = ["symbol", "ticker", "stocksymbol", "stock_symbol", "tradingsymbol", "security", "code"]
        name_keys = ["name", "stockname", "stock_name", "company", "companyname", "company_name"]
        qty_keys = ["qty", "quantity", "shares", "units"]
        price_keys = ["price", "avgbuyprice", "avg_buy_price", "avgprice", "buyprice", "buy_price", "cost"]
        sector_keys = ["sector", "industry", "theme", "bucket"]

        resolved_rows: list[dict] = []
        skipped: list[dict] = []

        def _best_search_match(query: str, symbol_hint: str = "") -> dict | None:
            q = (query or "").strip()
            if not q:
                return None
            try:
                results = search_equities(q, max_results=12)
            except Exception:
                results = []
            if not results:
                return None
            hint = (symbol_hint or "").strip().upper()
            if hint:
                exact = next((x for x in results if str(x.get("symbol", "")).upper() == hint), None)
                if exact:
                    return exact
                pref = next((x for x in results if str(x.get("symbol", "")).upper().startswith(f"{hint}.")), None)
                if pref:
                    return pref
            q_upper = q.upper()
            scored = []
            for item in results:
                sym = str(item.get("symbol") or "").upper()
                name = str(item.get("name") or "")
                sym_score = difflib.SequenceMatcher(None, q_upper, sym).ratio()
                name_score = difflib.SequenceMatcher(None, q.lower(), name.lower()).ratio() if name else 0.0
                bonus = 0.2 if sym.startswith(q_upper) else 0.0
                scored.append((sym_score * 0.65 + name_score * 0.35 + bonus, item))
            scored.sort(key=lambda x: x[0], reverse=True)
            return scored[0][1] if scored else results[0]

        def _portfolio_name_for_sector(sector_name: str | None) -> str:
            if not group_by_sector:
                return base_name
            bucket = (sector_name or "").strip() or "Uncategorized"
            # Grouped mode is sector-first to keep dashboards clean and reusable.
            return bucket

        for idx, row in enumerate(rows, start=1):
            raw_symbol = _csv_pick(row, symbol_keys).upper()
            raw_name = _csv_pick(row, name_keys)
            raw_sector = _csv_pick(row, sector_keys)

            qty = _decimal_or_none(_csv_pick(row, qty_keys)) or Decimal("1")
            if qty <= 0:
                skipped.append({"row": idx, "reason": "qty must be > 0"})
                continue

            search_match = None
            symbol = raw_symbol
            name = raw_name
            exchange_hint = ""

            if symbol and "." in symbol and _looks_like_symbol(symbol):
                # Already exchange-qualified (AAPL, INFY.NS, TCS.BO, etc).
                exchange_hint = _infer_exchange(symbol)
            elif symbol:
                # For bare symbols from CSV (ADANIENT, AXISBANK), try best match first.
                search_match = _best_search_match(raw_name or symbol, symbol_hint=symbol)
            elif name:
                search_match = _best_search_match(name)
            else:
                skipped.append({"row": idx, "reason": "missing symbol and name"})
                continue

            if search_match:
                symbol = str(search_match.get("symbol") or symbol or "").strip().upper()
                exchange_hint = str(search_match.get("exchange") or "")
                if not name:
                    name = str(search_match.get("name") or symbol)
            elif symbol and _looks_like_symbol(symbol):
                exchange_hint = _infer_exchange(symbol)
                if "." not in symbol:
                    # Try common Indian suffixes when CSV has bare symbol.
                    ns_symbol = f"{symbol}.NS"
                    bo_symbol = f"{symbol}.BO"
                    try:
                        ns_q = get_fast_quote(ns_symbol)
                        if ns_q.get("last_price") is not None:
                            symbol = ns_symbol
                            exchange_hint = "NSE"
                        else:
                            bo_q = get_fast_quote(bo_symbol)
                            if bo_q.get("last_price") is not None:
                                symbol = bo_symbol
                                exchange_hint = "BSE"
                    except Exception:
                        pass

            if not symbol:
                skipped.append({"row": idx, "reason": "unable to resolve stock symbol"})
                continue

            price = _decimal_or_none(_csv_pick(row, price_keys))
            if price is None or price <= 0:
                # Keep import deterministic/fast; avoid per-row network quote calls.
                price = Decimal("1")

            sector_name = raw_sector
            if not sector_name and group_by_sector:
                try:
                    f = get_fundamentals(symbol) or {}
                    sector_name = str(f.get("sector") or "").strip()
                except Exception:
                    sector_name = ""

            resolved_rows.append(
                {
                    "row": idx,
                    "symbol": symbol,
                    "name": name or symbol,
                    "exchange": exchange_hint or _infer_exchange(symbol),
                    "qty": str(qty),
                    "price": str(price),
                    "sector": sector_name or "",
                    "portfolio_name": _portfolio_name_for_sector(sector_name if group_by_sector else None),
                }
            )

        tentative_counts: dict[str, int] = {}
        existing_lookup: dict[str, Portfolio] = {}
        existing_by_id: dict[int, Portfolio] = {}
        for p in Portfolio.objects.filter(user=request.user):
            existing_by_id[p.id] = p
            for k in _portfolio_match_keys(p.name):
                existing_lookup[k] = p

        # Annotate preview rows with where they will land: existing portfolio vs newly created portfolio.
        for item in resolved_rows:
            raw_pname = item["portfolio_name"]
            matched = None
            for lookup_key in _portfolio_match_keys(raw_pname):
                if lookup_key in existing_lookup:
                    matched = existing_lookup[lookup_key]
                    break
            target_name = matched.name if matched is not None else raw_pname
            item["portfolio_target_name"] = target_name
            item["portfolio_target_existing"] = matched is not None
            item["portfolio_target_id"] = matched.id if matched is not None else None
            tentative_counts[target_name] = tentative_counts.get(target_name, 0) + 1
        tentative_portfolios = [{"name": k, "stock_count": v} for k, v in tentative_counts.items()]

        if mode == "preview":
            return Response(
                {
                    "mode": "preview",
                    "rows_received": len(rows),
                    "rows_resolved": len(resolved_rows),
                    "rows_skipped": len(skipped),
                    "grouped_by_sector": group_by_sector,
                    "tentative_portfolios": tentative_portfolios,
                    "resolved_preview": resolved_rows[:50],
                    "skipped_preview": skipped[:50],
                },
                status=status.HTTP_200_OK,
            )

        if not resolved_rows:
            return Response(
                {
                    "detail": "No valid stock rows found in CSV. Nothing imported.",
                    "rows_received": len(rows),
                    "rows_skipped": len(skipped),
                    "skipped_preview": skipped[:50],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        created_portfolios: dict[str, Portfolio] = {}
        newly_created_portfolios: dict[str, Portfolio] = {}
        portfolio_stock_counts: dict[int, int] = {}
        processed = 0
        import_log: list[dict] = []

        with db_transaction.atomic():
            for item in resolved_rows:
                symbol = item["symbol"]
                name = item["name"]
                qty = Decimal(item["qty"])
                price = Decimal(item["price"])
                exchange_hint = item.get("exchange") or ""
                sector_name = item.get("sector") or ""
                pname = item.get("portfolio_target_name") or item["portfolio_name"]

                key = _normalize_name_key(pname)
                portfolio = created_portfolios.get(key)
                if portfolio is None:
                    # Reuse existing portfolio when name/sector matches.
                    matched = existing_by_id.get(item.get("portfolio_target_id")) if item.get("portfolio_target_id") else None
                    if matched is None:
                        for lookup_key in _portfolio_match_keys(pname):
                            if lookup_key in existing_lookup:
                                matched = existing_lookup[lookup_key]
                                break

                    if matched is not None:
                        portfolio = matched
                    else:
                        portfolio = Portfolio.objects.create(user=request.user, name=pname)
                        newly_created_portfolios[key] = portfolio
                        for k in _portfolio_match_keys(portfolio.name):
                            existing_lookup[k] = portfolio

                    created_portfolios[key] = portfolio
                    portfolio_stock_counts.setdefault(portfolio.id, 0)

                stock = _get_or_create_stock(symbol, name_hint=name, exchange_hint=exchange_hint)
                if sector_name:
                    sector_obj, _ = Sector.objects.get_or_create(name=sector_name)
                    if stock.sector_id != sector_obj.id:
                        stock.sector = sector_obj
                        stock.save(update_fields=["sector"])

                holding = Holding.objects.select_for_update().filter(portfolio=portfolio, stock=stock).first()
                if holding is None:
                    Holding.objects.create(portfolio=portfolio, stock=stock, qty=qty, avg_buy_price=price)
                    portfolio_stock_counts[portfolio.id] = (portfolio_stock_counts.get(portfolio.id, 0) + 1)
                else:
                    total_cost = (holding.avg_buy_price * holding.qty) + (price * qty)
                    new_qty = holding.qty + qty
                    holding.qty = new_qty
                    holding.avg_buy_price = (total_cost / new_qty) if new_qty else holding.avg_buy_price
                    holding.save()

                # Ensure imported stocks always enter through BUY transactions.
                Transaction.objects.create(
                    portfolio=portfolio,
                    stock=stock,
                    side="BUY",
                    qty=qty,
                    price=price,
                    realized_pnl=Decimal("0"),
                )
                processed += 1
                import_log.append(
                    {
                        "row": item.get("row"),
                        "symbol": symbol,
                        "portfolio_name": portfolio.name,
                        "status": "completed",
                    }
                )

        out_portfolios = [
            {"id": p.id, "name": p.name, "stock_count": portfolio_stock_counts.get(p.id, 0)}
            for p in newly_created_portfolios.values()
        ]

        touched_portfolios = [
            {"id": p.id, "name": p.name, "stock_count": portfolio_stock_counts.get(p.id, 0)}
            for p in created_portfolios.values()
        ]

        created_ids = [p["id"] for p in out_portfolios if p.get("id")]
        if created_ids:
            def _warm_after_commit():
                for pid in created_ids:
                    try:
                        _start_portfolio_snapshot_refresh(pid, request.user.id, fresh_seconds=45)
                    except Exception:
                        pass
                try:
                    _start_dashboard_refresh(request.user.id, fresh_seconds=45)
                except Exception:
                    pass

            db_transaction.on_commit(_warm_after_commit)

        return Response(
            {
                "mode": "import",
                "rows_received": len(rows),
                "rows_resolved": len(resolved_rows),
                "rows_processed": processed,
                "rows_skipped": len(skipped),
                "transactions_created": processed,
                "grouped_by_sector": group_by_sector,
                "created_portfolios": out_portfolios,
                "touched_portfolios": touched_portfolios,
                "import_log": import_log[:120],
                "skipped_preview": skipped[:50],
            },
            status=status.HTTP_201_CREATED,
        )


class PortfoliosRetrieveDestroyView(APIView):
    def get(self, request, portfolio_id: int):
        portfolio = Portfolio.objects.get(id=portfolio_id, user=request.user)
        force = request.query_params.get("force") == "1"
        data = warm_portfolio_snapshot_cache(portfolio=portfolio, force=force, fresh_seconds=45)
        meta = data.get("meta") or {}
        if not force and meta.get("source") == "snapshot" and meta.get("stale"):
            _start_portfolio_snapshot_refresh(portfolio.id, request.user.id, fresh_seconds=45)
        return Response(data)

    def delete(self, request, portfolio_id: int):
        portfolio = Portfolio.objects.get(id=portfolio_id, user=request.user)
        portfolio.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PortfolioRecommendationsView(APIView):
    def get(self, request, portfolio_id: int):
        portfolio = Portfolio.objects.get(id=portfolio_id, user=request.user)
        force = request.query_params.get("force") == "1"
        fresh_seconds = int(os.getenv("PORTFOLIO_RECO_CACHE_SECONDS", "180") or "180")
        cache_key = f"portfolio_reco:{request.user.id}:{portfolio.id}"
        snapshot = CachedPayload.objects.filter(key=cache_key).first()
        now = timezone.now()

        if snapshot and not force:
            age = (now - snapshot.updated_at).total_seconds()
            payload = dict(snapshot.payload or {})
            if age <= fresh_seconds:
                payload["meta"] = {
                    "source": "snapshot",
                    "age_seconds": round(age, 2),
                    "updated_at": snapshot.updated_at.isoformat(),
                }
                return Response(payload)

        holdings_qs = Holding.objects.filter(portfolio=portfolio).select_related("stock", "stock__sector")
        holdings = [
            {
                "symbol": h.stock.symbol,
                "sector": (h.stock.sector.name if h.stock.sector_id else ""),
                "qty": float(h.qty),
                "avg_buy_price": float(h.avg_buy_price),
            }
            for h in holdings_qs
        ]
        ctx = type(
            "RecoCtx",
            (),
            {
                "holdings": holdings,
                "portfolios": [{"id": portfolio.id, "name": portfolio.name, "market": portfolio.market}],
            },
        )()
        items = compute_recommendations(ctx, limit=10)
        payload = {
            "portfolio_id": portfolio.id,
            "items": items,
            "meta": {"source": "live", "generated_at": now.isoformat()},
        }
        CachedPayload.objects.update_or_create(key=cache_key, defaults={"payload": payload})
        return Response(payload)


class HoldingsListCreateView(APIView):
    def get(self, request, portfolio_id: int):
        portfolio = Portfolio.objects.get(id=portfolio_id, user=request.user)
        holdings = Holding.objects.filter(portfolio=portfolio).select_related("stock", "stock__sector").order_by("stock__symbol")
        return Response(HoldingSerializer(holdings, many=True).data)

    def post(self, request, portfolio_id: int):
        return Response(
            {"detail": "Direct holding edits are disabled. Use /transactions/ to BUY/SELL."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )


class HoldingsRetrieveUpdateDestroyView(APIView):
    def patch(self, request, portfolio_id: int, holding_id: int):
        return Response(
            {"detail": "Direct holding edits are disabled. Use /transactions/ to BUY/SELL."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def delete(self, request, portfolio_id: int, holding_id: int):
        portfolio = Portfolio.objects.get(id=portfolio_id, user=request.user)
        holding = Holding.objects.get(id=holding_id, portfolio=portfolio)
        holding.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TransactionsListCreateView(APIView):
    def get(self, request, portfolio_id: int):
        portfolio = Portfolio.objects.get(id=portfolio_id, user=request.user)
        txs = Transaction.objects.filter(portfolio=portfolio).select_related("stock", "stock__sector")
        return Response(TransactionSerializer(txs, many=True).data)

    @db_transaction.atomic
    def post(self, request, portfolio_id: int):
        portfolio = Portfolio.objects.get(id=portfolio_id, user=request.user)
        serializer = TradeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        side = serializer.validated_data["side"]
        qty: Decimal = serializer.validated_data["qty"]
        price: Decimal = serializer.validated_data["price"]

        stock = serializer.validated_data.get("stock_id")
        if stock is None:
            symbol = serializer.validated_data.get("stock_symbol", "").strip().upper()
            name = serializer.validated_data.get("stock_name", "").strip() or symbol
            if not symbol:
                return Response({"detail": "stock_symbol is required"}, status=status.HTTP_400_BAD_REQUEST)

            stock = _get_or_create_stock(symbol, name_hint=name)

        holding = Holding.objects.select_for_update().filter(portfolio=portfolio, stock=stock).first()
        if side == "SELL":
            if holding is None:
                return Response({"detail": "Cannot SELL: no holding found."}, status=status.HTTP_400_BAD_REQUEST)
            if qty > holding.qty:
                return Response(
                    {"detail": f"Cannot SELL {qty}. Available qty is {holding.qty}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            realized = (price - holding.avg_buy_price) * qty
            tx = Transaction.objects.create(
                portfolio=portfolio,
                stock=stock,
                side=side,
                qty=qty,
                price=price,
                realized_pnl=realized,
            )

            holding.qty = holding.qty - qty
            if holding.qty <= 0:
                holding.delete()
            else:
                holding.save()

            return Response(TransactionSerializer(tx).data, status=status.HTTP_201_CREATED)

        # BUY
        if holding is None:
            holding = Holding.objects.create(portfolio=portfolio, stock=stock, qty=qty, avg_buy_price=price)
        else:
            total_cost = (holding.avg_buy_price * holding.qty) + (price * qty)
            new_qty = holding.qty + qty
            holding.qty = new_qty
            holding.avg_buy_price = (total_cost / new_qty) if new_qty else holding.avg_buy_price
            holding.save()

        tx = Transaction.objects.create(
            portfolio=portfolio,
            stock=stock,
            side=side,
            qty=qty,
            price=price,
            realized_pnl=Decimal("0"),
        )
        return Response(TransactionSerializer(tx).data, status=status.HTTP_201_CREATED)


class WatchlistView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        items = WatchlistItem.objects.filter(user=request.user).select_related("stock", "stock__sector")
        data = WatchlistItemSerializer(items, many=True).data
        # enrich quotes
        for item in data:
            sym = item.get("stock", {}).get("symbol")
            last = None
            if sym:
                try:
                    last = get_fast_quote(sym).get("last_price")
                except Exception:
                    last = None
            item["last_price"] = last
        return Response(data)

    def post(self, request):
        serializer = WatchlistAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        stock = _get_or_create_stock(serializer.validated_data["stock_symbol"], serializer.validated_data.get("stock_name"))
        item, _ = WatchlistItem.objects.get_or_create(user=request.user, stock=stock)
        out = WatchlistItemSerializer(item).data
        try:
            out["last_price"] = get_fast_quote(stock.symbol).get("last_price")
        except Exception:
            out["last_price"] = None
        return Response(out, status=status.HTTP_201_CREATED)


class WatchlistItemDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, item_id: int):
        WatchlistItem.objects.filter(id=item_id, user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AlertsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        alerts = PriceAlert.objects.filter(user=request.user).select_related("stock", "stock__sector")
        data = PriceAlertSerializer(alerts, many=True).data

        # check + enrich quotes; auto-trigger if condition met
        for idx, a in enumerate(alerts):
            sym = a.stock.symbol
            last = None
            try:
                last = get_fast_quote(sym).get("last_price")
            except Exception:
                last = None

            data[idx]["last_price"] = last
            if a.is_active and last is not None and a.triggered_at is None:
                try:
                    last_d = Decimal(str(last))
                    hit = (a.direction == "ABOVE" and last_d >= a.target_price) or (a.direction == "BELOW" and last_d <= a.target_price)
                except Exception:
                    hit = False
                if hit:
                    a.is_active = False
                    from django.utils import timezone

                    a.triggered_at = timezone.now()
                    a.save(update_fields=["is_active", "triggered_at"])

        return Response(data)

    def post(self, request):
        serializer = PriceAlertCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        stock = _get_or_create_stock(serializer.validated_data["stock_symbol"], serializer.validated_data.get("stock_name"))
        alert = PriceAlert.objects.create(
            user=request.user,
            stock=stock,
            direction=serializer.validated_data["direction"],
            target_price=serializer.validated_data["target_price"],
        )
        out = PriceAlertSerializer(alert).data
        try:
            out["last_price"] = get_fast_quote(stock.symbol).get("last_price")
        except Exception:
            out["last_price"] = None
        return Response(out, status=status.HTTP_201_CREATED)


class AlertDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, alert_id: int):
        PriceAlert.objects.filter(id=alert_id, user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DashboardSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    FRESH_SECONDS = 45

    def get(self, request):
        user = request.user
        force = str(request.query_params.get("force") or "").lower() in {"1", "true", "yes"}
        cache_key = f"dashboard_summary:user:{user.id}"
        now = timezone.now()
        snapshot = CachedPayload.objects.filter(key=cache_key).first()

        if snapshot and not force:
            age_seconds = (now - snapshot.updated_at).total_seconds()
            payload = dict(snapshot.payload or {})
            payload["meta"] = {
                "source": "snapshot",
                "updated_at": snapshot.updated_at.isoformat(),
                "stale": age_seconds > self.FRESH_SECONDS,
                "age_seconds": round(age_seconds, 1),
            }
            if age_seconds > self.FRESH_SECONDS:
                _start_dashboard_refresh(user.id, self.FRESH_SECONDS)
            return Response(payload)

        payload = warm_dashboard_summary_cache(user=user, force=True, fresh_seconds=self.FRESH_SECONDS)
        return Response(payload)

class MarketSummaryView(APIView):
    permission_classes = [permissions.AllowAny]
    CACHE_KEY = "landing_market_summary"
    FRESH_SECONDS = 45

    TOP_UNIVERSE = [
        "RELIANCE.NS",
        "TCS.NS",
        "INFY.NS",
        "HDFCBANK.NS",
        "ICICIBANK.NS",
        "SBIN.NS",
        "ITC.NS",
        "LT.NS",
        "AXISBANK.NS",
        "BHARTIARTL.NS",
        "HINDUNILVR.NS",
        "MARUTI.NS",
        "SUNPHARMA.NS",
        "KOTAKBANK.NS",
        "ASIANPAINT.NS",
    ]

    def get(self, request):
        now = timezone.now()
        snapshot = CachedPayload.objects.filter(key=self.CACHE_KEY).first()

        if snapshot:
            age_seconds = (now - snapshot.updated_at).total_seconds()
            payload = dict(snapshot.payload or {})
            payload["meta"] = {
                "source": "snapshot",
                "updated_at": snapshot.updated_at.isoformat(),
                "stale": age_seconds > self.FRESH_SECONDS,
                "age_seconds": round(age_seconds, 1),
            }
            if age_seconds > self.FRESH_SECONDS:
                _start_market_refresh(self.CACHE_KEY, self.TOP_UNIVERSE)
            return Response(payload)

        payload = warm_market_summary_cache(
            cache_key=self.CACHE_KEY,
            top_universe=self.TOP_UNIVERSE,
            force=True,
            fresh_seconds=self.FRESH_SECONDS,
        )
        return Response(payload)


class MarketWarmView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        token = (os.getenv("MARKET_WARMUP_TOKEN") or "").strip()
        provided = (
            request.headers.get("X-Warmup-Token")
            or request.query_params.get("token")
            or request.data.get("token")
            or ""
        ).strip()
        if token and provided != token:
            return Response({"detail": "Invalid warmup token."}, status=status.HTTP_403_FORBIDDEN)

        force = str(request.query_params.get("force") or request.data.get("force") or "").lower() in {"1", "true", "yes"}
        payload = warm_market_summary_cache(
            cache_key=MarketSummaryView.CACHE_KEY,
            top_universe=MarketSummaryView.TOP_UNIVERSE,
            force=force,
            fresh_seconds=MarketSummaryView.FRESH_SECONDS,
        )
        return Response(
            {
                "ok": True,
                "warmed": True,
                "cache_key": MarketSummaryView.CACHE_KEY,
                "meta": payload.get("meta", {}),
            }
        )


class MetalsSummaryView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        days = int(request.query_params.get("days", "7") or 7)
        return Response(metals_summary(days=days))


class MetalsNewsView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        limit = int(request.query_params.get("limit", "6") or 6)
        return Response({"items": metals_news(limit=limit)})


class MetalsQuoteView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        ttl = int(request.query_params.get("ttl", "20") or 20)
        return Response(metals_quote_fast(ttl_seconds=ttl))


class MetalsForecastView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        horizon = (request.query_params.get("horizon", "1w") or "1w").strip().lower()
        return Response(metals_forecast(horizon=horizon))


class BtcSummaryView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        days = int(request.query_params.get("days", "30") or 30)
        return Response(btc_summary(days=days))


class BtcQuoteView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        ttl = int(request.query_params.get("ttl", "20") or 20)
        return Response(btc_quote_fast(ttl_seconds=ttl))


class BtcNewsView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        limit = int(request.query_params.get("limit", "6") or 6)
        return Response({"items": btc_news(limit=limit)})


class BtcPredictionsView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        horizon = (request.query_params.get("horizon", "1m") or "1m").strip().lower()
        return Response(btc_predictions(horizon=horizon))


class EdachiBootstrapView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        if request.user and request.user.is_authenticated:
            ctx = build_context(request.user)
            brief = build_quick_brief(ctx)
            session = get_or_init_session(request.user)
            return Response(
                {
                    "assistant_name": "EDACHI Assistant",
                    "user": {"id": request.user.id, "username": request.user.username},
                    "mode": "authenticated",
                    "summary": brief,
                    "portfolios": ctx.portfolios[:12],
                    "recent_messages": (session.get("messages") or [])[-8:],
                    "suggested_questions": [
                        "Show my portfolio list",
                        "Give me a quick portfolio summary",
                        "Portfolio sentiment summary",
                        "Add AAPL to watchlist",
                        "Create alert for INFY.NS above 1800",
                        "Latest news for INFY.NS",
                        "Recommend stocks based on my holdings",
                        "Add AAPL to watchlist",
                        "Create alert for INFY.NS above 1800"
                    ],
                }
            )

        guest_ctx = build_guest_context()
        return Response(
            {
                "assistant_name": "EDACHI Assistant",
                "mode": "guest",
                "summary": {
                    "portfolios": 0,
                    "holdings": 0,
                    "watchlist_items": 0,
                    "market_snapshot": guest_ctx.markets,
                },
                "portfolios": [],
                "recent_messages": [],
                "suggested_questions": [
                    "How do I start using PortfolioAnalyzer?",
                    "What features are available before login?",
                    "Show market snapshot for Nifty and Sensex",
                    "How do I create my first portfolio?",
                    "Latest news for AAPL",
                    "What is the price of TCS.NS?",
                    "How do I create my first portfolio?"
                ],
            }
        )


class EdachiAskView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        question = str(request.data.get("question") or "").strip()
        if not question:
            return Response({"detail": "question is required"}, status=status.HTTP_400_BAD_REQUEST)
        if len(question) > 1000:
            return Response({"detail": "question is too long (max 1000 characters)"}, status=status.HTTP_400_BAD_REQUEST)

        if request.user and request.user.is_authenticated:
            out = answer_question(request.user, question)
            out["mode"] = "authenticated"
            return Response(out)

        allowed, limit_meta = _edachi_guest_limit(request)
        if not allowed:
            return Response(
                {
                    "detail": "Guest chat limit reached. Please wait or login for a higher limit.",
                    "limits": limit_meta,
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        recent_messages = request.data.get("recent_messages")
        if not isinstance(recent_messages, list):
            recent_messages = []
        out = answer_public_question(question, recent_messages=recent_messages[-6:])
        out = answer_public_question(question, recent_messages=recent_messages[-8:], client_id=_client_ip(request))
        out["mode"] = "guest"
        out["limits"] = limit_meta
        return Response(out)


class EdachiSessionResetView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        if request.user and request.user.is_authenticated:
            clear_session(request.user)
            return Response({"ok": True, "detail": "Session cleared", "mode": "authenticated"})
        return Response({"ok": True, "detail": "Guest chat cleared", "mode": "guest"})


class EdachiFeedbackView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        helpful = request.data.get("helpful")
        if not isinstance(helpful, bool):
            return Response({"detail": "helpful (boolean) is required"}, status=status.HTTP_400_BAD_REQUEST)

        question = str(request.data.get("question") or "").strip()
        answer = str(request.data.get("answer") or "").strip()
        source = str(request.data.get("source") or "").strip()
        if not question or not answer:
            return Response({"detail": "question and answer are required"}, status=status.HTTP_400_BAD_REQUEST)

        if request.user and request.user.is_authenticated:
            save_feedback(request.user, question=question[:500], answer=answer[:1500], helpful=helpful, source=source[:40])
            return Response({"ok": True, "mode": "authenticated"})

        client_id = _client_ip(request)
        save_guest_feedback(client_id=client_id, question=question[:500], answer=answer[:1500], helpful=helpful, source=source[:40])
        return Response({"ok": True, "mode": "guest"})


class EdachiMarketIntelToolView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        question = str(request.data.get("question") or "").strip()
        symbol = str(request.data.get("symbol") or "").strip()
        if not question and not symbol:
            return Response({"detail": "question or symbol is required"}, status=status.HTTP_400_BAD_REQUEST)
        merged_q = question or f"latest market update for {symbol}"
        if symbol and symbol.upper() not in merged_q.upper():
            merged_q = f"{merged_q} {symbol}"

        if request.user and request.user.is_authenticated:
            ctx = build_context(request.user)
            payload = build_market_intel(question=merged_q, user=request.user, ctx=ctx, include_recommendations=True)
            return Response({"ok": True, "mode": "authenticated", "data": payload})

        payload = build_market_intel(question=merged_q, user=None, ctx=None, include_recommendations=False)
        return Response({"ok": True, "mode": "guest", "data": payload})


class EdachiObservabilityView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not request.user.is_staff:
            return Response({"detail": "Admin access required"}, status=status.HTTP_403_FORBIDDEN)
        return Response(chat_observability_dashboard())


class EdachiNightlyLearningView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not request.user.is_staff:
            return Response({"detail": "Admin access required"}, status=status.HTTP_403_FORBIDDEN)
        min_helpful = int(request.data.get("min_helpful") or 1)
        max_items = int(request.data.get("max_items") or 800)
        return Response(curate_chat_memory(min_helpful=min_helpful, max_items=max_items))
