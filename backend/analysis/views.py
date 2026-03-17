from __future__ import annotations

from decimal import Decimal
import csv
import threading

from django.shortcuts import get_object_or_404
from datetime import timedelta

from django.http import HttpResponse
from django.db import close_old_connections
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import CachedPayload
from portfolio.models import Holding, Portfolio

from api.yf_client import get_52w_range, get_fast_quote, get_fundamentals, history_daily
from .cluster import build_cluster_items, cluster_items


_refresh_flags: dict[str, bool] = {}
_refresh_lock = threading.Lock()


def _compute_portfolio_pe_payload(portfolio: Portfolio) -> dict:
    holdings = (
        Holding.objects.filter(portfolio=portfolio)
        .select_related("stock")
        .order_by("stock__symbol")
    )

    items = []
    total_mv = Decimal("0")
    for h in holdings:
        q = get_fast_quote(h.stock.symbol)
        last = q.get("last_price")
        last_dec = Decimal(str(last)) if last is not None else None
        mv = (last_dec * h.qty) if last_dec is not None else None
        if mv is not None:
            total_mv += mv

        f = get_fundamentals(h.stock.symbol)
        pe = f.get("trailingPE") or f.get("forwardPE")

        r52w = get_52w_range(h.stock.symbol)
        low_52w = r52w.get("low_52w")
        high_52w = r52w.get("high_52w")
        discount_from_high_pct = None
        position_in_range_pct = None
        try:
            if last is not None and high_52w:
                discount_from_high_pct = float(((Decimal(str(high_52w)) - Decimal(str(last))) / Decimal(str(high_52w))) * 100)
            if last is not None and low_52w is not None and high_52w is not None and float(high_52w) != float(low_52w):
                position_in_range_pct = float(
                    ((Decimal(str(last)) - Decimal(str(low_52w))) / (Decimal(str(high_52w)) - Decimal(str(low_52w)))) * 100
                )
        except Exception:
            discount_from_high_pct = None
            position_in_range_pct = None

        items.append(
            {
                "symbol": h.stock.symbol,
                "name": h.stock.name,
                "qty": str(h.qty),
                "last_price": float(last) if last is not None else None,
                "market_value": str(mv) if mv is not None else None,
                "pe": float(pe) if pe is not None else None,
                "low_52w": float(low_52w) if low_52w is not None else None,
                "high_52w": float(high_52w) if high_52w is not None else None,
                "discount_from_52w_high_pct": discount_from_high_pct,
                "position_in_52w_range_pct": position_in_range_pct,
            }
        )

    for item in items:
        mv = item["market_value"]
        if mv is None or total_mv == 0:
            item["weight"] = None
        else:
            try:
                item["weight"] = float(Decimal(mv) / total_mv)
            except Exception:
                item["weight"] = None

    pe_weighted_sum = Decimal("0")
    pe_weight_sum = Decimal("0")
    for item in items:
        if item["pe"] is None or item["market_value"] is None or total_mv == 0:
            continue
        try:
            w = Decimal(item["market_value"]) / total_mv
            pe_weighted_sum += Decimal(str(item["pe"])) * w
            pe_weight_sum += w
        except Exception:
            continue

    portfolio_pe = None
    if pe_weight_sum != 0:
        portfolio_pe = float(pe_weighted_sum / pe_weight_sum)

    return {
        "portfolio": {"id": portfolio.id, "name": portfolio.name},
        "total_market_value": str(total_mv),
        "portfolio_pe_weighted": portfolio_pe,
        "holdings": items,
    }


def warm_portfolio_pe_cache(portfolio: Portfolio, force: bool = False, fresh_seconds: int = 180) -> dict:
    now = timezone.now()
    cache_key = f"portfolio_pe:{portfolio.id}"
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
        payload = _compute_portfolio_pe_payload(portfolio)
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


def _refresh_cached_portfolio_pe(portfolio_id: int, user_id: int, fresh_seconds: int = 180) -> None:
    close_old_connections()
    try:
        portfolio = Portfolio.objects.filter(id=portfolio_id, user_id=user_id).first()
        if portfolio:
            warm_portfolio_pe_cache(portfolio=portfolio, force=True, fresh_seconds=fresh_seconds)
    except Exception:
        pass
    finally:
        cache_key = f"portfolio_pe:{portfolio_id}"
        with _refresh_lock:
            _refresh_flags[cache_key] = False
        close_old_connections()


