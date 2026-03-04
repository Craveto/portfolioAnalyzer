from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db import transaction as db_transaction
from django.db.models import Q
from rest_framework import permissions, status
from rest_framework.authtoken.models import Token
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserProfile
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
from .yf_client import download_daily, get_52w_range, get_fast_quote, get_fundamentals, search_indian_equities


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
        data = PortfolioSerializer(portfolio).data
        holdings = Holding.objects.filter(portfolio=portfolio).select_related("stock", "stock__sector").order_by("stock__symbol")
        holdings_data = HoldingSerializer(holdings, many=True).data

        realized_total = Transaction.objects.filter(portfolio=portfolio, side="SELL").values_list("realized_pnl", flat=True)
        try:
            data["realized_pnl_total"] = str(sum((Decimal(str(x)) for x in realized_total), Decimal("0")))
        except Exception:
            data["realized_pnl_total"] = "0"

        # Best-effort live quote enrichment (cached).
        symbols = [h.stock.symbol for h in holdings]
        quotes = {}
        for s in symbols:
            try:
                quotes[s] = get_fast_quote(s)
            except Exception:
                quotes[s] = {"ticker": s, "last_price": None}

        for item in holdings_data:
            symbol = item.get("stock", {}).get("symbol")
            last_price = None
            if symbol and symbol in quotes:
                last_price = quotes[symbol].get("last_price")
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

    def get(self, request):
        user = request.user

        portfolios = Portfolio.objects.filter(user=user).order_by("-created_at")
        portfolio_ids = list(portfolios.values_list("id", flat=True))

        holdings_qs = Holding.objects.filter(portfolio_id__in=portfolio_ids).select_related("stock")
        holdings_count = holdings_qs.count()

        realized_total = Transaction.objects.filter(portfolio_id__in=portfolio_ids, side="SELL").values_list("realized_pnl", flat=True)
        try:
            realized_pnl_total = str(sum((Decimal(str(x)) for x in realized_total), Decimal("0")))
        except Exception:
            realized_pnl_total = "0"

        # Watchlist + alerts
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
                "executed_at": t.executed_at,
            }
            for t in recent_txs
        ]

        # Profile preferences (for quick actions)
        profile, _ = UserProfile.objects.get_or_create(user=user)
        default_portfolio = None
        if profile.default_portfolio_id:
            default_portfolio = {"id": profile.default_portfolio_id, "name": profile.default_portfolio.name}

        # Market cards
        nifty = get_fast_quote("^NSEI")
        sensex = get_fast_quote("^BSESN")

        return Response(
            {
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
                "portfolios": [{"id": p.id, "name": p.name, "market": p.market, "created_at": p.created_at} for p in portfolios[:20]],
                "watchlist_preview": watchlist_preview,
                "recent_transactions": recent,
                "market": {"nifty": nifty, "sensex": sensex},
            }
        )

class MarketSummaryView(APIView):
    permission_classes = [permissions.AllowAny]

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
        # Indices (Yahoo Finance)
        nifty = get_fast_quote("^NSEI")
        sensex = get_fast_quote("^BSESN")

        # "Top 10" for demo: pick biggest % movers from a fixed liquid universe.
        df = download_daily(self.TOP_UNIVERSE, days=5)
        movers = []
        for symbol in self.TOP_UNIVERSE:
            try:
                hist = df[symbol] if symbol in df.columns.get_level_values(0) else None
                if hist is None or hist.empty:
                    continue
                last = float(hist["Close"].dropna().iloc[-1])
                prev = float(hist["Close"].dropna().iloc[-2]) if len(hist["Close"].dropna()) >= 2 else last
                chg_pct = ((last - prev) / prev) * 100 if prev else 0.0
                movers.append({"symbol": symbol, "last": last, "changePct": chg_pct})
            except Exception:
                continue

        movers.sort(key=lambda x: abs(x["changePct"]), reverse=True)
        top10 = movers[:10]

        return Response(
            {
                "indices": {"nifty": nifty, "sensex": sensex},
                "top10": top10,
                "note": "Top10 is computed from a fixed Nifty-like universe for Day-1 demo.",
            }
        )
