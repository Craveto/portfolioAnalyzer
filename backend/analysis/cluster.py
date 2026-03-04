from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np

from api.yf_client import get_52w_range, get_fast_quote, get_fundamentals


@dataclass(frozen=True)
class ClusterItem:
    portfolio_id: int
    portfolio_name: str
    symbol: str
    name: str
    sector: Optional[str]
    qty: Decimal
    avg_buy_price: Decimal
    last_price: Optional[float]
    market_value: Optional[Decimal]
    pe: Optional[float]
    low_52w: Optional[float]
    high_52w: Optional[float]
    discount_from_52w_high_pct: Optional[float]
    position_in_52w_range_pct: Optional[float]


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def build_cluster_items(holdings) -> List[ClusterItem]:
    """
    Build per-holding feature rows (best-effort from yfinance).

    Intended for day-1 demo clustering:
    - Uses lightweight metrics already used elsewhere: last price, P/E, 52W range.
    - Keeps it explainable; not financial advice.
    """
    out: List[ClusterItem] = []
    for h in holdings:
        sym = h.stock.symbol
        q = get_fast_quote(sym)
        last = q.get("last_price")
        last_f = _to_float(last)
        last_dec = Decimal(str(last_f)) if last_f is not None else None
        mv = (last_dec * h.qty) if last_dec is not None else None

        f = get_fundamentals(sym)
        pe = f.get("trailingPE") or f.get("forwardPE")
        pe_f = _to_float(pe)

        r52w = get_52w_range(sym)
        low_52w = _to_float(r52w.get("low_52w"))
        high_52w = _to_float(r52w.get("high_52w"))

        discount_from_high_pct = None
        position_in_range_pct = None
        try:
            if last_f is not None and high_52w:
                discount_from_high_pct = float(((Decimal(str(high_52w)) - Decimal(str(last_f))) / Decimal(str(high_52w))) * 100)
            if (
                last_f is not None
                and low_52w is not None
                and high_52w is not None
                and float(high_52w) != float(low_52w)
            ):
                position_in_range_pct = float(
                    ((Decimal(str(last_f)) - Decimal(str(low_52w))) / (Decimal(str(high_52w)) - Decimal(str(low_52w)))) * 100
                )
        except Exception:
            discount_from_high_pct = None
            position_in_range_pct = None

        out.append(
            ClusterItem(
                portfolio_id=h.portfolio_id,
                portfolio_name=getattr(h.portfolio, "name", ""),
                symbol=sym,
                name=h.stock.name,
                sector=getattr(getattr(h.stock, "sector", None), "name", None),
                qty=h.qty,
                avg_buy_price=h.avg_buy_price,
                last_price=last_f,
                market_value=mv,
                pe=pe_f,
                low_52w=low_52w,
                high_52w=high_52w,
                discount_from_52w_high_pct=discount_from_high_pct,
                position_in_52w_range_pct=position_in_range_pct,
            )
        )
    return out


def _feature_matrix(items: Sequence[ClusterItem]) -> Tuple[np.ndarray, List[str]]:
    """
    Create an (n, d) numeric matrix for clustering.

    Features (explainable + available):
    - log1p(last_price)
    - pe (clipped)
    - discount_from_52w_high_pct
    - position_in_52w_range_pct
    """
    cols = ["log_last", "pe", "discount", "position"]
    rows: List[List[float]] = []
    for it in items:
        last = it.last_price
        pe = it.pe
        disc = it.discount_from_52w_high_pct
        pos = it.position_in_52w_range_pct

        # Convert to floats; keep NaNs for missing
        log_last = np.log1p(last) if last is not None and last > 0 else np.nan
        pe_v = float(pe) if pe is not None else np.nan
        if np.isfinite(pe_v):
            pe_v = float(np.clip(pe_v, 0, 200))  # avoid outliers exploding the scale
        disc_v = float(disc) if disc is not None else np.nan
        pos_v = float(pos) if pos is not None else np.nan

        rows.append([log_last, pe_v, disc_v, pos_v])

    X = np.array(rows, dtype=float)
    # Fill NaNs with column median (or 0 if all missing)
    for j in range(X.shape[1]):
        col = X[:, j]
        if np.all(~np.isfinite(col)):
            X[:, j] = 0.0
            continue
        med = np.nanmedian(col)
        col[np.isnan(col)] = med
        X[:, j] = col

    # Standardize
    mu = X.mean(axis=0)
    sigma = X.std(axis=0)
    sigma[sigma == 0] = 1.0
    X = (X - mu) / sigma
    return X, cols


def kmeans_labels(X: np.ndarray, k: int, seed: int = 42, max_iter: int = 25) -> Tuple[np.ndarray, np.ndarray]:
    """
    Tiny, dependency-free k-means (numpy only).
    Returns (labels, centroids).
    """
    n = int(X.shape[0])
    if n == 0:
        return np.array([], dtype=int), np.zeros((0, X.shape[1]), dtype=float)

    k = int(max(1, min(int(k), n)))
    rng = np.random.default_rng(seed)

    # init: choose k distinct points
    init_idx = rng.choice(n, size=k, replace=False)
    C = X[init_idx].copy()
    labels = np.zeros((n,), dtype=int)

    for _ in range(max_iter):
        # assign
        d2 = ((X[:, None, :] - C[None, :, :]) ** 2).sum(axis=2)
        new_labels = d2.argmin(axis=1).astype(int)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels

        # update
        for ci in range(k):
            mask = labels == ci
            if not np.any(mask):
                C[ci] = X[rng.integers(0, n)]
            else:
                C[ci] = X[mask].mean(axis=0)

    return labels, C


def cluster_items(items: Sequence[ClusterItem], k: int = 3, seed: int = 42) -> Tuple[List[dict], List[str]]:
    """
    Cluster items and return a JSON-friendly cluster list.
    """
    X, feature_names = _feature_matrix(items)
    labels, _centroids = kmeans_labels(X, k=k, seed=seed)

    clusters: List[dict] = []
    if len(items) == 0:
        return clusters, feature_names

    k_eff = int(labels.max()) + 1 if labels.size else 0
    for cid in range(k_eff):
        idx = np.where(labels == cid)[0].tolist()
        members = [items[i] for i in idx]

        def avg(getter):
            vals = [getter(m) for m in members]
            vals = [v for v in vals if v is not None]
            if not vals:
                return None
            return float(np.mean(vals))

        clusters.append(
            {
                "id": cid,
                "size": len(members),
                "avg_last_price": avg(lambda m: m.last_price),
                "avg_pe": avg(lambda m: m.pe),
                "avg_discount_pct": avg(lambda m: m.discount_from_52w_high_pct),
                "avg_position_pct": avg(lambda m: m.position_in_52w_range_pct),
                "items": [
                    {
                        "portfolio_id": m.portfolio_id,
                        "portfolio_name": m.portfolio_name,
                        "symbol": m.symbol,
                        "name": m.name,
                        "sector": m.sector,
                        "qty": str(m.qty),
                        "avg_buy_price": str(m.avg_buy_price),
                        "last_price": m.last_price,
                        "market_value": str(m.market_value) if m.market_value is not None else None,
                        "pe": m.pe,
                        "low_52w": m.low_52w,
                        "high_52w": m.high_52w,
                        "discount_from_52w_high_pct": m.discount_from_52w_high_pct,
                        "position_in_52w_range_pct": m.position_in_52w_range_pct,
                    }
                    for m in members
                ],
            }
        )

    # stable ordering: bigger clusters first, then id
    clusters.sort(key=lambda c: (-c["size"], c["id"]))
    return clusters, feature_names