def _start_portfolio_pe_refresh(portfolio_id: int, user_id: int, fresh_seconds: int = 180) -> None:
    cache_key = f"portfolio_pe:{portfolio_id}"
    with _refresh_lock:
        if _refresh_flags.get(cache_key):
            return
        _refresh_flags[cache_key] = True
    t = threading.Thread(target=_refresh_cached_portfolio_pe, args=(portfolio_id, user_id, fresh_seconds), daemon=True)
    t.start()


class PortfolioPEView(APIView):
    """
    Day-1 analysis module endpoint:
    - Returns current P/E per holding (best-effort from yfinance)
    - Includes market value + weights to support charts later
    """

    def get(self, request, portfolio_id: int):
        portfolio = get_object_or_404(Portfolio, id=portfolio_id, user=request.user)
        force = request.query_params.get("force") == "1"
        payload = warm_portfolio_pe_cache(portfolio=portfolio, force=force, fresh_seconds=180)
        meta = payload.get("meta") or {}
        if meta.get("source") == "snapshot" and meta.get("age_seconds") and meta.get("age_seconds", 0) > 180:
            _start_portfolio_pe_refresh(portfolio.id, request.user.id, fresh_seconds=180)
        return Response(payload, status=status.HTTP_200_OK)


class PortfolioForecastView(APIView):
    """
    Educational forecast for portfolio value.

    Method (simple + explainable):
    - Fetch daily close prices via yfinance
    - Estimate mean daily log return (last ~180 trading days)
    - Forecast expected price path: P(t) = P0 * exp(mu * t)

    Not financial advice; for EDA/demo only.
    """

    def get(self, request, portfolio_id: int):
        portfolio = get_object_or_404(Portfolio, id=portfolio_id, user=request.user)
        days = int(request.query_params.get("days", "90") or 90)
        days = max(7, min(365, days))

        holdings = Holding.objects.filter(portfolio=portfolio).select_related("stock").order_by("stock__symbol")
        if not holdings.exists():
            return Response(
                {"portfolio": {"id": portfolio.id, "name": portfolio.name}, "days": days, "series": [], "holdings": []},
                status=status.HTTP_200_OK,
            )

        # Build forecast per holding and combine by qty (portfolio value).
        now = timezone.localdate()
        horizon = [now + timedelta(days=i) for i in range(days + 1)]

        portfolio_series = [Decimal("0") for _ in horizon]
        holding_out = []

        for h in holdings:
            sym = h.stock.symbol
            try:
                df = history_daily(sym, period="2y")
            except Exception:
                df = None

            mu = None
            last_close = None
            try:
                if df is not None and not df.empty and "Close" in df.columns:
                    closes = df["Close"].dropna().tail(200)
                    if len(closes) >= 30:
                        last_close = Decimal(str(float(closes.iloc[-1])))
                        # log returns
                        import numpy as np

                        lr = np.log(closes / closes.shift(1)).dropna().tail(180)
                        if len(lr) >= 30:
                            mu = float(lr.mean())
            except Exception:
                mu = None
                last_close = None

            if last_close is None:
                try:
                    q = get_fast_quote(sym)
                    lp = q.get("last_price")
                    if lp is not None:
                        last_close = Decimal(str(lp))
                except Exception:
                    last_close = None

            if last_close is None:
                continue

            # Default mu=0 if can't estimate
            mu = mu if mu is not None else 0.0

            series = []
            for i, d in enumerate(horizon):
                # expected price path
                try:
                    import math

                    price = Decimal(str(float(last_close) * math.exp(mu * i)))
                except Exception:
                    price = last_close
                value = price * h.qty
                portfolio_series[i] += value
                series.append({"date": d.isoformat(), "price": float(price), "value": float(value)})

            holding_out.append(
                {
                    "symbol": sym,
                    "name": h.stock.name,
                    "qty": str(h.qty),
                    "mu_daily": mu,
                    "start_price": float(last_close),
                    "series": series,
                }
            )

        out_series = [{"date": horizon[i].isoformat(), "portfolio_value": float(portfolio_series[i])} for i in range(len(horizon))]

        return Response(
            {
                "portfolio": {"id": portfolio.id, "name": portfolio.name},
                "days": days,
                "series": out_series,
                "holdings": holding_out,
                "disclaimer": "Educational forecast using simple historical-return model. Not investment advice.",
            },
            status=status.HTTP_200_OK,
        )


