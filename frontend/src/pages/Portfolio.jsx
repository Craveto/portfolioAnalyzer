import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, clearTokens } from "../api.js";
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

function toneClass(label) {
  const v = String(label || "").toLowerCase();
  if (v.includes("bull") || v.includes("positive")) return "pos";
  if (v.includes("bear") || v.includes("negative")) return "neg";
  return "neutral";
}

function asText(v, fallback = "") {
  if (v === null || v === undefined) return fallback;
  if (typeof v === "string") return v || fallback;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (typeof v === "object") {
    const candidate = v.displayName || v.name || v.shortName || v.longName || v.title || v.url;
    if (typeof candidate === "string" && candidate.trim()) return candidate;
    return fallback;
  }
  return fallback;
}

function normKey(v) {
  return String(v || "")
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}

function ModuleLoader({ title = "Loading insights", hint = "Crunching data..." }) {
  return (
    <div className="moduleLoader" role="status" aria-live="polite">
      <div className="moduleLoaderHead">
        <div className="moduleLoaderOrb" />
        <div>
          <div className="strong">{title}</div>
          <div className="muted small">{hint}</div>
        </div>
      </div>
      <div className="moduleLoaderTrack">
        <div className="moduleLoaderBar" />
      </div>
      <div className="moduleLoaderGrid">
        <span />
        <span />
        <span />
        <span />
      </div>
    </div>
  );
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

function recoCacheKey(portfolioId) {
  return `portfolioReco:${portfolioId}`;
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

function readRecoCache(portfolioId, signature = "", ttlMs = 8 * 60 * 1000) {
  try {
    const raw = localStorage.getItem(recoCacheKey(portfolioId));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const age = Date.now() - Number(parsed?.cachedAt || 0);
    if (signature && parsed?.signature !== signature) return null;
    if (!Array.isArray(parsed?.items) || age > ttlMs) return null;
    return parsed.items;
  } catch {
    return null;
  }
}

function writeRecoCache(portfolioId, items, signature = "") {
  try {
    localStorage.setItem(recoCacheKey(portfolioId), JSON.stringify({ items, signature, cachedAt: Date.now() }));
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
  const [tradeSuccess, setTradeSuccess] = useState("");
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
  const [tradeSentimentBySymbol, setTradeSentimentBySymbol] = useState({});
  const [tradeSentimentBusySymbol, setTradeSentimentBusySymbol] = useState("");
  const [tradeSentimentError, setTradeSentimentError] = useState("");
  const [recoOpen, setRecoOpen] = useState(false);
  const [recoBusy, setRecoBusy] = useState(false);
  const [recoError, setRecoError] = useState("");
  const [recommendations, setRecommendations] = useState([]);
  const [recoAddingSymbol, setRecoAddingSymbol] = useState("");
  const [recoSuccess, setRecoSuccess] = useState("");
  const recoWarmSignatureRef = useRef("");

  const [clusterOpen, setClusterOpen] = useState(false);
  const clusterAnchorRef = useRef(null);
  const clusterSelectAnchorRef = useRef(null);
  const [allPortfolios, setAllPortfolios] = useState([]);
  const [clusterPortfolioIds, setClusterPortfolioIds] = useState([portfolioId]);
  const [clusterK, setClusterK] = useState(3);
  const [clusterData, setClusterData] = useState(null);
  const [clusterBusy, setClusterBusy] = useState(false);
  const [clusterError, setClusterError] = useState("");

  const heldSymbolsSet = useMemo(() => {
    return new Set((holdings || []).map((h) => String(h?.stock?.symbol || "").toUpperCase()).filter(Boolean));
  }, [holdings]);

  const holdingsSignature = useMemo(() => {
    return (holdings || [])
      .map((h) => String(h?.stock?.symbol || "").toUpperCase())
      .filter(Boolean)
      .sort()
      .join("|");
  }, [holdings]);

  const sectorWeights = useMemo(() => {
    const map = new Map();
    for (const h of holdings || []) {
      const raw = asText(h?.stock?.sector?.name, "");
      const key = normKey(raw);
      if (!key) continue;
      map.set(key, (map.get(key) || 0) + 1);
    }
    return map;
  }, [holdings]);

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
    const [data, txs] = await Promise.all([portfolioPromise, transactionsPromise]);
    setPortfolio(data);
    setHoldings(data.holdings || []);
    setTransactions(txs || []);
    writePortfolioCache(portfolioId, {
      portfolio: data,
      holdings: data.holdings || [],
      transactions: txs || [],
      holdingMetricsBySymbol
    });

    if (!force && data?.meta?.stale) {
      window.setTimeout(() => {
        refresh(true).catch(() => {});
      }, 0);
    }

    api
      .portfolioPE(portfolioId, force)
      .then((metrics) => {
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
        if (!force && metrics?.meta?.stale) {
          window.setTimeout(() => {
            api.portfolioPE(portfolioId, true).then((fresh) => {
              const fm = {};
              const fItems = fresh?.holdings || [];
              for (const it of fItems) {
                if (it?.symbol) fm[String(it.symbol)] = it;
              }
              setHoldingMetricsBySymbol(fm);
            }).catch(() => {});
          }, 0);
        }
      })
      .catch((e) => {
        if (isAuthErr(e)) {
          clearTokens();
          nav("/");
        }
      });
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
  const selectedQuickSentiment = useMemo(() => tradeSentimentBySymbol[String(selectedSymbol || "")] || null, [tradeSentimentBySymbol, selectedSymbol]);

  async function fetchQuickSentiment(symbol, name = "", force = false) {
    const sym = String(symbol || "").trim().toUpperCase();
    if (!sym) return;
    setTradeSentimentError("");
    setTradeSentimentBusySymbol(sym);
    try {
      const data = await api.quickStockSentiment(sym, name || "", force);
      setTradeSentimentBySymbol((prev) => ({ ...prev, [sym]: data }));
    } catch (e) {
      setTradeSentimentError(e.message || "Quick sentiment is unavailable right now.");
    } finally {
      setTradeSentimentBusySymbol("");
    }
  }

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
    if (!selectedSymbol) return;
    const key = String(selectedSymbol);
    if (tradeSentimentBySymbol[key]) return;
    fetchQuickSentiment(selectedSymbol, selectedName || asText(selected?.name, ""));
  }, [selectedSymbol, selectedName, selected, tradeSentimentBySymbol]);

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

  useEffect(() => {
    if (!recoOpen) return;
    const onKeyDown = (e) => {
      if (e.key === "Escape") setRecoOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [recoOpen]);

  useEffect(() => {
    if (!tradeSuccess) return;
    const t = setTimeout(() => setTradeSuccess(""), 2200);
    return () => clearTimeout(t);
  }, [tradeSuccess]);

  useEffect(() => {
    if (!recoSuccess) return;
    const t = setTimeout(() => setRecoSuccess(""), 2200);
    return () => clearTimeout(t);
  }, [recoSuccess]);

  useEffect(() => {
    if (!recoOpen) return;
    loadRecommendations(false);
  }, [recoOpen]);

  useEffect(() => {
    if (!holdingsSignature) return;
    const signature = `${portfolioId}:${holdingsSignature}`;
    if (recoWarmSignatureRef.current === signature) return;
    recoWarmSignatureRef.current = signature;

    const cached = readRecoCache(portfolioId, signature);
    if (cached?.length) {
      setRecommendations(cached);
      return;
    }
    loadRecommendations(false, true);
  }, [portfolioId, holdingsSignature]);

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
        stock_name: selectedName || asText(selected?.name, ""),
        side,
        qty,
        price
      });
      setTradeSuccess(`Trade added: ${selectedSymbol}`);
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

  async function loadRecommendations(force = false, silent = false) {
    if (!silent && recoBusy) return;
    if (!force && recommendations.length) return;

    const signature = `${portfolioId}:${holdingsSignature}`;
    if (!force) {
      const cached = readRecoCache(portfolioId, signature);
      if (cached?.length) {
        setRecommendations(cached);
        return;
      }
    }

    if (!silent) {
      setRecoBusy(true);
      setRecoError("");
    }
    try {
      const sectorKeys = Array.from(sectorWeights.keys());
      const sectorQueries = sectorKeys.slice(0, 3);
      const marketHints = String(portfolio?.market || "").toUpperCase() === "IN"
        ? ["NIFTY", "BANK", "IT"]
        : ["NASDAQ", "TECH", "HEALTH"];
      const searchQueries = [...sectorQueries, ...marketHints].slice(0, 6);

      const merged = new Map();
      const searchResults = await Promise.all(
        searchQueries.map((qWord) => api.searchStocksLive(qWord).catch(() => []))
      );
      for (const batch of searchResults) {
        for (const item of Array.isArray(batch) ? batch : []) {
          const symbol = String(item?.symbol || "").toUpperCase();
          if (!symbol || heldSymbolsSet.has(symbol) || merged.has(symbol)) continue;
          merged.set(symbol, item);
        }
      }

      const fallbackSymbolsIn = [
        "RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "LT.NS",
        "ITC.NS", "TATAMOTORS.NS", "SUNPHARMA.NS", "MARUTI.NS", "BHARTIARTL.NS"
      ];
      const fallbackSymbolsUs = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "UNH"];
      const fallbackSymbols = String(portfolio?.market || "").toUpperCase() === "IN" ? fallbackSymbolsIn : fallbackSymbolsUs;

      for (const symbol of fallbackSymbols) {
        if (!heldSymbolsSet.has(symbol) && !merged.has(symbol)) {
          merged.set(symbol, { symbol, name: symbol, exchange: symbol.includes(".") ? "NSE/BSE" : "US" });
        }
      }

      const candidates = Array.from(merged.values()).slice(0, 18);
      const preview = await api.stocksPreview(candidates.map((c) => c.symbol));
      const previewBySymbol = {};
      for (const p of Array.isArray(preview) ? preview : []) {
        const symbol = String(p?.symbol || "").toUpperCase();
        if (symbol) previewBySymbol[symbol] = p;
      }

      const ranked = candidates
        .map((item) => {
          const symbol = String(item?.symbol || "").toUpperCase();
          const sectorLabel = asText(item?.sector?.name || item?.sector || "", "");
          const sectorScore = sectorWeights.get(normKey(sectorLabel)) || 0;
          const p = previewBySymbol[symbol] || {};
          const pe = toNum(p?.pe);
          const discount = toNum(p?.discount_from_52w_high_pct);
          const last = toNum(p?.last_price);

          let score = sectorScore * 30;
          if (pe !== null && pe >= 8 && pe <= 28) score += 18;
          if (discount !== null && discount >= 6 && discount <= 35) score += 22;
          if (last !== null && last > 0) score += 8;

          const reasons = [];
          if (sectorScore > 0) reasons.push("Sector match");
          if (pe !== null && pe <= 22) reasons.push("Reasonable P/E");
          if (discount !== null && discount >= 10) reasons.push("Pullback from 52W high");
          if (!reasons.length) reasons.push("High liquidity candidate");

          return {
            symbol,
            name: asText(item?.name, symbol),
            exchange: asText(item?.exchange, "--"),
            sector: sectorLabel || "--",
            pe,
            discount,
            lastPrice: last,
            score,
            reasons,
          };
        })
        .sort((a, b) => b.score - a.score)
        .slice(0, 10);

      setRecommendations(ranked);
      writeRecoCache(portfolioId, ranked, signature);
      if (!ranked.length) {
        if (!silent) setRecoError("No recommendations found for this portfolio yet.");
      }
    } catch (e) {
      if (!silent) setRecoError(e.message || "Failed to load recommendations");
      setRecommendations([]);
    } finally {
      if (!silent) setRecoBusy(false);
    }
  }

  async function addRecommendedToPortfolio(item) {
    const symbol = String(item?.symbol || "").toUpperCase();
    if (!symbol || recoAddingSymbol) return;
    setRecoAddingSymbol(symbol);
    setRecoError("");
    setRecoSuccess("");
    try {
      const price = item?.lastPrice && Number(item.lastPrice) > 0 ? Number(item.lastPrice).toFixed(2) : "1";
      await api.createTransaction(portfolioId, {
        stock_symbol: symbol,
        stock_name: item?.name || symbol,
        side: "BUY",
        qty: "1",
        price,
      });
      setRecoSuccess(`${symbol} added to portfolio`);
      await refresh(true);
      setRecommendations((prev) => prev.filter((x) => String(x.symbol) !== symbol));
    } catch (e) {
      setRecoError(e.message || "Failed to add stock");
    } finally {
      setRecoAddingSymbol("");
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
            <div className="portfolioHeadingWrap">
              <Link className="btn ghost sm iconBtn" to="/dashboard" title="Back to dashboard" aria-label="Back to dashboard">
                <span aria-hidden="true">←</span>
              </Link>
              <h3 style={{ margin: 0 }}>Holdings</h3>
            </div>
            <div className="portfolioSectionActions">
              <button className="btn ghost sm" type="button" onClick={() => setRecoOpen(true)}>
                Recommendations
              </button>
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
            <div className="holdingsRowsViewport">
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

          <div key={activeBottomTab} className="tabPaneTransition">
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
                  <div className="transactionsRowsViewport">
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
          </div>
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

      {recoOpen ? (
        <div className="modalBackdrop" onClick={() => setRecoOpen(false)} role="presentation">
          <div
            className="modal recoModal"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label="Portfolio recommendations"
          >
            <div className="modalHeader">
              <div>
                <div className="strong">Stock recommendations</div>
                <div className="muted small">Relevant to your current portfolio mix</div>
              </div>
              <div className="modalHeaderActions">
                <button className="btn ghost sm" type="button" onClick={() => loadRecommendations(true)} disabled={recoBusy}>
                  {recoBusy ? "Refreshing..." : "Refresh"}
                </button>
                <button className="btn ghost sm" type="button" onClick={() => setRecoOpen(false)}>
                  Close
                </button>
              </div>
            </div>

            {recoError ? <div className="error">{recoError}</div> : null}
            {recoSuccess ? <div className="success">{recoSuccess}</div> : null}

            {recoBusy ? (
              <ModuleLoader title="Finding relevant stocks" hint="Scanning sector fit, valuation and pullback opportunities..." />
            ) : null}

            {!recoBusy && recommendations.length ? (
              <div className="recoList">
                {recommendations.map((item) => (
                  <div className="recoCard" key={item.symbol}>
                    <div className="recoCardHead">
                      <div>
                        <div className="strong mono">{item.symbol}</div>
                        <div className="muted small">{item.name}</div>
                      </div>
                      <div className="recoScore">Fit {Math.round(item.score)}</div>
                    </div>
                    <div className="chipRow">
                      <span className="chip">{item.exchange || "--"}</span>
                      <span className="chip">{item.sector || "--"}</span>
                      {item.reasons.map((r) => (
                        <span className="chip" key={`${item.symbol}:${r}`}>
                          {r}
                        </span>
                      ))}
                    </div>
                    <div className="recoMetrics">
                      <div>
                        <div className="kpiLabel">Last</div>
                        <div className="strong">{item.lastPrice === null ? "--" : fmt(item.lastPrice)}</div>
                      </div>
                      <div>
                        <div className="kpiLabel">P/E</div>
                        <div className="strong">{item.pe === null ? "--" : fmt(item.pe)}</div>
                      </div>
                      <div>
                        <div className="kpiLabel">Discount</div>
                        <div className={item.discount === null ? "strong" : item.discount >= 10 ? "strong pos" : "strong"}>
                          {item.discount === null ? "--" : `${fmt(item.discount)}%`}
                        </div>
                      </div>
                    </div>
                    <div className="recoActions">
                      <button
                        className="btn ghost sm"
                        type="button"
                        onClick={() => {
                          setRecoOpen(false);
                          openStockDetail(item.symbol);
                        }}
                      >
                        Insight
                      </button>
                      <button
                        className={`btn primary sm ${recoAddingSymbol === item.symbol ? "btnBusy" : ""}`}
                        type="button"
                        onClick={() => addRecommendedToPortfolio(item)}
                        disabled={!!recoAddingSymbol}
                      >
                        {recoAddingSymbol === item.symbol ? "Adding..." : "Add to portfolio"}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
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
                <div className="muted small">Buy/Sell from Indian and US stocks (NSE/BSE/NASDAQ/NYSE via yfinance)</div>
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
                    if (maybe.length >= 1 && /^[A-Z][A-Z0-9.\-]{0,9}$/.test(maybe)) {
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
                      setSelectedName(asText(picked.name, ""));
                      setQ(`${picked.symbol}`);
                    }
                  }}
                  placeholder="Type: INFY, TCS.NS, AAPL, MSFT"
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
                        setSelectedName(asText(s.name, ""));
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
                            <div className="muted small">{asText(s.name, "")}</div>
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
                          <button
                            type="button"
                            className={`miniSentBtn ${tradeSentimentBusySymbol === sym ? "busy" : ""}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedSymbol(s.symbol);
                              setSelectedName(asText(s.name, ""));
                              setQ(`${s.symbol}`);
                              fetchQuickSentiment(s.symbol, asText(s.name, ""));
                            }}
                            title="Quick sentiment summary"
                          >
                            {tradeSentimentBusySymbol === sym ? "..." : "Sentiment"}
                          </button>
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
                  <div className="muted small">{selectedName || asText(selected?.name, "")}</div>
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

            {selectedSymbol ? (
              <div className="quickSentimentPanel">
                <div className="quickSentimentHead">
                  <div className="strong">Quick sentiment</div>
                  <button
                    type="button"
                    className={`btn ghost sm ${tradeSentimentBusySymbol === selectedSymbol ? "btnBusy" : ""}`}
                    onClick={() => fetchQuickSentiment(selectedSymbol, selectedName || asText(selected?.name, ""), true)}
                    disabled={tradeSentimentBusySymbol === selectedSymbol}
                  >
                    {tradeSentimentBusySymbol === selectedSymbol ? "Refreshing..." : "Refresh"}
                  </button>
                </div>
                {tradeSentimentError ? <div className="muted small">{tradeSentimentError}</div> : null}
                {selectedQuickSentiment ? (
                  <>
                    <div className="quickSentimentGrid">
                      <div className="quickSentimentMetric">
                        <span>Signal</span>
                        <strong className={toneClass(selectedQuickSentiment.overall_signal?.label)}>
                          {selectedQuickSentiment.overall_signal?.label || "Neutral"}
                        </strong>
                      </div>
                      <div className="quickSentimentMetric">
                        <span>Score</span>
                        <strong>{fmt(selectedQuickSentiment.overall_signal?.sentiment_score)}</strong>
                      </div>
                      <div className="quickSentimentMetric">
                        <span>Confidence</span>
                        <strong>{fmt(Number(selectedQuickSentiment.overall_signal?.confidence || 0) * 100)}%</strong>
                      </div>
                      <div className="quickSentimentMetric">
                        <span>Risk flags</span>
                        <strong>{(selectedQuickSentiment.risk_flags || []).length}</strong>
                      </div>
                    </div>
                    <div className="quickSentimentVerdict">
                      {(selectedQuickSentiment.verdict || {}).reason || "Based on latest news flow and market context."}
                    </div>
                  </>
                ) : (
                  <div className="muted small">Tap Sentiment to load a concise stock view.</div>
                )}
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

      {tradeSuccess ? (
        <div className="successToast" role="status" aria-live="polite">
          <span className="successToastCheck" aria-hidden="true">
            ✓
          </span>
          <span>{tradeSuccess}</span>
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
  const [activeClusterId, setActiveClusterId] = useState(null);
  const activeClusterAnchorRef = useRef(null);

  const clusterInsights = useMemo(() => {
    const safeNum = (v) => (Number.isFinite(Number(v)) ? Number(v) : null);
    const decorated = clusters.map((c) => {
      const pe = safeNum(c.avg_pe);
      const disc = safeNum(c.avg_discount_pct);
      const pos = safeNum(c.avg_position_pct);
      const size = Number(c.size || 0);
      const clusterPct = total ? (size / total) * 100 : 0;

      const opportunityScore =
        (disc === null ? 0 : Math.max(0, Math.min(40, disc)) * 1.5) +
        (pe === null ? 6 : Math.max(0, 35 - pe) * 1.15) +
        (pos === null ? 5 : Math.max(0, 70 - pos) * 0.5) +
        Math.max(0, 16 - clusterPct * 0.35);

      let profile = "Balanced Core";
      let tone = "neutral";
      let action = "Hold core names, add selectively on pullbacks.";

      if ((disc !== null && disc >= 18) && (pe !== null && pe <= 30)) {
        profile = "Opportunity Basket";
        tone = "pos";
        action = "Stagger accumulation with position limits.";
      } else if ((pe !== null && pe > 58) || ((pos !== null && pos > 84) && (disc !== null && disc < 8))) {
        profile = "Overheated Risk";
        tone = "neg";
        action = "Trim exposure, tighten stop-loss / hedge.";
      } else if ((disc !== null && disc < 6) && (pe !== null && pe > 40)) {
        profile = "FOMO Risk";
        tone = "neg";
        action = "Avoid chasing; wait for better risk/reward.";
      }

      return {
        ...c,
        avg_pe: pe,
        avg_discount_pct: disc,
        avg_position_pct: pos,
        clusterPct,
        opportunityScore: Math.round(opportunityScore),
        profile,
        tone,
        action
      };
    });

    const rankedByOpportunity = [...decorated].sort((a, b) => (b.opportunityScore || 0) - (a.opportunityScore || 0));
    const rankedByRisk = [...decorated].sort((a, b) => {
      const aRisk = (a.avg_pe || 0) + (a.avg_position_pct || 0) - (a.avg_discount_pct || 0);
      const bRisk = (b.avg_pe || 0) + (b.avg_position_pct || 0) - (b.avg_discount_pct || 0);
      return bRisk - aRisk;
    });

    const concentration = decorated.length ? Math.max(...decorated.map((c) => c.clusterPct || 0)) : 0;
    const peVals = decorated.map((c) => c.avg_pe).filter((v) => v !== null);
    const peMean = peVals.length ? peVals.reduce((a, b) => a + b, 0) / peVals.length : 0;
    const peDispersion = peVals.length
      ? Math.sqrt(peVals.reduce((acc, v) => acc + ((v - peMean) ** 2), 0) / peVals.length)
      : 0;

    return {
      decorated,
      bestCluster: rankedByOpportunity[0] || null,
      riskyCluster: rankedByRisk[0] || null,
      concentration,
      peDispersion
    };
  }, [clusters, total]);
  const activeCluster = useMemo(() => {
    if (activeClusterId === null || activeClusterId === undefined) return null;
    return clusterInsights.decorated.find((c) => String(c.id) === String(activeClusterId)) || null;
  }, [clusterInsights, activeClusterId]);
  useEffect(() => {
    if (!activeCluster) return;
    const onKeyDown = (e) => {
      if (e.key === "Escape") setActiveClusterId(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activeCluster]);

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
      {busy ? <ModuleLoader title="Building cluster map" hint="Grouping stocks by valuation and positioning..." /> : null}

      {clusters.length ? (
        <>
          <div className="clusterInsightGrid">
            <div className="clusterDecisionCard cardA">
              <div className="kpiLabel">Best Opportunity</div>
              <div className="kpiValue">{clusterInsights.bestCluster ? `Cluster ${clusterInsights.bestCluster.id}` : "--"}</div>
              <div className="muted small">
                {clusterInsights.bestCluster ? `${clusterInsights.bestCluster.profile} • Score ${clusterInsights.bestCluster.opportunityScore}` : ""}
              </div>
            </div>
            <div className="clusterDecisionCard cardB">
              <div className="kpiLabel">Highest Risk</div>
              <div className="kpiValue neg">{clusterInsights.riskyCluster ? `Cluster ${clusterInsights.riskyCluster.id}` : "--"}</div>
              <div className="muted small">{clusterInsights.riskyCluster?.profile || ""}</div>
            </div>
            <div className="clusterDecisionCard cardC">
              <div className="kpiLabel">Concentration Risk</div>
              <div className={`kpiValue ${clusterInsights.concentration > 52 ? "neg" : "neutral"}`}>
                {fmt(round2(clusterInsights.concentration))}%
              </div>
              <div className="muted small">Largest cluster share</div>
            </div>
            <div className="clusterDecisionCard cardD">
              <div className="kpiLabel">P/E Dispersion</div>
              <div className={`kpiValue ${clusterInsights.peDispersion > 16 ? "neg" : "pos"}`}>{fmt(round2(clusterInsights.peDispersion))}</div>
              <div className="muted small">Cross-cluster valuation spread</div>
            </div>
          </div>

          <div className="card" style={{ marginTop: 12, background: "rgba(255,255,255,0.04)" }}>
            <div className="strong">Cluster sizes</div>
            <div className="clusterSizeList">
              {clusterInsights.decorated.map((c) => {
                const pct = total ? Math.round(((c.size || 0) / total) * 100) : 0;
                const toneClass = c.tone === "pos" ? "pos" : c.tone === "neg" ? "neg" : "neutral";
                return (
                  <div key={c.id} className="clusterSizeRow">
                    <div className="mono strong">Cluster {c.id}</div>
                    <div className="clusterSizeBar">
                      <div
                        className={`clusterSizeFill ${toneClass}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <div className="muted small right">
                      {c.size} ({pct}%)
                    </div>
                    <div className={`clusterTag ${toneClass}`}>{c.profile}</div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="clusterPlaybook" style={{ marginTop: 12 }}>
            {clusterInsights.decorated.map((c) => (
              <div
                key={`playbook-${c.id}`}
                className="clusterPlayCard"
                role="button"
                tabIndex={0}
                onClick={(e) => {
                  activeClusterAnchorRef.current = e.currentTarget;
                  setActiveClusterId(c.id);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    activeClusterAnchorRef.current = e.currentTarget;
                    setActiveClusterId(c.id);
                  }
                }}
              >
                <div className="sectionRow">
                  <div className="strong">Cluster {c.id}</div>
                  <div className={`clusterTag ${c.tone}`}>{c.profile}</div>
                </div>
                <div className="muted small" style={{ marginTop: 6 }}>
                  Avg P/E {fmt(c.avg_pe)} | Avg Discount {fmt(c.avg_discount_pct)}% | Avg 52W Position {fmt(c.avg_position_pct)}%
                </div>
                <div className="clusterAction">{c.action}</div>
                <div className="clusterPlayActions">
                  <div className="muted small">Tap to view stock list</div>
                  <button
                    type="button"
                    className="btn ghost sm"
                    onClick={(e) => {
                      e.stopPropagation();
                      activeClusterAnchorRef.current = e.currentTarget.closest(".clusterPlayCard");
                      setActiveClusterId(c.id);
                    }}
                  >
                    View stocks
                  </button>
                </div>
              </div>
            ))}
          </div>
        </>
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
            Clustering uses 4 features (log Last, P/E, Discount, 52W Position). Dot size represents market value (bigger = larger holding value).
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

      {!busy && !clusters.length && !error ? <div className="muted" style={{ marginTop: 10 }}>No cluster data yet.</div> : null}

      <Popover
        open={Boolean(activeCluster)}
        anchorRef={activeClusterAnchorRef}
        onClose={() => setActiveClusterId(null)}
        title={activeCluster ? `Cluster ${activeCluster.id} stocks` : "Cluster stocks"}
        ariaLabel="Cluster stocks"
        width={980}
        draggable={false}
        tapToMove={false}
        followPointer={false}
      >
        {activeCluster ? (
          <div className="clusterPopoverBody">
            <div className="clusterPopoverMetrics">
              <div className="clusterMetricChip">
                <span className="clusterMetricLabel">Stocks</span>
                <span className="clusterMetricValue">{activeCluster.items?.length || 0}</span>
              </div>
              <div className="clusterMetricChip">
                <span className="clusterMetricLabel">Avg P/E</span>
                <span className="clusterMetricValue">{fmt(activeCluster.avg_pe)}</span>
              </div>
              <div className="clusterMetricChip">
                <span className="clusterMetricLabel">Avg Disc</span>
                <span className="clusterMetricValue">{fmt(activeCluster.avg_discount_pct)}%</span>
              </div>
              <div className="clusterMetricChip">
                <span className="clusterMetricLabel">Avg Pos</span>
                <span className="clusterMetricValue">{fmt(activeCluster.avg_position_pct)}%</span>
              </div>
            </div>
            <div className="table">
              <div className="row head clusterModalGrid">
                <div>Symbol</div>
                <div>Sector</div>
                <div className="right">P/E</div>
                <div className="right">Disc</div>
              </div>
              <div className="clusterRowsViewport">
                {(activeCluster.items || []).map((it) => (
                  <div key={`${activeCluster.id}:${it.portfolio_id}:${it.symbol}`} className="row clusterModalGrid">
                    <div className="mono strong" data-label="Symbol">{it.symbol}</div>
                    <div className="muted" data-label="Sector">{it.sector || "--"}</div>
                    <div className="right" data-label="P/E">{fmt(it.pe)}</div>
                    <div className="right" data-label="Disc">{fmt(it.discount_from_52w_high_pct)}%</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : null}
      </Popover>
    </div>
  );
}

function PortfolioPEChart({ portfolioId }) {
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState("");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState("opportunity");

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

  const rows = useMemo(() => {
    const holdings = data?.holdings || [];
    return holdings
      .map((h) => ({
        symbol: String(h.symbol || ""),
        name: String(h.name || ""),
        pe: h.pe === null || h.pe === undefined ? null : Number(h.pe),
        weight: h.weight === null || h.weight === undefined ? null : Number(h.weight),
        discount: h.discount_from_52w_high_pct === null || h.discount_from_52w_high_pct === undefined
          ? null
          : Number(h.discount_from_52w_high_pct),
      }))
      .filter((p) => p.pe !== null && Number.isFinite(p.pe))
      .map((p) => {
        let band = "Unknown";
        let suggestion = "Review";
        let bandClass = "neutral";
        if (p.pe <= 15) {
          band = "Value";
          suggestion = "Accumulation Candidate";
          bandClass = "pos";
        } else if (p.pe <= 30) {
          band = "Fair";
          suggestion = "Hold / Add on Dips";
          bandClass = "neutral";
        } else if (p.pe <= 60) {
          band = "Growth";
          suggestion = "Hold with Risk Control";
          bandClass = "neutral";
        } else {
          band = "High";
          suggestion = "High Valuation Risk";
          bandClass = "neg";
        }
        const discountPart = Number.isFinite(p.discount) ? Math.max(0, Math.min(40, p.discount)) : 0;
        const pePart = Math.max(0, Math.min(40, 40 - Math.max(0, p.pe - 10)));
        const weightPart = Number.isFinite(p.weight) ? Math.max(0, 20 - Math.min(20, p.weight * 100)) : 10;
        const opportunityScore = Math.round(discountPart + pePart + weightPart);
        return { ...p, band, suggestion, bandClass, opportunityScore };
      });
  }, [data]);

  const filteredRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    const base = q
      ? rows.filter((r) => r.symbol.toLowerCase().includes(q) || r.name.toLowerCase().includes(q))
      : rows;
    const copy = [...base];
    copy.sort((a, b) => {
      if (sortBy === "pe") return (a.pe || 0) - (b.pe || 0);
      if (sortBy === "weight") return (b.weight || 0) - (a.weight || 0);
      return (b.opportunityScore || 0) - (a.opportunityScore || 0);
    });
    return copy;
  }, [rows, search, sortBy]);

  const summary = useMemo(() => {
    const total = rows.length;
    const highRisk = rows.filter((r) => r.pe > 60).length;
    const valueCount = rows.filter((r) => r.pe <= 15).length;
    const top = [...rows].sort((a, b) => (b.opportunityScore || 0) - (a.opportunityScore || 0))[0] || null;
    return { total, highRisk, valueCount, top };
  }, [rows]);

  return (
    <div className="transactionsChartBody" style={{ marginTop: 10 }}>
      {busy ? <ModuleLoader title="Analyzing P/E structure" hint="Scoring valuation bands and opportunities..." /> : null}
      {err ? <div className="error">{err}</div> : null}
      {!busy && rows.length === 0 ? <div className="muted">No P/E values available for holdings yet.</div> : null}

      {rows.length ? (
        <div className="peInsightGrid">
          <div className="peDecisionCard">
            <div className="kpiLabel">Stocks with P/E</div>
            <div className="kpiValue">{summary.total}</div>
          </div>
          <div className="peDecisionCard">
            <div className="kpiLabel">Value Zone (P/E &lt;= 15)</div>
            <div className="kpiValue pos">{summary.valueCount}</div>
          </div>
          <div className="peDecisionCard">
            <div className="kpiLabel">High Risk (P/E &gt; 60)</div>
            <div className="kpiValue neg">{summary.highRisk}</div>
          </div>
          <div className="peDecisionCard">
            <div className="kpiLabel">Top Opportunity</div>
            <div className="kpiValue">{summary.top?.symbol || "--"}</div>
            <div className="muted small">{summary.top ? `Score ${summary.top.opportunityScore}` : ""}</div>
          </div>
        </div>
      ) : null}

      {rows.length ? (
        <>
          <div className="twoCol" style={{ marginTop: 10 }}>
            <label className="label" style={{ marginTop: 0 }}>
              Search
              <input className="input" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Symbol or name" />
            </label>
            <label className="label" style={{ marginTop: 0 }}>
              Sort by
              <select className="input" value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
                <option value="opportunity">Opportunity Score</option>
                <option value="pe">Lowest P/E first</option>
                <option value="weight">Highest weight first</option>
              </select>
            </label>
          </div>

          <div className="peTableWrap">
            <div className="table">
              <div className="row head" style={{ gridTemplateColumns: "1fr 1.4fr 0.7fr 0.8fr 0.9fr 1fr 1fr 0.9fr" }}>
                <div>Symbol</div>
                <div>Name</div>
                <div className="right">P/E</div>
                <div className="right">Weight</div>
                <div className="right">Discount</div>
                <div>Band</div>
                <div>Suggestion</div>
                <div className="right">Score</div>
              </div>
              <div className="peRowsViewport">
                {filteredRows.map((r) => (
                  <div className="row" key={r.symbol} style={{ gridTemplateColumns: "1fr 1.4fr 0.7fr 0.8fr 0.9fr 1fr 1fr 0.9fr" }}>
                    <div className="mono">{r.symbol}</div>
                    <div title={r.name}>{r.name}</div>
                    <div className="right">{fmt(r.pe)}</div>
                    <div className="right">{r.weight === null ? "--" : `${fmt((r.weight || 0) * 100)}%`}</div>
                    <div className="right">{r.discount === null ? "--" : `${fmt(r.discount)}%`}</div>
                    <div className={r.bandClass}>{r.band}</div>
                    <div className="muted small">{r.suggestion}</div>
                    <div className="right strong">{r.opportunityScore}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      ) : null}
      <div className="muted small" style={{ marginTop: 10 }}>
        Decision guide: lower P/E with healthy discount can indicate better entry zones; very high P/E needs stricter risk control.
      </div>
    </div>
  );
}

function PortfolioDiscountChartLegacy({ portfolioId }) {
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState("");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState("opportunity");

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

  const rows = useMemo(() => {
    const holdings = data?.holdings || [];
    return holdings
      .map((h) => ({
        symbol: String(h.symbol || ""),
        name: String(h.name || ""),
        discount: h.discount_from_52w_high_pct === null || h.discount_from_52w_high_pct === undefined
          ? null
          : Number(h.discount_from_52w_high_pct),
        pe: h.pe === null || h.pe === undefined ? null : Number(h.pe),
        weight: h.weight === null || h.weight === undefined ? null : Number(h.weight),
      }))
      .filter((p) => p.discount !== null && Number.isFinite(p.discount))
      .map((p) => {
        let zone = "Unknown";
        let suggestion = "Review";
        let zoneClass = "neutral";
        if (p.discount >= 30) {
          zone = "Deep Discount";
          suggestion = "High upside if fundamentals hold";
          zoneClass = "pos";
        } else if (p.discount >= 15) {
          zone = "Healthy Discount";
          suggestion = "Good watchlist candidate";
          zoneClass = "neutral";
        } else if (p.discount >= 5) {
          zone = "Near Fair";
          suggestion = "Hold / staggered entry";
          zoneClass = "neutral";
        } else {
          zone = "Near 52W High";
          suggestion = "Momentum zone, manage risk";
          zoneClass = "neg";
        }
        const discountPart = Math.max(0, Math.min(60, p.discount || 0));
        const pePart = Number.isFinite(p.pe) ? Math.max(0, Math.min(25, 35 - (p.pe || 0) / 2)) : 12;
        const weightPart = Number.isFinite(p.weight) ? Math.max(0, 15 - Math.min(15, (p.weight || 0) * 100)) : 8;
        const opportunityScore = Math.round(discountPart + pePart + weightPart);
        return { ...p, zone, suggestion, zoneClass, opportunityScore };
      });
  }, [data]);

  const filteredRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    const base = q
      ? rows.filter((r) => r.symbol.toLowerCase().includes(q) || r.name.toLowerCase().includes(q))
      : rows;
    const copy = [...base];
    copy.sort((a, b) => {
      if (sortBy === "discount") return (b.discount || 0) - (a.discount || 0);
      if (sortBy === "pe") return (a.pe || 0) - (b.pe || 0);
      return (b.opportunityScore || 0) - (a.opportunityScore || 0);
    });
    return copy;
  }, [rows, search, sortBy]);

  const summary = useMemo(() => {
    const total = rows.length;
    const deep = rows.filter((r) => (r.discount || 0) >= 30).length;
    const nearHigh = rows.filter((r) => (r.discount || 0) < 5).length;
    const top = [...rows].sort((a, b) => (b.opportunityScore || 0) - (a.opportunityScore || 0))[0] || null;
    return { total, deep, nearHigh, top };
  }, [rows]);

  return (
    <div className="transactionsChartBody" style={{ marginTop: 10 }}>
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

function PortfolioDiscountChart({ portfolioId }) {
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState("");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState("opportunity");

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

  const rows = useMemo(() => {
    const holdings = data?.holdings || [];
    return holdings
      .map((h) => ({
        symbol: String(h.symbol || ""),
        name: String(h.name || ""),
        discount: h.discount_from_52w_high_pct === null || h.discount_from_52w_high_pct === undefined
          ? null
          : Number(h.discount_from_52w_high_pct),
        pe: h.pe === null || h.pe === undefined ? null : Number(h.pe),
        weight: h.weight === null || h.weight === undefined ? null : Number(h.weight),
      }))
      .filter((p) => p.discount !== null && Number.isFinite(p.discount))
      .map((p) => {
        let zone = "Unknown";
        let suggestion = "Review";
        let zoneClass = "neutral";
        if (p.discount >= 30) {
          zone = "Deep Discount";
          suggestion = "High upside if fundamentals hold";
          zoneClass = "pos";
        } else if (p.discount >= 15) {
          zone = "Healthy Discount";
          suggestion = "Good watchlist candidate";
          zoneClass = "neutral";
        } else if (p.discount >= 5) {
          zone = "Near Fair";
          suggestion = "Hold / staggered entry";
          zoneClass = "neutral";
        } else {
          zone = "Near 52W High";
          suggestion = "Momentum zone, manage risk";
          zoneClass = "neg";
        }
        const discountPart = Math.max(0, Math.min(60, p.discount || 0));
        const pePart = Number.isFinite(p.pe) ? Math.max(0, Math.min(25, 35 - (p.pe || 0) / 2)) : 12;
        const weightPart = Number.isFinite(p.weight) ? Math.max(0, 15 - Math.min(15, (p.weight || 0) * 100)) : 8;
        const opportunityScore = Math.round(discountPart + pePart + weightPart);
        return { ...p, zone, suggestion, zoneClass, opportunityScore };
      });
  }, [data]);

  const filteredRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    const base = q
      ? rows.filter((r) => r.symbol.toLowerCase().includes(q) || r.name.toLowerCase().includes(q))
      : rows;
    const copy = [...base];
    copy.sort((a, b) => {
      if (sortBy === "discount") return (b.discount || 0) - (a.discount || 0);
      if (sortBy === "pe") return (a.pe || 0) - (b.pe || 0);
      return (b.opportunityScore || 0) - (a.opportunityScore || 0);
    });
    return copy;
  }, [rows, search, sortBy]);

  const summary = useMemo(() => {
    const total = rows.length;
    const deep = rows.filter((r) => (r.discount || 0) >= 30).length;
    const nearHigh = rows.filter((r) => (r.discount || 0) < 5).length;
    const top = [...rows].sort((a, b) => (b.opportunityScore || 0) - (a.opportunityScore || 0))[0] || null;
    return { total, deep, nearHigh, top };
  }, [rows]);

  return (
    <div className="transactionsChartBody" style={{ marginTop: 10 }}>
      {busy ? <ModuleLoader title="Computing discount zones" hint="Evaluating 52W discount opportunities..." /> : null}
      {err ? <div className="error">{err}</div> : null}
      {!busy && rows.length === 0 ? <div className="muted">No discount values yet (needs 52W high + last price).</div> : null}

      {rows.length ? (
        <div className="discountInsightGrid">
          <div className="discountDecisionCard cardA">
            <div className="kpiLabel">Stocks with Discount</div>
            <div className="kpiValue">{summary.total}</div>
          </div>
          <div className="discountDecisionCard cardB">
            <div className="kpiLabel">Deep Discount (&gt;= 30%)</div>
            <div className="kpiValue pos">{summary.deep}</div>
          </div>
          <div className="discountDecisionCard cardC">
            <div className="kpiLabel">Near 52W High (&lt; 5%)</div>
            <div className="kpiValue neg">{summary.nearHigh}</div>
          </div>
          <div className="discountDecisionCard cardD">
            <div className="kpiLabel">Top Opportunity</div>
            <div className="kpiValue">{summary.top?.symbol || "--"}</div>
            <div className="muted small">{summary.top ? `Score ${summary.top.opportunityScore}` : ""}</div>
          </div>
        </div>
      ) : null}

      {rows.length ? (
        <>
          <div className="twoCol" style={{ marginTop: 10 }}>
            <label className="label" style={{ marginTop: 0 }}>
              Search
              <input className="input" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Symbol or name" />
            </label>
            <label className="label" style={{ marginTop: 0 }}>
              Sort by
              <select className="input" value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
                <option value="opportunity">Opportunity Score</option>
                <option value="discount">Highest Discount first</option>
                <option value="pe">Lowest P/E first</option>
              </select>
            </label>
          </div>

          <div className="discountTableWrap">
            <div className="table">
              <div className="row head" style={{ gridTemplateColumns: "1fr 1.4fr 0.9fr 0.7fr 0.8fr 1fr 1.2fr 0.9fr" }}>
                <div>Symbol</div>
                <div>Name</div>
                <div className="right">Discount</div>
                <div className="right">P/E</div>
                <div className="right">Weight</div>
                <div>Zone</div>
                <div>Suggestion</div>
                <div className="right">Score</div>
              </div>
              <div className="discountRowsViewport">
                {filteredRows.map((r) => (
                  <div className="row" key={r.symbol} style={{ gridTemplateColumns: "1fr 1.4fr 0.9fr 0.7fr 0.8fr 1fr 1.2fr 0.9fr" }}>
                    <div className="mono">{r.symbol}</div>
                    <div title={r.name}>{r.name}</div>
                    <div className="right strong">{fmt(r.discount)}%</div>
                    <div className="right">{r.pe === null ? "--" : fmt(r.pe)}</div>
                    <div className="right">{r.weight === null ? "--" : `${fmt((r.weight || 0) * 100)}%`}</div>
                    <div className={r.zoneClass}>{r.zone}</div>
                    <div className="muted small">{r.suggestion}</div>
                    <div className="right strong">{r.opportunityScore}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      ) : null}

      <div className="muted small" style={{ marginTop: 10 }}>
        Decision guide: higher discount can indicate value entry zones, but combine with P/E and concentration before adding aggressively.
      </div>
    </div>
  );
}

function PortfolioForecastChart({ portfolioId }) {
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState("");
  const [activeModel, setActiveModel] = useState("ensemble");

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

  const baseSeries = useMemo(() => {
    const s = data?.series || [];
    return s.map((p, idx) => ({
      date: p.date,
      y: Number(p.portfolio_value),
      i: idx
    })).filter((p) => Number.isFinite(p.y));
  }, [data]);

  const modelBundle = useMemo(() => {
    if (!baseSeries.length) return null;
    const start = baseSeries[0].y;
    const end = baseSeries[baseSeries.length - 1].y;
    const n = Math.max(1, baseSeries.length - 1);
    const avgStep = (end - start) / n;
    const trendStrength = Math.min(0.2, Math.abs((end - start) / Math.max(1, start)));
    const volProxy = Math.max(0.03, Math.min(0.18, trendStrength * 1.4 + 0.04));

    const project = (factorFn) => baseSeries.map((p, idx) => {
      const t = n === 0 ? 0 : idx / n;
      const base = p.y;
      return {
        ...p,
        y: base * factorFn(t, idx),
      };
    });

    const conservative = project((t) => 1 - volProxy * 0.6 * t);
    const momentum = project((t, idx) => {
      const accel = 1 + (avgStep / Math.max(1, start)) * idx * 0.6;
      return Math.max(0.5, accel + trendStrength * 0.5 * t);
    });
    const meanReversion = project((t) => {
      const pullToMean = 1 - (trendStrength * 0.9) * t + (volProxy * 0.35) * (1 - t);
      return Math.max(0.55, pullToMean);
    });
    const ensemble = baseSeries.map((p, idx) => ({
      ...p,
      y: (conservative[idx].y * 0.35) + (momentum[idx].y * 0.4) + (meanReversion[idx].y * 0.25)
    }));

    const models = {
      conservative,
      momentum,
      meanReversion,
      ensemble
    };

    const summarize = (key, label, risk) => {
      const series = models[key];
      const startV = series[0]?.y ?? null;
      const endV = series[series.length - 1]?.y ?? null;
      const ret = startV && endV ? ((endV - startV) / startV) * 100 : null;
      return { key, label, risk, startV, endV, ret };
    };

    const summary = [
      summarize("conservative", "Conservative", "Low"),
      summarize("ensemble", "Ensemble", "Balanced"),
      summarize("meanReversion", "Mean Reversion", "Medium"),
      summarize("momentum", "Momentum", "High")
    ];

    const endValues = summary.map((s) => s.endV).filter((v) => Number.isFinite(v));
    const spread = endValues.length ? ((Math.max(...endValues) - Math.min(...endValues)) / Math.max(1, start)) * 100 : 0;
    const ensembleRet = summary.find((s) => s.key === "ensemble")?.ret ?? 0;
    const decision = ensembleRet > 4
      ? "Accumulation bias"
      : ensembleRet > 0
        ? "Selective hold/add"
        : "Defensive posture";
    const confidence = Math.max(25, Math.min(92, Math.round(86 - spread * 2.2)));

    return {
      models,
      summary,
      spread,
      decision,
      confidence,
      ensembleRet
    };
  }, [baseSeries]);

  const chartData = useMemo(() => {
    if (!modelBundle) return null;
    const modelNames = ["conservative", "meanReversion", "momentum", "ensemble"];
    const modelColors = {
      conservative: "#36d08e",
      meanReversion: "#f5b946",
      momentum: "#f96a8b",
      ensemble: "#7ab5ff"
    };
    const all = modelNames.flatMap((k) => modelBundle.models[k] || []);
    const ys = all.map((p) => p.y).filter((v) => Number.isFinite(v));
    const minY = ys.length ? Math.min(...ys) : 0;
    const maxY = ys.length ? Math.max(...ys) : 1;
    const spanY = maxY - minY || 1;
    const w = 980;
    const h = 310;
    const padL = 62;
    const padR = 20;
    const padT = 22;
    const padB = 52;
    const innerW = w - padL - padR;
    const innerH = h - padT - padB;

    const toCoord = (idx, yVal, seriesLen = baseSeries.length) => {
      const x = padL + (idx / Math.max(1, seriesLen - 1)) * innerW;
      const y = padT + (1 - (yVal - minY) / spanY) * innerH;
      return { x, y };
    };

    const toPath = (pts) => pts.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(" ");
    const areaToBottom = (pts) => {
      if (!pts.length) return "";
      const start = pts[0];
      const end = pts[pts.length - 1];
      const bottomY = padT + innerH;
      return `${toPath(pts)} L ${end.x.toFixed(2)} ${bottomY.toFixed(2)} L ${start.x.toFixed(2)} ${bottomY.toFixed(2)} Z`;
    };

    const modelPoints = {};
    for (const key of modelNames) {
      const s = modelBundle.models[key] || [];
      modelPoints[key] = s.map((p, idx) => {
        const c = toCoord(idx, p.y, s.length);
        return { ...c, yValue: p.y, date: p.date };
      });
    }

    const modelPath = (key) => {
      const pts = modelPoints[key] || [];
      if (pts.length < 2) return "";
      return toPath(pts);
    };

    const modelAreaPath = (key) => {
      const pts = modelPoints[key] || [];
      if (pts.length < 2) return "";
      return areaToBottom(pts);
    };

    const coneTop = [];
    const coneBottom = [];
    for (let i = 0; i < baseSeries.length; i += 1) {
      const vals = modelNames
        .map((k) => modelBundle.models[k]?.[i]?.y)
        .filter((v) => Number.isFinite(v));
      if (!vals.length) continue;
      const hi = Math.max(...vals);
      const lo = Math.min(...vals);
      const topC = toCoord(i, hi, baseSeries.length);
      const bottomC = toCoord(i, lo, baseSeries.length);
      coneTop.push(topC);
      coneBottom.push(bottomC);
    }

    const conePath = coneTop.length > 1 && coneBottom.length > 1
      ? `${toPath(coneTop)} ${toPath([...coneBottom].reverse()).replace(/^M\s/, "L ")} Z`
      : "";

    const modelEndPoints = {};
    for (const key of modelNames) {
      const pts = modelPoints[key] || [];
      if (pts.length) modelEndPoints[key] = pts[pts.length - 1];
    }

    const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => minY + spanY * (1 - t));
    const xTicks = [0, Math.floor((baseSeries.length - 1) / 2), baseSeries.length - 1].filter((v, i, a) => a.indexOf(v) === i);

    return {
      modelNames,
      modelColors,
      minY,
      maxY,
      spanY,
      w,
      h,
      padL,
      padR,
      padT,
      padB,
      innerW,
      innerH,
      modelPath,
      modelAreaPath,
      modelEndPoints,
      conePath,
      ticks,
      xTicks
    };
  }, [modelBundle, baseSeries]);

  const modelSummary = useMemo(() => {
    if (!modelBundle) return [];
    return [...modelBundle.summary].sort((a, b) => (b.ret || -999) - (a.ret || -999));
  }, [modelBundle]);

  const activeSeries = useMemo(() => {
    if (!modelBundle) return [];
    return modelBundle.models[activeModel] || [];
  }, [modelBundle, activeModel]);

  const activeMeta = useMemo(() => {
    return modelSummary.find((m) => m.key === activeModel) || null;
  }, [modelSummary, activeModel]);

  const yTicks = useMemo(() => {
    if (!chartData) return [];
    return chartData.ticks.map((t) => ({
      value: t,
      y: chartData.padT + (1 - (t - chartData.minY) / chartData.spanY) * chartData.innerH
    }));
  }, [chartData]);

  return (
    <div className="transactionsChartBody" style={{ marginTop: 10 }}>
      {busy ? <ModuleLoader title="Running forecast models" hint="Generating multi-model outlook and confidence..." /> : null}
      {err ? <div className="error">{err}</div> : null}
      {!busy && !baseSeries.length ? <div className="muted">No forecast available (add holdings first).</div> : null}

      {baseSeries.length && modelBundle && chartData ? (
        <>
          <div className="forecastInsightGrid">
            <div className="forecastDecisionCard cardA">
              <div className="kpiLabel">Decision</div>
              <div className="kpiValue">{modelBundle.decision}</div>
            </div>
            <div className="forecastDecisionCard cardB">
              <div className="kpiLabel">Ensemble Return</div>
              <div className={`kpiValue ${modelBundle.ensembleRet >= 0 ? "pos" : "neg"}`}>{fmt(round2(modelBundle.ensembleRet))}%</div>
            </div>
            <div className="forecastDecisionCard cardC">
              <div className="kpiLabel">Model Spread Risk</div>
              <div className={`kpiValue ${modelBundle.spread > 8 ? "neg" : "neutral"}`}>{fmt(round2(modelBundle.spread))}%</div>
            </div>
            <div className="forecastDecisionCard cardD">
              <div className="kpiLabel">Confidence</div>
              <div className="kpiValue">{modelBundle.confidence}%</div>
            </div>
          </div>

          <div className="forecastModelTabs">
            {modelSummary.map((m) => (
              <button
                key={m.key}
                type="button"
                className={`forecastModelChip ${activeModel === m.key ? "active" : ""}`}
                onClick={() => setActiveModel(m.key)}
              >
                {m.label}
              </button>
            ))}
          </div>

          <div className="forecastVizWrap">
            <svg className="forecastVizSvg" viewBox={`0 0 ${chartData.w} ${chartData.h}`} preserveAspectRatio="none" role="img" aria-label="Forecast models chart">
              <defs>
                <linearGradient id="forecastBandUp" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="rgba(67,212,136,0.20)" />
                  <stop offset="100%" stopColor="rgba(67,212,136,0.04)" />
                </linearGradient>
                <linearGradient id="forecastBandDown" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="rgba(255,107,107,0.06)" />
                  <stop offset="100%" stopColor="rgba(255,107,107,0.18)" />
                </linearGradient>
                <linearGradient id="forecastConeGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="rgba(122,181,255,0.22)" />
                  <stop offset="100%" stopColor="rgba(122,181,255,0.06)" />
                </linearGradient>
                <linearGradient id="forecastActiveArea" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="rgba(122,181,255,0.30)" />
                  <stop offset="100%" stopColor="rgba(122,181,255,0.03)" />
                </linearGradient>
                <filter id="forecastGlow" x="-30%" y="-30%" width="160%" height="160%">
                  <feGaussianBlur stdDeviation="4.5" result="blur" />
                  <feMerge>
                    <feMergeNode in="blur" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
              </defs>

              <rect x={chartData.padL} y={chartData.padT} width={chartData.innerW} height={chartData.innerH} fill="rgba(255,255,255,0.02)" rx="12" />
              <rect x={chartData.padL} y={chartData.padT} width={chartData.innerW} height={chartData.innerH * 0.45} fill="url(#forecastBandUp)" />
              <rect x={chartData.padL} y={chartData.padT + chartData.innerH * 0.45} width={chartData.innerW} height={chartData.innerH * 0.55} fill="url(#forecastBandDown)" />
              {chartData.conePath ? <path d={chartData.conePath} fill="url(#forecastConeGrad)" /> : null}
              {chartData.modelAreaPath(activeModel) ? <path d={chartData.modelAreaPath(activeModel)} fill="url(#forecastActiveArea)" /> : null}

              {yTicks.map((t, idx) => (
                <g key={idx}>
                  <line x1={chartData.padL} y1={t.y} x2={chartData.w - chartData.padR} y2={t.y} className="histGrid" />
                  <text x={chartData.padL - 10} y={t.y} className="histTick" textAnchor="end" dominantBaseline="middle">
                    {fmt(t.value)}
                  </text>
                </g>
              ))}

              {chartData.xTicks.map((idx) => {
                const x = chartData.padL + ((idx || 0) / Math.max(1, baseSeries.length - 1)) * chartData.innerW;
                return (
                  <g key={idx}>
                    <line x1={x} y1={chartData.padT + chartData.innerH} x2={x} y2={chartData.padT + chartData.innerH + 6} className="histAxis" />
                    <text x={x} y={chartData.padT + chartData.innerH + 18} className="histTick" textAnchor="middle">
                      {baseSeries[idx]?.date || ""}
                    </text>
                  </g>
                );
              })}

              {chartData.modelNames.map((k) => (
                <path
                  key={k}
                  d={chartData.modelPath(k)}
                  fill="none"
                  stroke={chartData.modelColors[k]}
                  strokeWidth={k === activeModel ? 3.8 : 2}
                  strokeOpacity={k === activeModel ? 1 : 0.45}
                  strokeLinecap="round"
                />
              ))}
              {chartData.modelPath(activeModel) ? (
                <path
                  d={chartData.modelPath(activeModel)}
                  fill="none"
                  stroke={chartData.modelColors[activeModel]}
                  strokeWidth={2.2}
                  strokeOpacity={0.95}
                  strokeLinecap="round"
                  filter="url(#forecastGlow)"
                />
              ) : null}
              {chartData.modelNames.map((k) => {
                const p = chartData.modelEndPoints[k];
                if (!p) return null;
                return (
                  <g key={`${k}-end`}>
                    <circle cx={p.x} cy={p.y} r={k === activeModel ? 5 : 3.5} fill={chartData.modelColors[k]} opacity={k === activeModel ? 1 : 0.75} />
                  </g>
                );
              })}
            </svg>
          </div>

          <div className="forecastLegend">
            {chartData.modelNames.map((k) => (
              <div key={k} className="forecastLegendItem">
                <span className="forecastLegendDot" style={{ background: chartData.modelColors[k] }} />
                <span className={k === activeModel ? "strong" : "muted"}>
                  {modelSummary.find((m) => m.key === k)?.label || k}
                </span>
              </div>
            ))}
          </div>

          <div className="forecastTableWrap">
            <div className="table">
              <div className="row head" style={{ gridTemplateColumns: "1.2fr 0.7fr 1fr 1fr 0.9fr" }}>
                <div>Model</div>
                <div>Risk</div>
                <div className="right">Start</div>
                <div className="right">End (90d)</div>
                <div className="right">Return</div>
              </div>
              {modelSummary.map((m) => (
                <div className="row" key={m.key} style={{ gridTemplateColumns: "1.2fr 0.7fr 1fr 1fr 0.9fr" }}>
                  <div className={m.key === activeModel ? "strong" : ""}>{m.label}</div>
                  <div>{m.risk}</div>
                  <div className="right">{fmt(round2(m.startV))}</div>
                  <div className="right">{fmt(round2(m.endV))}</div>
                  <div className={`right strong ${(m.ret || 0) >= 0 ? "pos" : "neg"}`}>{fmt(round2(m.ret))}%</div>
                </div>
              ))}
            </div>
          </div>

          {activeMeta && activeSeries.length ? (
            <div className="forecastNarrative">
              <div className="strong">{activeMeta.label} model outlook</div>
              <div className="muted small" style={{ marginTop: 4 }}>
                Expected move over 90 days: <span className={activeMeta.ret >= 0 ? "pos strong" : "neg strong"}>{fmt(round2(activeMeta.ret))}%</span>.
                Suggested posture: {modelBundle.decision}. Use model spread ({fmt(round2(modelBundle.spread))}%) as risk budget signal.
              </div>
            </div>
          ) : null}
        </>
      ) : null}

      <div className="muted small" style={{ marginTop: 10 }}>
        {data?.disclaimer || "Educational forecast using multiple heuristic models. Not investment advice."}
      </div>
    </div>
  );
}
