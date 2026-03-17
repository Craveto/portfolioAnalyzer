import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, clearTokens } from "../api.js";
import LineChart from "../components/LineChart.jsx";
import ScatterPlot from "../components/ScatterPlot.jsx";
import Popover from "../components/Popover.jsx";
import NavBar from "../components/NavBar.jsx";
import Footer from "../components/Footer.jsx";

function toNum(v) {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function fmt(n) {
  if (n === null || n === undefined) return "--";
  const num = Number(n);
  if (Number.isNaN(num)) return "--";
  return num.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function round2(n) {
  const num = Number(n);
  if (!Number.isFinite(num)) return null;
  return Math.round(num * 100) / 100;
}

function loadRecent() {
  try {
    const raw = localStorage.getItem("recentSymbols");
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function saveRecent(symbol) {
  if (!symbol) return;
  const prev = loadRecent().filter((s) => s !== symbol);
  const next = [symbol, ...prev].slice(0, 6);
  try {
    localStorage.setItem("recentSymbols", JSON.stringify(next));
  } catch {}
}

function portfolioCacheKey(portfolioId) {
  return `portfolioPage:${portfolioId}`;
}

function readPortfolioCache(portfolioId) {
  try {
    const raw = localStorage.getItem(portfolioCacheKey(portfolioId));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

function writePortfolioCache(portfolioId, payload) {
  try {
    localStorage.setItem(portfolioCacheKey(portfolioId), JSON.stringify({ ...payload, cachedAt: Date.now() }));
  } catch {}
}

export default function Portfolio() {
  const { id } = useParams();
  const portfolioId = Number(id);
  const nav = useNavigate();
  const tradeSearchRef = useRef(null);

  const [portfolio, setPortfolio] = useState(null);
  const [holdings, setHoldings] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [q, setQ] = useState("");
  const [stockResults, setStockResults] = useState([]);
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [selectedName, setSelectedName] = useState("");
  const [recentSymbols, setRecentSymbols] = useState(loadRecent());
  const [side, setSide] = useState("BUY");
  const [qty, setQty] = useState("1");
  const [price, setPrice] = useState("0");
  const [error, setError] = useState("");
  const [quoteBusy, setQuoteBusy] = useState(false);
  const [activeBottomTab, setActiveBottomTab] = useState("transactions"); // transactions | pe | discount | forecast | cluster
  const [selectedHoldingSymbol, setSelectedHoldingSymbol] = useState("");
  const [stockDetail, setStockDetail] = useState(null);
  const [stockDetailBusy, setStockDetailBusy] = useState(false);
  const [tradeOpen, setTradeOpen] = useState(false);
  const [holdingMetricsBySymbol, setHoldingMetricsBySymbol] = useState({});
  const [searchPreviewBySymbol, setSearchPreviewBySymbol] = useState({});
  const [searchPreviewBusy, setSearchPreviewBusy] = useState(false);
  const [activeSearchIdx, setActiveSearchIdx] = useState(0);

  const [clusterOpen, setClusterOpen] = useState(false);
  const clusterAnchorRef = useRef(null);
  const clusterSelectAnchorRef = useRef(null);
  const [allPortfolios, setAllPortfolios] = useState([]);
  const [clusterPortfolioIds, setClusterPortfolioIds] = useState([portfolioId]);
  const [clusterK, setClusterK] = useState(3);
  const [clusterData, setClusterData] = useState(null);
  const [clusterBusy, setClusterBusy] = useState(false);
  const [clusterError, setClusterError] = useState("");

  useEffect(() => {
    setClusterPortfolioIds((prev) => {
      if (Array.isArray(prev) && prev.length) return prev;
      return [portfolioId];
    });
  }, [portfolioId]);

  async function refresh(force = false) {
    const isAuthErr = (e) => {
      const msg = String(e?.message || "");
      return msg.includes("HTTP 401") || msg.includes("HTTP 403");
    };

    const portfolioPromise = api.getPortfolio(portfolioId, force);
    const transactionsPromise = api.listTransactions(portfolioId);
    const metricsPromise = api
      .portfolioPE(portfolioId, force)
      .then((d) => d)
      .catch((e) => {
        if (isAuthErr(e)) throw e;
        return null;
      });

    const [data, txs, metrics] = await Promise.all([portfolioPromise, transactionsPromise, metricsPromise]);
    setPortfolio(data);
    setHoldings(data.holdings || []);
    setTransactions(txs || []);

    const nextMetrics = {};
    const items = metrics?.holdings || [];
    for (const item of items) {
      if (item?.symbol) nextMetrics[String(item.symbol)] = item;
    }
    setHoldingMetricsBySymbol(nextMetrics);
    writePortfolioCache(portfolioId, {
      portfolio: data,
      holdings: data.holdings || [],
      transactions: txs || [],
      holdingMetricsBySymbol: nextMetrics
    });

    if (!force && (data?.meta?.stale || metrics?.meta?.stale)) {
      window.setTimeout(() => {
        refresh(true).catch(() => {});
      }, 0);
    }
  }

  useEffect(() => {
    const cached = readPortfolioCache(portfolioId);
    if (cached) {
      if (cached.portfolio) setPortfolio(cached.portfolio);
      if (Array.isArray(cached.holdings)) setHoldings(cached.holdings);
      if (Array.isArray(cached.transactions)) setTransactions(cached.transactions);
      if (cached.holdingMetricsBySymbol && typeof cached.holdingMetricsBySymbol === "object") {
        setHoldingMetricsBySymbol(cached.holdingMetricsBySymbol);
      }
    }
    refresh().catch(() => {
      clearTokens();
      nav("/");
    });
  }, [portfolioId, nav]);

  useEffect(() => {
    if (!q.trim()) {
      setStockResults([]);
      setSearchPreviewBySymbol({});
      return;
    }
    const t = setTimeout(() => {
      api
        .searchStocksLive(q.trim())
        .then((data) => setStockResults(data))
        .catch(() => setStockResults([]));
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const top = (stockResults || []).slice(0, 8).map((s) => String(s.symbol)).filter(Boolean);
    if (!top.length) {
      setSearchPreviewBySymbol({});
      setSearchPreviewBusy(false);
      return;
    }
    let alive = true;
    setSearchPreviewBusy(true);
    api
      .stocksPreview(top)
      .then((items) => {
        if (!alive) return;
        const next = {};
        for (const it of items || []) {
          if (it?.symbol) next[String(it.symbol)] = it;
        }
        setSearchPreviewBySymbol(next);
        setSearchPreviewBusy(false);
      })
      .catch(() => {
        if (!alive) return;
        setSearchPreviewBySymbol({});
        setSearchPreviewBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [stockResults]);

  useEffect(() => {
    setActiveSearchIdx(0);
  }, [q, stockResults.length]);

  const selected = useMemo(() => stockResults.find((s) => String(s.symbol) === String(selectedSymbol)), [stockResults, selectedSymbol]);
  const selectedPreview = useMemo(() => searchPreviewBySymbol[String(selectedSymbol || "")] || null, [searchPreviewBySymbol, selectedSymbol]);

  useEffect(() => {
    if (!selectedSymbol) return;
    let alive = true;
    setQuoteBusy(true);
    api
      .quote(selectedSymbol)
      .then((q) => {
        if (!alive) return;
        const lp = q?.last_price;
        const r = round2(lp);
        if (r !== null) setPrice(r.toFixed(2));
      })
      .catch(() => {})
      .finally(() => {
        if (!alive) return;
        setQuoteBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [selectedSymbol]);

  useEffect(() => {
    if (!tradeOpen) return;
    const onKeyDown = (e) => {
      if (e.key === "Escape") setTradeOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    const t = setTimeout(() => tradeSearchRef.current?.focus?.(), 0);
    return () => {
      clearTimeout(t);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [tradeOpen]);

  useEffect(() => {
    if (!selectedHoldingSymbol) return;
    const onKeyDown = (e) => {
      if (e.key === "Escape") closeStockDetail();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedHoldingSymbol]);

  async function placeTrade() {
    setError("");
    try {
      if (!selectedSymbol) throw new Error("Select a stock");
      const qtyNum = Number(qty);
      const priceNum = Number(price);
      if (!Number.isFinite(qtyNum) || qtyNum <= 0) throw new Error("Qty must be a number > 0");
      if (!Number.isFinite(priceNum) || priceNum <= 0) throw new Error("Trade price must be a number > 0 (no commas)");
      await api.createTransaction(portfolioId, {
        stock_symbol: selectedSymbol,
        stock_name: selectedName || selected?.name,
        side,
        qty,
        price
      });
      saveRecent(selectedSymbol);
      setRecentSymbols(loadRecent());
      await refresh(true);
      setQ("");
      setSelectedSymbol("");
      setSelectedName("");
      setTradeOpen(false);
    } catch (e) {
      setError(e.message || "Failed");
    }
  }

  async function removeHolding(holdingId) {
    setError("");
    try {
      await api.deleteHolding(portfolioId, holdingId);
      setHoldings((prev) => prev.filter((h) => h.id !== holdingId));
      await refresh(true);
    } catch (e) {
      setError(e.message || "Failed to delete");
    }
  }

  async function openStockDetail(symbol) {
    if (!symbol) return;
    setSelectedHoldingSymbol(symbol);
    setStockDetail(null);
    setStockDetailBusy(true);
    setError("");
    try {
      const d = await api.stockDetail(symbol);
      setStockDetail(d);
    } catch (e) {
      setError(e.message || "Failed to load stock detail");
    } finally {
      setStockDetailBusy(false);
    }
  }

  function closeStockDetail() {
    setSelectedHoldingSymbol("");
    setStockDetail(null);
    setStockDetailBusy(false);
  }

  function logout() {
    clearTokens();
    nav("/");
  }

  async function ensurePortfoliosLoaded() {
    if (allPortfolios.length) return;
    try {
      const list = await api.listPortfolios();
      setAllPortfolios(Array.isArray(list) ? list : []);
    } catch (e) {
      // non-fatal; cluster modal can still show current portfolio only
      setAllPortfolios([]);
    }
  }

  useEffect(() => {
    let alive = true;
    if (activeBottomTab !== "cluster") return;
    if (!Array.isArray(clusterPortfolioIds) || clusterPortfolioIds.length === 0) return;

    setClusterBusy(true);
    setClusterError("");
    api
      .cluster({ portfolioIds: clusterPortfolioIds, k: clusterK })
      .then((d) => {
        if (!alive) return;
        setClusterData(d);
      })
      .catch((e) => {
        if (!alive) return;
        setClusterError(e.message || "Failed to load clusters");
        setClusterData(null);
      })
      .finally(() => {
        if (!alive) return;
        setClusterBusy(false);
      });

    ensurePortfoliosLoaded();
    return () => {
      alive = false;
    };
  }, [activeBottomTab, clusterK, clusterPortfolioIds]);

  async function downloadClusterCsv() {
    setClusterError("");
    try {
      const blob = await api.clusterCsv({ portfolioIds: clusterPortfolioIds, k: clusterK });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const stamp = new Date().toISOString().slice(0, 10);
      a.download = `clusters_${stamp}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setClusterError(e.message || "Failed to download CSV");
    }
  }

  return (
    <div className="page pageWide">
      <NavBar
        title={portfolio?.name || "Portfolio"}
        subtitle={
          <Link className="link" to="/dashboard">
            Back to dashboard
          </Link>
        }
        links={[
          { to: "/dashboard", label: "Dashboard" },
          { to: `/portfolio/${portfolioId}`, label: "Holdings", end: true, match: (l) => l.pathname.startsWith("/portfolio/") },
          { to: `/analysis/${portfolioId}`, label: "Analysis", match: (l) => l.pathname.startsWith("/analysis/") },
          { to: `/chart/${portfolioId}`, label: "Charts", match: (l) => l.pathname.startsWith("/chart/") },
          { to: "/account", label: "Account" }
        ]}
        actions={
          <button className="btn danger sm" type="button" onClick={logout}>
            Logout
          </button>
        }
      />

      <main className="grid portfolioGrid">
        <section className="card">
          <div className="portfolioSectionHead">
            <h3 style={{ margin: 0 }}>Holdings</h3>
            <div className="portfolioSectionActions">
              <button className="btn primary sm" type="button" onClick={() => setTradeOpen(true)}>
                + Add trade
              </button>
              <Link className="btn ghost sm" to={`/analysis/${portfolioId}`}>
                Open Analysis
              </Link>
            </div>
          </div>
          {error ? <div className="error">{error}</div> : null}
          {holdings.length === 0 ? (
            <div className="muted" style={{ marginTop: 10 }}>
              No holdings yet. Click <span className="strong">+ Add trade</span> to add your first stock.
            </div>
          ) : null}
          <div className="kpiRow">
            <div className="kpi">
              <div className="kpiLabel">Realized P&L (SELL)</div>
              <div className={toNum(portfolio?.realized_pnl_total) >= 0 ? "kpiValue pos" : "kpiValue neg"}>
                {fmt(portfolio?.realized_pnl_total)}
              </div>
            </div>
            <div className="kpi">
              <div className="kpiLabel">Holdings</div>
              <div className="kpiValue">{holdings.length}</div>
            </div>
          </div>
          <div className="table holdingsTable desktopHoldingsTable">
            <div className="row head holdingsRow">
              <div data-label="Symbol">Symbol</div>
              <div data-label="Stock">Stock</div>
              <div className="right" data-label="Qty">Qty</div>
              <div className="right" data-label="Avg">Avg</div>
              <div className="right" data-label="Last">Last</div>
              <div className="right" data-label="Min (365d)">Min (365d)</div>
              <div className="right" data-label="Max (365d)">Max (365d)</div>
              <div className="right" data-label="P/E">P/E</div>
              <div className="right" data-label="Discount">Discount</div>
              <div className="right" data-label="U.PnL">U.PnL</div>
              <div className="right" data-label="Action">Action</div>
            </div>
            {holdings.map((h) => {
              const symbol = h.stock?.symbol ? String(h.stock.symbol) : "";
              const metrics = symbol ? holdingMetricsBySymbol[symbol] : null;
              const avgNum = toNum(h.avg_buy_price);
              const low52 = toNum(metrics?.low_52w);
              const high52 = toNum(metrics?.high_52w);
              const pe = toNum(metrics?.pe);
              const discountPct = toNum(metrics?.discount_from_52w_high_pct);
              const sectorLabel = h.stock?.sector?.name || "--";
              const exLabel = h.stock?.exchange ? ` (${h.stock.exchange})` : "";
              return (
              <div
                className="row holdingsRow"
                key={h.id}
                style={{ cursor: "pointer" }}
                onClick={() => openStockDetail(h.stock?.symbol)}
                title="Click to view stock detail"
              >
                <div className="mono" data-label="Symbol">{h.stock?.symbol}</div>
                <div data-label="Stock">
                  <div>{h.stock?.name}</div>
                  <div className="muted small">
                    {sectorLabel}
                    {exLabel}
                  </div>
                </div>
                <div className="right" data-label="Qty">{h.qty}</div>
                <div className="right" data-label="Avg">{avgNum === null ? "--" : fmt(avgNum)}</div>
                <div className="right" data-label="Last">
                  <div>{fmt(h.last_price)}</div>
                </div>
                <div className="right" data-label="Min (365d)">{low52 === null ? "--" : fmt(low52)}</div>
                <div className="right" data-label="Max (365d)">{high52 === null ? "--" : fmt(high52)}</div>
                <div className="right" data-label="P/E">{pe === null ? "--" : fmt(pe)}</div>
                <div className="right" data-label="Discount">{discountPct === null ? "--" : `${fmt(discountPct)}%`}</div>
                <div className={toNum(h.unrealized_pnl) >= 0 ? "right pos" : "right neg"} data-label="U.PnL">
                  {h.unrealized_pnl === null ? "--" : fmt(h.unrealized_pnl)}
                </div>
                <div className="right" data-label="Action" onClick={(e) => e.stopPropagation()}>
                  <button className="btn danger sm" onClick={() => removeHolding(h.id)} title="Delete holding row">
                    Delete
                  </button>
                </div>
              </div>
              );
            })}
          </div>

          <div className="mobileHoldingsList">
            {holdings.map((h) => (
              <button
                key={`mobile-${h.id}`}
                type="button"
                className="mobileHoldingItem"
                onClick={() => openStockDetail(h.stock?.symbol)}
                title="Tap to view stock details"
              >
                <div className="mobileHoldingMain">
                  <div className="mobileHoldingText">
                    <div className="strong mono">{h.stock?.symbol}</div>
                    <div className="muted small">{h.stock?.name}</div>
                  </div>
                  <button
                    className="btn danger sm mobileHoldingDelete"
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      removeHolding(h.id);
                    }}
                    title="Delete holding"
                  >
                    Delete
                  </button>
                </div>
              </button>
            ))}
          </div>

          <div className="stockInlineHint" style={{ marginTop: 12 }}>
            <div className="muted small">Stock detail (click a holding)</div>
            {!selectedHoldingSymbol ? (
              <div className="muted" style={{ marginTop: 6 }}>
                Select a stock to see 52-week min/max and P/E.
              </div>
            ) : (
              <div className="card" style={{ marginTop: 10, background: "rgba(255,255,255,0.04)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                  <div>
                    <div className="strong mono">{selectedHoldingSymbol}</div>
                    <div className="muted small">{stockDetail?.fundamentals?.sector || ""}</div>
                  </div>
                  <div className="muted small">{stockDetailBusy ? "Loading..." : ""}</div>
                </div>

                {(() => {
                  const h = holdings.find((x) => String(x?.stock?.symbol || "") === String(selectedHoldingSymbol || ""));
                  const avg = toNum(h?.avg_buy_price);
                  const qtyNum = toNum(h?.qty);
                  const last = toNum(stockDetail?.quote?.last_price);
                  const low52 = toNum(stockDetail?.range_52w?.low_52w);
                  const high52 = toNum(stockDetail?.range_52w?.high_52w);
                  const discountPct =
                    last !== null && high52 !== null && high52 !== 0 ? round2(((high52 - last) / high52) * 100) : null;
                  const upnl =
                    last !== null && avg !== null && qtyNum !== null ? round2((last - avg) * qtyNum) : toNum(h?.unrealized_pnl);

                  return (
                    <>
                      <div className="kpiRow" style={{ marginTop: 10 }}>
                        <div className="kpi">
                          <div className="kpiLabel">Min (365d)</div>
                          <div className="kpiValue">{low52 === null ? "--" : fmt(low52)}</div>
                        </div>
                        <div className="kpi">
                          <div className="kpiLabel">Max (365d)</div>
                          <div className="kpiValue">{high52 === null ? "--" : fmt(high52)}</div>
                        </div>
                      </div>

                      <div className="kpiRow" style={{ marginTop: 10 }}>
                        <div className="kpi">
                          <div className="kpiLabel">P/E Ratio</div>
                          <div className="kpiValue">{fmt(stockDetail?.pe)}</div>
                        </div>
                        <div className="kpi">
                          <div className="kpiLabel">Last Price</div>
                          <div className="kpiValue">{fmt(last)}</div>
                        </div>
                      </div>

                      <div className="kpiRow" style={{ marginTop: 10 }}>
                        <div className="kpi">
                          <div className="kpiLabel">Discount (from 52W high)</div>
                          <div className={discountPct === null ? "kpiValue" : discountPct >= 0 ? "kpiValue pos" : "kpiValue neg"}>
                            {discountPct === null ? "--" : `${fmt(discountPct)}%`}
                          </div>
                        </div>
                        <div className="kpi">
                          <div className="kpiLabel">U.PnL (vs Avg)</div>
                          <div className={upnl === null ? "kpiValue" : upnl >= 0 ? "kpiValue pos" : "kpiValue neg"}>
                            {upnl === null ? "--" : fmt(upnl)}
                          </div>
                        </div>
                      </div>

                      <div className="muted small" style={{ marginTop: 8 }}>
                        Tip: <span className="pos">green</span> = favorable, <span className="neg">red</span> = unfavorable (same colors as U.PnL).
                      </div>
                    </>
                  );
                })()}
              </div>
            )}
          </div>
        </section>

        <section className="card" style={{ gridColumn: "1 / -1" }}>
          <div className="portfolioSectionHead">
            <h3 style={{ margin: 0 }}>Transactions</h3>
            <div className="segmented transactionsTabs">
              <button
                className={activeBottomTab === "transactions" ? "seg active" : "seg"}
                onClick={() => setActiveBottomTab("transactions")}
              >
                Trades
              </button>
              <button className={activeBottomTab === "pe" ? "seg active" : "seg"} onClick={() => setActiveBottomTab("pe")}>
                P/E
              </button>
              <button className={activeBottomTab === "discount" ? "seg active" : "seg"} onClick={() => setActiveBottomTab("discount")}>
                Discount
              </button>
              <button className={activeBottomTab === "forecast" ? "seg active" : "seg"} onClick={() => setActiveBottomTab("forecast")}>
                Forecast
              </button>
              <button
                className={activeBottomTab === "cluster" ? "seg active" : "seg"}
                onClick={() => {
                  setActiveBottomTab("cluster");
                  setClusterOpen(true);
                  ensurePortfoliosLoaded();
                }}
                ref={clusterAnchorRef}
              >
                Cluster
              </button>
            </div>
          </div>

          {activeBottomTab === "transactions" ? (
            <>
              {transactions.length === 0 ? <div className="muted">No transactions yet.</div> : null}
              <div className="table">
                <div className="row head" style={{ gridTemplateColumns: "1.2fr 1fr 0.8fr 0.9fr 1fr" }}>
                  <div data-label="Symbol">Symbol</div>
                  <div data-label="Side">Side</div>
                  <div className="right" data-label="Qty">Qty</div>
                  <div className="right" data-label="Price">Price</div>
                  <div className="right" data-label="Realized">Realized</div>
                </div>
                {transactions.map((t) => (
                  <div className="row" key={t.id} style={{ gridTemplateColumns: "1.2fr 1fr 0.8fr 0.9fr 1fr" }}>
                    <div className="mono" data-label="Symbol">{t.stock?.symbol}</div>
                    <div className={t.side === "BUY" ? "pos" : "neg"} data-label="Side">{t.side}</div>
                    <div className="right" data-label="Qty">{t.qty}</div>
                    <div className="right" data-label="Price">{fmt(t.price)}</div>
                    <div className={toNum(t.realized_pnl) >= 0 ? "right pos" : "right neg"} data-label="Realized">{fmt(t.realized_pnl)}</div>
                  </div>
                ))}
              </div>
            </>
          ) : activeBottomTab === "pe" ? (
            <PortfolioPEChart portfolioId={portfolioId} />
          ) : activeBottomTab === "discount" ? (
            <PortfolioDiscountChart portfolioId={portfolioId} />
          ) : activeBottomTab === "forecast" ? (
            <PortfolioForecastChart portfolioId={portfolioId} />
          ) : (
            <PortfolioClusterPanel
              clusterData={clusterData}
              busy={clusterBusy}
              error={clusterError}
              k={clusterK}
              setK={setClusterK}
              onOpenConfig={() => {
                setClusterOpen(true);
                ensurePortfoliosLoaded();
              }}
              onDownloadCsv={downloadClusterCsv}
              selectAnchorRef={clusterSelectAnchorRef}
            />
          )}
        </section>
      </main>

      {selectedHoldingSymbol ? (
        <div className="stockDetailModalBackdrop" role="presentation" onClick={closeStockDetail}>
          <div className="stockDetailModal" role="dialog" aria-modal="true" aria-label="Stock details" onClick={(e) => e.stopPropagation()}>
            <div className="stockDetailModalHead">
              <div>
                <div className="strong mono">{selectedHoldingSymbol}</div>
                <div className="muted small">{stockDetail?.fundamentals?.sector || "Stock detail"}</div>
              </div>
              <div className="stockDetailModalActions">
                <div className="muted small">{stockDetailBusy ? "Loading..." : ""}</div>
                <button className="stockDetailCloseBtn" type="button" onClick={closeStockDetail} aria-label="Close stock details">
                  ×
                </button>
              </div>
            </div>

            {(() => {
              const h = holdings.find((x) => String(x?.stock?.symbol || "") === String(selectedHoldingSymbol || ""));
              const avg = toNum(h?.avg_buy_price);
              const qtyNum = toNum(h?.qty);
              const last = toNum(stockDetail?.quote?.last_price);
              const low52 = toNum(stockDetail?.range_52w?.low_52w);
              const high52 = toNum(stockDetail?.range_52w?.high_52w);
              const discountPct =
                last !== null && high52 !== null && high52 !== 0 ? round2(((high52 - last) / high52) * 100) : null;
              const upnl =
                last !== null && avg !== null && qtyNum !== null ? round2((last - avg) * qtyNum) : toNum(h?.unrealized_pnl);

              return (
                <>
                  <div className="kpiRow" style={{ marginTop: 10 }}>
                    <div className="kpi">
                      <div className="kpiLabel">Min (365d)</div>
                      <div className="kpiValue">{low52 === null ? "--" : fmt(low52)}</div>
                    </div>
                    <div className="kpi">
                      <div className="kpiLabel">Max (365d)</div>
                      <div className="kpiValue">{high52 === null ? "--" : fmt(high52)}</div>
                    </div>
                  </div>

                  <div className="kpiRow" style={{ marginTop: 10 }}>
                    <div className="kpi">
                      <div className="kpiLabel">P/E Ratio</div>
                      <div className="kpiValue">{fmt(stockDetail?.pe)}</div>
                    </div>
                    <div className="kpi">
                      <div className="kpiLabel">Last Price</div>
                      <div className="kpiValue">{fmt(last)}</div>
                    </div>
                  </div>

                  <div className="kpiRow" style={{ marginTop: 10 }}>
                    <div className="kpi">
                      <div className="kpiLabel">Discount (from 52W high)</div>
                      <div className={discountPct === null ? "kpiValue" : discountPct >= 0 ? "kpiValue pos" : "kpiValue neg"}>
                        {discountPct === null ? "--" : `${fmt(discountPct)}%`}
                      </div>
                    </div>
                    <div className="kpi">
                      <div className="kpiLabel">U.PnL (vs Avg)</div>
                      <div className={upnl === null ? "kpiValue" : upnl >= 0 ? "kpiValue pos" : "kpiValue neg"}>
                        {upnl === null ? "--" : fmt(upnl)}
                      </div>
                    </div>
                  </div>
                </>
              );
            })()}
          </div>
        </div>
      ) : null}

      <Footer />

      {tradeOpen ? (
        <div className="modalBackdrop" onClick={() => setTradeOpen(false)} role="presentation">
          <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Add trade">
            <div className="modalHeader">
              <div>
                <div className="strong">Add trade</div>
                <div className="muted small">Buy/Sell from any stock (NSE/BSE via yfinance)</div>
              </div>
              <button className="btn ghost sm" type="button" onClick={() => setTradeOpen(false)} aria-label="Close">
                Close
              </button>
            </div>

            {error ? <div className="error">{error}</div> : null}

            <label className="label">
              Search stock (symbol/name)
              <div className="inputWithBtn">
                <input
                  ref={tradeSearchRef}
                  className="input"
                  value={q}
                  onChange={(e) => {
                    const v = e.target.value;
                    setQ(v);
                    const maybe = v.trim().toUpperCase();
                    if ((maybe.endsWith(".NS") || maybe.endsWith(".BO")) && maybe.length >= 5) {
                      setSelectedSymbol(maybe);
                      setSelectedName("");
                    }
                  }}
                  onKeyDown={(e) => {
                    const list = stockResults.slice(0, 8);
                    if (!list.length) return;
                    if (e.key === "ArrowDown") {
                      e.preventDefault();
                      setActiveSearchIdx((i) => Math.min(i + 1, list.length - 1));
                    } else if (e.key === "ArrowUp") {
                      e.preventDefault();
                      setActiveSearchIdx((i) => Math.max(i - 1, 0));
                    } else if (e.key === "Enter") {
                      e.preventDefault();
                      const picked = list[Math.min(activeSearchIdx, list.length - 1)];
                      if (!picked) return;
                      setSelectedSymbol(picked.symbol);
                      setSelectedName(picked.name || "");
                      setQ(`${picked.symbol}`);
                    }
                  }}
                  placeholder="Type: INFY, Reliance, TCS.NS"
                />
                {q ? (
                  <button
                    className="inputClearBtn"
                    type="button"
                    onClick={() => {
                      setQ("");
                      setSelectedSymbol("");
                      setSelectedName("");
                    }}
                    aria-label="Clear search"
                    title="Clear"
                  >
                    ×
                  </button>
                ) : null}
              </div>
            </label>

            <div className="searchPanel">
              {recentSymbols.length ? (
                <div className="searchBlock">
                  <div className="muted small">Recent</div>
                  <div className="chipRow">
                    {recentSymbols.map((sym) => (
                      <button
                        key={sym}
                        className="chip"
                        type="button"
                        onClick={() => {
                          setSelectedSymbol(sym);
                          setSelectedName("");
                          setQ(sym);
                        }}
                      >
                        {sym}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="searchBlock">
                <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "baseline" }}>
                  <div className="muted small">Results</div>
                  <div className="muted small">
                    {searchPreviewBusy ? "Updating..." : stockResults.length ? "↑/↓ navigate • Enter select" : ""}
                  </div>
                </div>
                {q.trim() && stockResults.length === 0 ? <div className="muted small">No results.</div> : null}
                <div className="searchList">
                  {stockResults.slice(0, 8).map((s, idx) => (
                    (() => {
                      const sym = String(s.symbol);
                      const p = searchPreviewBySymbol[sym] || null;
                      const peLabel = p?.pe === null || p?.pe === undefined ? "--" : fmt(p.pe);
                      const disc = p?.discount_from_52w_high_pct;
                      const discLabel = disc === null || disc === undefined ? "--" : `${fmt(disc)}%`;
                      const lastLabel = p?.last_price === null || p?.last_price === undefined ? "--" : fmt(p.last_price);
                      const isActive = idx === activeSearchIdx;
                      const isSelected = String(s.symbol) === String(selectedSymbol);
                      const discClass =
                        disc === null || disc === undefined
                          ? ""
                          : Number(disc) >= 20
                            ? "pos"
                            : Number(disc) <= 5
                              ? "neg"
                              : "";
                      const showLoading = searchPreviewBusy && !p;
                      return (
                    <button
                      key={s.symbol}
                      type="button"
                      className={[
                        "searchItem",
                        isSelected ? "active" : "",
                        isActive ? "kbdActive" : ""
                      ]
                        .filter(Boolean)
                        .join(" ")}
                      onClick={() => {
                        setSelectedSymbol(s.symbol);
                        setSelectedName(s.name || "");
                        setQ(`${s.symbol}`);
                      }}
                    >
                      <div className="searchItemRow">
                        <div className="searchLeft">
                          <div className="searchAvatar" aria-hidden="true">
                            {String(s.symbol || "?").slice(0, 1)}
                          </div>
                          <div>
                            <div className="mono strong">{s.symbol}</div>
                            <div className="muted small">{s.name}</div>
                          </div>
                        </div>
                        <div className="searchItemStats" aria-label="Stock preview">
                          <div className="statPill">
                            <div className="statLabel">Last</div>
                            <div className="statValue mono">{showLoading ? <span className="statSkeleton" /> : lastLabel}</div>
                          </div>
                          <div className="statPill">
                            <div className="statLabel">P/E</div>
                            <div className="statValue mono">{showLoading ? <span className="statSkeleton" /> : peLabel}</div>
                          </div>
                          <div className="statPill">
                            <div className="statLabel">Disc</div>
                            <div className={discClass ? `statValue mono ${discClass}` : "statValue mono"}>
                              {showLoading ? <span className="statSkeleton" /> : discLabel}
                            </div>
                          </div>
                        </div>
                      </div>
                    </button>
                      );
                    })()
                  ))}
                </div>
              </div>
            </div>

            {selectedSymbol ? (
              <div className="kpiRow" style={{ marginTop: 10 }}>
                <div className="kpi">
                  <div className="kpiLabel">Selected</div>
                  <div className="strong mono">{selectedSymbol}</div>
                  <div className="muted small">{selectedName || selected?.name || ""}</div>
                </div>
                <div className="kpi">
                  <div className="kpiLabel">Last price</div>
                  <div className="kpiValue">{quoteBusy ? "--" : fmt(price)}</div>
                  <div className="muted small">{quoteBusy ? "Fetching…" : ""}</div>
                </div>
              </div>
            ) : null}

            {selectedSymbol ? (
              <div className="kpiRow" style={{ marginTop: 10 }}>
                <div className="kpi">
                  <div className="kpiLabel">P/E Ratio</div>
                  <div className="kpiValue">
                    {selectedPreview?.pe === null || selectedPreview?.pe === undefined ? "--" : fmt(selectedPreview.pe)}
                  </div>
                </div>
                <div className="kpi">
                  <div className="kpiLabel">Discount from 52W High</div>
                  <div className="kpiValue">
                    {selectedPreview?.discount_from_52w_high_pct === null || selectedPreview?.discount_from_52w_high_pct === undefined
                      ? "--"
                      : `${fmt(selectedPreview.discount_from_52w_high_pct)}%`}
                  </div>
                </div>
              </div>
            ) : null}

            <div className="twoCol">
              <label className="label">
                Side
                <select className="input" value={side} onChange={(e) => setSide(e.target.value)}>
                  <option value="BUY">BUY</option>
                  <option value="SELL">SELL</option>
                </select>
              </label>
              <label className="label">
                Qty
                <input className="input" value={qty} onChange={(e) => setQty(e.target.value)} />
              </label>
            </div>
            <div className="twoCol">
              <label className="label">
                Trade price
                <input
                  className="input"
                  inputMode="decimal"
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                  onBlur={() => {
                    const r = round2(price);
                    if (r !== null) setPrice(r.toFixed(2));
                  }}
                />
              </label>
              <label className="label">
                &nbsp;
                <button className="btn primary" type="button" onClick={placeTrade} style={{ width: "100%" }}>
                  Add
                </button>
              </label>
            </div>
          </div>
        </div>
      ) : null}

      <Popover
        open={clusterOpen}
        anchorRef={clusterSelectAnchorRef?.current ? clusterSelectAnchorRef : clusterAnchorRef}
        onClose={() => setClusterOpen(false)}
        title="Cluster setup"
        ariaLabel="Cluster setup"
        width={520}
      >
        <div className="twoCol" style={{ marginTop: 0 }}>
          <label className="label" style={{ marginTop: 0 }}>
            Clusters (k)
            <input
              className="input"
              type="number"
              min="2"
              max="8"
              value={clusterK}
              onChange={(e) => {
                const v = Number(e.target.value);
                if (!Number.isFinite(v)) return;
                setClusterK(Math.max(2, Math.min(8, v)));
              }}
            />
          </label>
          <div className="label" style={{ marginTop: 0 }}>
            Selected
            <div className="muted small">{clusterPortfolioIds.length} portfolio(s)</div>
          </div>
        </div>

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 8 }}>
          <button className="btn ghost sm" type="button" onClick={() => setClusterPortfolioIds([portfolioId])}>
            Current only
          </button>
          <button
            className="btn ghost sm"
            type="button"
            onClick={() => setClusterPortfolioIds((allPortfolios || []).map((p) => p.id).filter(Boolean))}
            disabled={!allPortfolios.length}
          >
            Select all
          </button>
        </div>

        <div className="list" style={{ marginTop: 10 }}>
          {(allPortfolios.length ? allPortfolios : [{ id: portfolioId, name: portfolio?.name || `Portfolio #${portfolioId}` }]).map((p) => {
            const checked = clusterPortfolioIds.includes(p.id);
            return (
              <label key={p.id} className="listItemRow" style={{ cursor: "pointer" }}>
                <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => {
                      setClusterPortfolioIds((prev) => {
                        const next = new Set(prev || []);
                        if (next.has(p.id)) next.delete(p.id);
                        else next.add(p.id);
                        const arr = Array.from(next).filter(Boolean);
                        return arr.length ? arr : [portfolioId];
                      });
                    }}
                  />
                  <div>
                    <div className="strong">{p.name}</div>
                    <div className="muted small">#{p.id}</div>
                  </div>
                </div>
                <div className="muted small">{checked ? "Selected" : ""}</div>
              </label>
            );
          })}
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap", marginTop: 10 }}>
          <div className="muted small">Tip: Use 2–5 clusters for best readability.</div>
          <button className="btn primary sm" type="button" onClick={() => setClusterOpen(false)}>
            Apply
          </button>
        </div>
      </Popover>
    </div>
  );
}

function PortfolioClusterPanel({
  clusterData,
  busy,
  error,
  k,
  setK,
  onOpenConfig,
  onDownloadCsv,
  selectAnchorRef
}) {
  const clusters = clusterData?.clusters || [];
  const portfolios = clusterData?.portfolios || [];
  const total = clusters.reduce((acc, c) => acc + (c.size || 0), 0) || 0;

  const flatItems = clusters.flatMap((c) => (c.items || []).map((it) => ({ ...it, _clusterId: c.id })));
  const palette = ["var(--accent1)", "var(--accent2)", "var(--accent3)", "#60a5fa", "#f59e0b", "#a78bfa", "#34d399", "#fb7185"];

  const getFeat = (it, key) => {
    if (!it) return null;
    if (key === "pe") return Number(it.pe);
    if (key === "discount") return Number(it.discount_from_52w_high_pct);
    if (key === "position") return Number(it.position_in_52w_range_pct);
    if (key === "log_last") {
      const lp = Number(it.last_price);
      if (!Number.isFinite(lp) || lp <= 0) return null;
      return Math.log1p(lp);
    }
    return null;
  };

  const logMvs = flatItems
    .map((it) => {
      const mv = Number(it.market_value);
      if (!Number.isFinite(mv) || mv <= 0) return null;
      return Math.log1p(mv);
    })
    .filter((x) => x !== null);
  const mvMin = logMvs.length ? Math.min(...logMvs) : 0;
  const mvMax = logMvs.length ? Math.max(...logMvs) : 1;
  const radiusFor = (it) => {
    const mv = Number(it.market_value);
    if (!Number.isFinite(mv) || mv <= 0 || mvMax === mvMin) return 4.2;
    const t = (Math.log1p(mv) - mvMin) / (mvMax - mvMin);
    return 3.2 + t * 6.0;
  };

  const labelFor = (it) => {
    const pe = fmt(it.pe);
    const disc = fmt(it.discount_from_52w_high_pct);
    const pos = fmt(it.position_in_52w_range_pct);
    const last = fmt(it.last_price);
    return `${it.symbol} | ${it.portfolio_name || `#${it.portfolio_id}`} | Last ${last} | P/E ${pe} | Disc ${disc}% | Pos ${pos}%`;
  };

  const makePoints = (xKey, yKey, colorMode = "cluster") => {
    return flatItems
      .map((it) => {
        const x = getFeat(it, xKey);
        const y = getFeat(it, yKey);
        const base = {
          x,
          y,
          r: radiusFor(it),
          label: labelFor(it)
        };
        if (colorMode === "plain") {
          return { ...base, color: "rgba(232,238,252,0.75)" };
        }
        return { ...base, color: palette[(it._clusterId || 0) % palette.length] };
      })
      .filter((p) => Number.isFinite(Number(p.x)) && Number.isFinite(Number(p.y)));
  };

  const unlabeledPoints = makePoints("discount", "pe", "plain");
  const clusteredPoints = makePoints("discount", "pe", "cluster");

  const matrixPairs = [
    ["discount", "pe"],
    ["position", "pe"],
    ["log_last", "pe"],
    ["discount", "position"],
    ["log_last", "discount"],
    ["log_last", "position"]
  ];

  const featLabel = (k2) => {
    if (k2 === "discount") return "Discount from 52W high (%)";
    if (k2 === "position") return "52W position (%)";
    if (k2 === "pe") return "P/E";
    if (k2 === "log_last") return "log(Last price)";
    return k2;
  };

  const tickSuffix = (k2) => {
    if (k2 === "discount" || k2 === "position") return "%";
    return "";
  };

  return (
    <div>
      <div className="sectionRow">
        <div>
          <div className="strong">Clustering</div>
          <div className="muted small">
            {portfolios.length ? `Portfolios: ${portfolios.map((p) => p.name).join(", ")}` : "Select portfolios to begin."}
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button className="btn ghost sm" type="button" onClick={onOpenConfig} ref={selectAnchorRef}>
            Select portfolios
          </button>
          <button className="btn ghost sm" type="button" onClick={onDownloadCsv} disabled={!clusters.length}>
            Download CSV
          </button>
        </div>
      </div>

      <div className="twoCol" style={{ marginTop: 10 }}>
        <label className="label" style={{ marginTop: 0 }}>
          Clusters (k)
          <input
            className="input"
            type="number"
            min="2"
            max="8"
            value={k}
            onChange={(e) => {
              const v = Number(e.target.value);
              if (!Number.isFinite(v)) return;
              setK(Math.max(2, Math.min(8, v)));
            }}
          />
        </label>
        <div className="label" style={{ marginTop: 0 }}>
          What it means
          <div className="muted small">{clusterData?.disclaimer || "Educational grouping based on P/E, discount, and 52W position."}</div>
        </div>
      </div>

      {error ? <div className="error">{error}</div> : null}
      {busy ? <div className="skeleton h200" style={{ marginTop: 10 }} /> : null}

      {clusters.length ? (
        <div className="card" style={{ marginTop: 12, background: "rgba(255,255,255,0.04)" }}>
          <div className="strong">Cluster sizes</div>
          <div style={{ marginTop: 10, display: "grid", gap: 10 }}>
            {clusters.map((c) => {
              const pct = total ? Math.round(((c.size || 0) / total) * 100) : 0;
              return (
                <div key={c.id} style={{ display: "grid", gridTemplateColumns: "120px 1fr 70px", gap: 10, alignItems: "center" }}>
                  <div className="mono strong">Cluster {c.id}</div>
                  <div style={{ height: 10, borderRadius: 999, background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
                    <div
                      style={{
                        width: `${pct}%`,
                        height: "100%",
                        background: "linear-gradient(90deg, color-mix(in srgb, var(--accent1) 65%, transparent), color-mix(in srgb, var(--accent2) 45%, transparent))"
                      }}
                    />
                  </div>
                  <div className="muted small right">
                    {c.size} ({pct}%)
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {clusters.length ? (
        <div className="twoCol" style={{ marginTop: 12 }}>
          <ScatterPlot
            title="Unlabeled data"
            subtitle="Discount vs P/E (all points)"
            points={unlabeledPoints}
            xLabel="Discount from 52W high (%)"
            yLabel="P/E"
            xTickSuffix="%"
          />
          <ScatterPlot
            title="Clustered data"
            subtitle={`k = ${k} (colored by cluster)`}
            points={clusteredPoints}
            xLabel="Discount from 52W high (%)"
            yLabel="P/E"
            xTickSuffix="%"
          />
        </div>
      ) : null}

      {clusters.length ? (
        <div className="card" style={{ marginTop: 12, background: "rgba(255,255,255,0.04)" }}>
          <div className="strong">4D view (pairwise projections)</div>
          <div className="muted small" style={{ marginTop: 6 }}>
            Clustering uses 4 features (log Last, P/E, Discount, 52W Position). A single 2D chart can hide separation, so this matrix shows multiple
            projections. Dot size represents market value (bigger = larger holding value).
          </div>

          <div className="twoCol" style={{ marginTop: 12 }}>
            <ScatterPlot
              title="Discount vs P/E"
              subtitle="Colored by cluster"
              height={220}
              points={makePoints(matrixPairs[0][0], matrixPairs[0][1], "cluster")}
              xLabel={featLabel(matrixPairs[0][0])}
              yLabel={featLabel(matrixPairs[0][1])}
              xTickSuffix={tickSuffix(matrixPairs[0][0])}
              yTickSuffix={tickSuffix(matrixPairs[0][1])}
            />
            <ScatterPlot
              title="52W Position vs P/E"
              subtitle="Colored by cluster"
              height={220}
              points={makePoints(matrixPairs[1][0], matrixPairs[1][1], "cluster")}
              xLabel={featLabel(matrixPairs[1][0])}
              yLabel={featLabel(matrixPairs[1][1])}
              xTickSuffix={tickSuffix(matrixPairs[1][0])}
              yTickSuffix={tickSuffix(matrixPairs[1][1])}
            />
          </div>

          <div className="twoCol" style={{ marginTop: 12 }}>
            <ScatterPlot
              title="log(Last) vs P/E"
              subtitle="Colored by cluster"
              height={220}
              points={makePoints(matrixPairs[2][0], matrixPairs[2][1], "cluster")}
              xLabel={featLabel(matrixPairs[2][0])}
              yLabel={featLabel(matrixPairs[2][1])}
              xTickSuffix={tickSuffix(matrixPairs[2][0])}
              yTickSuffix={tickSuffix(matrixPairs[2][1])}
            />
            <ScatterPlot
              title="Discount vs 52W Position"
              subtitle="Colored by cluster"
              height={220}
              points={makePoints(matrixPairs[3][0], matrixPairs[3][1], "cluster")}
              xLabel={featLabel(matrixPairs[3][0])}
              yLabel={featLabel(matrixPairs[3][1])}
              xTickSuffix={tickSuffix(matrixPairs[3][0])}
              yTickSuffix={tickSuffix(matrixPairs[3][1])}
            />
          </div>

          <div className="twoCol" style={{ marginTop: 12 }}>
            <ScatterPlot
              title="log(Last) vs Discount"
              subtitle="Colored by cluster"
              height={220}
              points={makePoints(matrixPairs[4][0], matrixPairs[4][1], "cluster")}
              xLabel={featLabel(matrixPairs[4][0])}
              yLabel={featLabel(matrixPairs[4][1])}
              xTickSuffix={tickSuffix(matrixPairs[4][0])}
              yTickSuffix={tickSuffix(matrixPairs[4][1])}
            />
            <ScatterPlot
              title="log(Last) vs 52W Position"
              subtitle="Colored by cluster"
              height={220}
              points={makePoints(matrixPairs[5][0], matrixPairs[5][1], "cluster")}
              xLabel={featLabel(matrixPairs[5][0])}
              yLabel={featLabel(matrixPairs[5][1])}
              xTickSuffix={tickSuffix(matrixPairs[5][0])}
              yTickSuffix={tickSuffix(matrixPairs[5][1])}
            />
          </div>
        </div>
      ) : null}

      {clusters.map((c) => (
        <div key={c.id} className="card" style={{ marginTop: 12 }}>
          <div className="sectionRow">
            <div className="strong">Cluster {c.id}</div>
            <div className="muted small">
              Avg P/E: {fmt(c.avg_pe)} | Avg Disc: {fmt(c.avg_discount_pct)}% | Avg Pos: {fmt(c.avg_position_pct)}%
            </div>
          </div>

          <div className="table" style={{ marginTop: 10 }}>
            <div className="row head" style={{ gridTemplateColumns: "1.2fr 1.1fr 0.9fr 0.7fr 0.8fr 0.9fr" }}>
              <div>Symbol</div>
              <div>Sector</div>
              <div>Portfolio</div>
              <div className="right">Last</div>
              <div className="right">P/E</div>
              <div className="right">Disc</div>
            </div>
            {(c.items || []).map((it) => (
              <div key={`${c.id}:${it.portfolio_id}:${it.symbol}`} className="row" style={{ gridTemplateColumns: "1.2fr 1.1fr 0.9fr 0.7fr 0.8fr 0.9fr" }}>
                <div className="mono strong">{it.symbol}</div>
                <div className="muted">{it.sector || "--"}</div>
                <div className="muted small">{it.portfolio_name || `#${it.portfolio_id}`}</div>
                <div className="right">{fmt(it.last_price)}</div>
                <div className="right">{fmt(it.pe)}</div>
                <div className="right">{fmt(it.discount_from_52w_high_pct)}%</div>
              </div>
            ))}
          </div>
        </div>
      ))}

      {!busy && !clusters.length && !error ? <div className="muted" style={{ marginTop: 10 }}>No cluster data yet.</div> : null}
    </div>
  );
}

function PortfolioPEChart({ portfolioId }) {
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    setBusy(true);
    api
      .portfolioPE(portfolioId)
      .then((d) => {
        if (!alive) return;
        setData(d);
        setErr("");
      })
      .catch((e) => {
        if (!alive) return;
        setErr(e.message || "Failed to load chart");
        if ((e.message || "").includes("HTTP 401") || (e.message || "").includes("HTTP 403")) {
          clearTokens();
          nav("/");
        }
      })
      .finally(() => {
        if (!alive) return;
        setBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [portfolioId, nav]);

  const points = useMemo(() => {
    const holdings = data?.holdings || [];
    return holdings
      .map((h) => ({
        symbol: h.symbol,
        name: h.name,
        pe: h.pe === null || h.pe === undefined ? null : Number(h.pe)
      }))
      .filter((p) => p.pe !== null && Number.isFinite(p.pe));
  }, [data]);

  const maxPE = useMemo(() => (points.length ? Math.max(...points.map((p) => p.pe)) : 0), [points]);

  return (
    <div style={{ marginTop: 10 }}>
      {busy ? <div className="skeleton h200" /> : null}
      {err ? <div className="error">{err}</div> : null}
      {!busy && points.length === 0 ? <div className="muted">No P/E values available for holdings yet.</div> : null}

      <div className="vbarWrap">
        <div className="vbarGrid">
          {points.map((p) => {
            const hPct = maxPE ? Math.max(2, Math.min(100, (p.pe / maxPE) * 100)) : 2;
            return (
              <div className="vbarCol" key={p.symbol} title={`${p.symbol} • PE ${fmt(p.pe)}`}>
                <div className="vbarTrack">
                  <div className="vbarFill" style={{ height: `${hPct}%` }} />
                </div>
                <div className="vbarLabel mono">{p.symbol}</div>
                <div className="vbarValue mono">{fmt(p.pe)}</div>
              </div>
            );
          })}
        </div>
      </div>
      <div className="muted small" style={{ marginTop: 10 }}>
        Vertical bar chart of P/E by holding. P/E is fetched from yfinance fundamentals (best-effort).
      </div>
    </div>
  );
}

function PortfolioDiscountChart({ portfolioId }) {
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    setBusy(true);
    api
      .portfolioPE(portfolioId)
      .then((d) => {
        if (!alive) return;
        setData(d);
        setErr("");
      })
      .catch((e) => {
        if (!alive) return;
        setErr(e.message || "Failed to load chart");
        if ((e.message || "").includes("HTTP 401") || (e.message || "").includes("HTTP 403")) {
          clearTokens();
          nav("/");
        }
      })
      .finally(() => {
        if (!alive) return;
        setBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [portfolioId, nav]);

  const points = useMemo(() => {
    const holdings = data?.holdings || [];
    return holdings
      .map((h) => ({
        symbol: h.symbol,
        discount: h.discount_from_52w_high_pct === null || h.discount_from_52w_high_pct === undefined ? null : Number(h.discount_from_52w_high_pct)
      }))
      .filter((p) => p.discount !== null && Number.isFinite(p.discount));
  }, [data]);

  const maxD = useMemo(() => (points.length ? Math.max(...points.map((p) => p.discount)) : 0), [points]);

  return (
    <div style={{ marginTop: 10 }}>
      {busy ? <div className="skeleton h200" /> : null}
      {err ? <div className="error">{err}</div> : null}
      {!busy && points.length === 0 ? <div className="muted">No discount values yet (needs 52W high + last price).</div> : null}

      <div className="vbarWrap">
        <div className="vbarGrid">
          {points.map((p) => {
            const hPct = maxD ? Math.max(2, Math.min(100, (p.discount / maxD) * 100)) : 2;
            return (
              <div className="vbarCol" key={p.symbol} title={`${p.symbol} • Discount ${fmt(p.discount)}%`}>
                <div className="vbarTrack">
                  <div className="vbarFill vbarFillDiscount" style={{ height: `${hPct}%` }} />
                </div>
                <div className="vbarLabel mono">{p.symbol}</div>
                <div className="vbarValue mono">{fmt(p.discount)}%</div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="muted small" style={{ marginTop: 10 }}>
        Discount % = (52W High − Last) / 52W High × 100.
      </div>
    </div>
  );
}

function PortfolioForecastChart({ portfolioId }) {
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    setBusy(true);
    api
      .portfolioForecast(portfolioId, 90)
      .then((d) => {
        if (!alive) return;
        setData(d);
        setErr("");
      })
      .catch((e) => {
        if (!alive) return;
        setErr(e.message || "Failed to load forecast");
        if ((e.message || "").includes("HTTP 401") || (e.message || "").includes("HTTP 403")) {
          clearTokens();
          nav("/");
        }
      })
      .finally(() => {
        if (!alive) return;
        setBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [portfolioId, nav]);

  const points = useMemo(() => {
    const s = data?.series || [];
    return s.map((p, idx) => ({
      x: p.date,
      xLabel: idx === 0 || idx === Math.floor(s.length / 2) || idx === s.length - 1 ? p.date : "",
      y: p.portfolio_value
    }));
  }, [data]);

  return (
    <div style={{ marginTop: 10 }}>
      {busy ? <div className="skeleton h200" /> : null}
      {err ? <div className="error">{err}</div> : null}
      {!busy && points.length === 0 ? <div className="muted">No forecast available (add holdings first).</div> : null}
      {points.length ? <LineChart points={points} xLabel="Next 90 days" yLabel="Portfolio value" /> : null}
      <div className="muted small" style={{ marginTop: 10 }}>
        {data?.disclaimer || "Educational forecast only."}
      </div>
    </div>
  );
}