class ClusterView(APIView):
    """
    Day-1 clustering endpoint (numpy-only k-means):
    - Input: portfolio_ids=1,2,3 and optional k=3
    - Output: clusters of holdings with simple explainable metrics (P/E, discount, position in 52W range)
    """

    def get(self, request):
        raw = request.query_params.get("portfolio_ids") or ""
        ids = []
        for part in raw.split(","):
            part = (part or "").strip()
            if not part:
                continue
            try:
                ids.append(int(part))
            except Exception:
                continue
        ids = sorted(set(ids))
        if not ids:
            return Response({"detail": "portfolio_ids is required (comma-separated)."}, status=status.HTTP_400_BAD_REQUEST)

        k = int(request.query_params.get("k", "3") or 3)
        k = max(2, min(8, k))

        portfolios = list(Portfolio.objects.filter(user=request.user, id__in=ids).order_by("id"))
        if not portfolios:
            return Response({"detail": "No portfolios found."}, status=status.HTTP_404_NOT_FOUND)

        holdings = (
            Holding.objects.filter(portfolio__in=portfolios)
            .select_related("portfolio", "stock", "stock__sector")
            .order_by("portfolio_id", "stock__symbol")
        )

        items = build_cluster_items(holdings)
        clusters, feature_names = cluster_items(items, k=k)

        return Response(
            {
                "k": k,
                "features": feature_names,
                "portfolios": [{"id": p.id, "name": p.name} for p in portfolios],
                "clusters": clusters,
                "disclaimer": "Educational clustering using simple metrics (P/E, discount, 52W position). Not investment advice.",
            },
            status=status.HTTP_200_OK,
        )


class ClusterCSVView(APIView):
    """
    Download clustering results as CSV.
    """

    def get(self, request):
        raw = request.query_params.get("portfolio_ids") or ""
        ids = []
        for part in raw.split(","):
            part = (part or "").strip()
            if not part:
                continue
            try:
                ids.append(int(part))
            except Exception:
                continue
        ids = sorted(set(ids))
        if not ids:
            return Response({"detail": "portfolio_ids is required (comma-separated)."}, status=status.HTTP_400_BAD_REQUEST)

        k = int(request.query_params.get("k", "3") or 3)
        k = max(2, min(8, k))

        portfolios = list(Portfolio.objects.filter(user=request.user, id__in=ids).order_by("id"))
        if not portfolios:
            return Response({"detail": "No portfolios found."}, status=status.HTTP_404_NOT_FOUND)

        holdings = (
            Holding.objects.filter(portfolio__in=portfolios)
            .select_related("portfolio", "stock", "stock__sector")
            .order_by("portfolio_id", "stock__symbol")
        )
        items = build_cluster_items(holdings)
        clusters, _feature_names = cluster_items(items, k=k)

        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="clusters.csv"'
        w = csv.writer(resp)
        w.writerow(
            [
                "cluster_id",
                "portfolio_id",
                "portfolio_name",
                "symbol",
                "name",
                "sector",
                "qty",
                "avg_buy_price",
                "last_price",
                "market_value",
                "pe",
                "low_52w",
                "high_52w",
                "discount_from_52w_high_pct",
                "position_in_52w_range_pct",
            ]
        )

        for c in clusters:
            cid = c.get("id")
            for it in c.get("items") or []:
                w.writerow(
                    [
                        cid,
                        it.get("portfolio_id"),
                        it.get("portfolio_name"),
                        it.get("symbol"),
                        it.get("name"),
                        it.get("sector"),
                        it.get("qty"),
                        it.get("avg_buy_price"),
                        it.get("last_price"),
                        it.get("market_value"),
                        it.get("pe"),
                        it.get("low_52w"),
                        it.get("high_52w"),
                        it.get("discount_from_52w_high_pct"),
                        it.get("position_in_52w_range_pct"),
                    ]
                )

        return resp
