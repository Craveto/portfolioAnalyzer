from __future__ import annotations

import os
import threading
from decimal import Decimal

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
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
from portfolio.models import Holding, Portfolio, Stock, Transaction
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
    search_indian_equities,
)


_refresh_flags: dict[str, bool] = {}
_refresh_lock = threading.Lock()


def _get_or_create_stock(symbol: str, name_hint: str | None = None) -> Stock:
    symbol = (symbol or "").strip().upper()
    name_hint = (name_hint or "").strip()
    exchange = "NSE" if symbol.endswith(".NS") else ("BSE" if symbol.endswith(".BO") else "NSE")
    stock, created = Stock.objects.get_or_create(
        symbol=symbol,
        defaults={"name": name_hint or symbol, "exchange": exchange},
    )
    if not created and name_hint and stock.name != name_hint:
        stock.name = name_hint
        stock.exchange = exchange
        stock.save(update_fields=["name", "exchange"])
    return stock


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
    for symbol in symbols:
        try:
            quotes[symbol] = get_fast_quote(symbol)
        except Exception:
            quotes[symbol] = {"ticker": symbol, "last_price": None}

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
            live = search_indian_equities(q, max_results=25)
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


class PortfoliosRetrieveDestroyView(APIView):
    def get(self, request, portfolio_id: int):
        portfolio = Portfolio.objects.get(id=portfolio_id, user=request.user)
        force = request.query_params.get("force") == "1"
        data = warm_portfolio_snapshot_cache(portfolio=portfolio, force=force, fresh_seconds=45)
        meta = data.get("meta") or {}
        if meta.get("source") == "snapshot" and meta.get("age_seconds") and meta.get("age_seconds", 0) > 45:
            _start_portfolio_snapshot_refresh(portfolio.id, request.user.id, fresh_seconds=45)
        return Response(data)

    def delete(self, request, portfolio_id: int):
        portfolio = Portfolio.objects.get(id=portfolio_id, user=request.user)
        portfolio.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


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
