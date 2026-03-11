import React, { useEffect, useState } from "react";
import { api, clearTokens } from "../api.js";
import { Link, useNavigate } from "react-router-dom";
import NavBar from "../components/NavBar.jsx";
import Footer from "../components/Footer.jsx";

const DASHBOARD_CACHE_KEY = "dashboard_summary_cache_v1";

function fmt(n) {
  if (n === null || n === undefined) return "--";
  const num = Number(n);
  if (Number.isNaN(num)) return "--";
  return num.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function loadDashboardCache() {
  try {
    const raw = localStorage.getItem(DASHBOARD_CACHE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveDashboardCache(data) {
  try {
    localStorage.setItem(DASHBOARD_CACHE_KEY, JSON.stringify({ savedAt: Date.now(), data }));
  } catch {
    // ignore
  }
}

export default function Dashboard() {
  const nav = useNavigate();
  const cachedDashboard = loadDashboardCache()?.data || null;
  const [me, setMe] = useState(cachedDashboard?.user || null);
  const [portfolios, setPortfolios] = useState(cachedDashboard?.portfolios || []);
  const [summary, setSummary] = useState(cachedDashboard);
  const [name, setName] = useState("My Portfolio");
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState(null);
  const [infoKey, setInfoKey] = useState("");
  const [marketFetchedAt, setMarketFetchedAt] = useState(() => loadDashboardCache()?.savedAt || null);

  useEffect(() => {
    refreshSummary(false);
  }, [nav]);

  useEffect(() => {
    // keep the dashboard snappy; portfolios are loaded via summary
  }, []);

  async function refreshSummary(force = false) {
    try {
      const d = await api.dashboardSummary(force);
      setMe(d.user);
      setSummary(d);
      setPortfolios(d.portfolios || []);
      setMarketFetchedAt(Date.now());
      saveDashboardCache(d);
    } catch {
      clearTokens();
      nav("/");
    }
  }

  async function create() {
    setError("");
    try {
      const p = await api.createPortfolio({ name });
      setPortfolios((prev) => {
        const next = [p, ...prev];
        setSummary((s) => {
          const updated = s ? { ...s, portfolios: next, kpis: { ...s.kpis, portfolios: (s.kpis?.portfolios || 0) + 1 } } : s;
          if (updated) saveDashboardCache(updated);
          return updated;
        });
        return next;
      });
      nav(`/portfolio/${p.id}`);
    } catch (e) {
      setError(e.message || "Failed to create portfolio");
    }
  }

  function logout() {
    clearTokens();
    nav("/");
  }

  async function deletePortfolio(id) {
    const ok = window.confirm("Delete this portfolio? This will remove holdings and transactions.");
    if (!ok) return;
    setBusyId(id);
    setError("");
    try {
      await api.deletePortfolio(id);
      setPortfolios((prev) => {
        const next = prev.filter((p) => p.id !== id);
        setSummary((s) => {
          const updated = s ? { ...s, portfolios: next, kpis: { ...s.kpis, portfolios: Math.max(0, (s.kpis?.portfolios || 1) - 1) } } : s;
          if (updated) saveDashboardCache(updated);
          return updated;
        });
        return next;
      });
    } catch (e) {
      setError(e.message || "Failed to delete portfolio");
    } finally {
      setBusyId(null);
    }
  }

  function calcMove(last, prev) {
    const l = Number(last);
    const p = Number(prev);
    if (!Number.isFinite(l) || !Number.isFinite(p) || p === 0) return { chg: null, pct: null };
    const chg = l - p;
    const pct = (chg / p) * 100;
    return { chg, pct };
  }

  return (
    <div className="page">
      <NavBar
        title="Dashboard"
        subtitle="Overview • Watchlist • Activity • Quick actions"
        links={[
          { to: "/dashboard", label: "Dashboard", end: true },
          { to: "/account", label: "Account" },
          { to: "/", label: "Home" }
        ]}
        actions={
          <button className="btn danger sm" type="button" onClick={logout}>
            Logout
          </button>
        }
      />

      <main className="grid">
        <section className="card hero">
          <h1>
            Welcome <span className="mono">{me?.username || "..."}</span>
          </h1>
          {/* <p className="muted">Like real portfolio apps: you get a quick market glance, portfolio shortcuts, and recent activity in one place.</p> */}
          <div className="kpiRow" style={{ marginTop: 12 }}>
            <button className="kpi kpiClickable" onClick={() => setInfoKey("portfolios")} type="button">
              <div className="kpiLabel">Portfolios</div>
              <div className="kpiValue">{summary?.kpis?.portfolios ?? "--"}</div>
            </button>
            <button className="kpi kpiClickable" onClick={() => setInfoKey("holdings")} type="button">
              <div className="kpiLabel">Holdings</div>
              <div className="kpiValue">{summary?.kpis?.holdings ?? "--"}</div>
            </button>
          </div>
          <div className="kpiRow" style={{ marginTop: 10 }}>
            <button className="kpi kpiClickable" onClick={() => setInfoKey("pnl")} type="button">
              <div className="kpiLabel">Realized P&L</div>
              <div className={(Number(summary?.kpis?.realized_pnl_total) || 0) >= 0 ? "kpiValue pos" : "kpiValue neg"}>
                {fmt(summary?.kpis?.realized_pnl_total)}
              </div>
            </button>
            <button className="kpi kpiClickable" onClick={() => setInfoKey("watchlist")} type="button">
              <div className="kpiLabel">Watchlist / Alerts</div>
              <div className="kpiValue">
                {summary?.kpis?.watchlist ?? 0} / {summary?.kpis?.alerts_active ?? 0}
              </div>
              <div className="muted small" style={{ marginTop: 6 }}>
                Triggered: {summary?.kpis?.alerts_triggered ?? 0}
              </div>
            </button>
          </div>
          <div className="heroActions" style={{ marginTop: 12 }}>
            {summary?.profile?.default_portfolio?.id ? (
              <>
                <Link className="btn primary" to={`/portfolio/${summary.profile.default_portfolio.id}`}>
                  Open default portfolio
                </Link>
                <Link className="btn ghost" to={`/analysis/${summary.profile.default_portfolio.id}`}>
                  Quick analysis
                </Link>
              </>
            ) : (
              <Link className="btn primary" to="/account">
                Set default portfolio
              </Link>
            )}
            <button className="btn ghost" onClick={() => refreshSummary(true).catch(() => {})}>
              Refresh
            </button>
          </div>
        </section>

        <section className="card" id="portfoliosSection">
          <h3>Your Portfolios</h3>
          {error ? <div className="error">{error}</div> : null}
          {portfolios.length === 0 ? <div className="muted">No portfolios yet. Create your first one.</div> : null}
          <div className="list">
            {portfolios.map((p) => (
              <div className="listItemRow" key={p.id}>
                <Link className="listItem" to={`/portfolio/${p.id}`}>
                  <div className="strong">{p.name}</div>
                  <div className="muted small" style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                    <span>Market: {p.market}</span>
                    <span className="mono">#{p.id}</span>
                  </div>
                </Link>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <Link className="btn sm" to={`/analysis/${p.id}`} title="Open analysis">
                    Analysis
                  </Link>
                  <button className="btn danger sm" onClick={() => deletePortfolio(p.id)} disabled={busyId === p.id} title="Delete portfolio">
                    {busyId === p.id ? "..." : "Delete"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="card" id="createPortfolioSection">
          <h3>Create Portfolio</h3>
          <label className="label">
            Name
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <button className="btn primary" onClick={create}>
            Create
          </button>
          <div className="muted small" style={{ marginTop: 10 }}>
            Tip: Keep separate portfolios for sectors (IT, Banking) to make EDA comparisons easy.
          </div>
        </section>

        <section className="card" id="marketSection" style={{ gridColumn: "1 / -1" }}>
          <div className="sectionRow">
            <h3 style={{ margin: 0 }}>Market glance</h3>
            <div className="muted small" style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <span>
                {summary?.meta?.source === "snapshot"
                  ? "Instant from last snapshot"
                  : marketFetchedAt
                    ? `Updated ${new Date(marketFetchedAt).toLocaleTimeString()}`
                    : ""}
              </span>
              <button className="btn ghost sm" type="button" onClick={() => refreshSummary(true).catch(() => {})}>
                Refresh
              </button>
            </div>
          </div>
          <div className="marketGlanceGrid">
            {(() => {
              const nLast = summary?.market?.nifty?.last_price;
              const nPrev = summary?.market?.nifty?.previous_close;
              const nMove = calcMove(nLast, nPrev);
              return (
                <div className="kpi marketKpi">
                  <div className="marketKpiHead">
                    <div className="kpiLabel">Nifty</div>
                    <div className={nMove.pct === null ? "muted small mono" : nMove.pct >= 0 ? "small mono pos" : "small mono neg"}>
                      {nMove.pct === null ? "--" : `${fmt(nMove.pct)}%`}
                    </div>
                  </div>
                  <div className="kpiValue">{fmt(nLast)}</div>
                  <div className="muted small">
                    Prev: {fmt(nPrev)} {nMove.chg === null ? "" : `• Chg: ${fmt(nMove.chg)}`}
                  </div>
                </div>
              );
            })()}

            {(() => {
              const sLast = summary?.market?.sensex?.last_price;
              const sPrev = summary?.market?.sensex?.previous_close;
              const sMove = calcMove(sLast, sPrev);
              return (
                <div className="kpi marketKpi">
                  <div className="marketKpiHead">
                    <div className="kpiLabel">Sensex</div>
                    <div className={sMove.pct === null ? "muted small mono" : sMove.pct >= 0 ? "small mono pos" : "small mono neg"}>
                      {sMove.pct === null ? "--" : `${fmt(sMove.pct)}%`}
                    </div>
                  </div>
                  <div className="kpiValue">{fmt(sLast)}</div>
                  <div className="muted small">
                    Prev: {fmt(sPrev)} {sMove.chg === null ? "" : `• Chg: ${fmt(sMove.chg)}`}
                  </div>
                </div>
              );
            })()}

            <div className="kpi marketInfo">
              <div className="kpiLabel">Notes</div>
              <div className="muted small" style={{ marginTop: 6 }}>
                Data via yfinance (cached). Use Refresh for a “live” feel.
              </div>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 10 }}>
                <Link className="btn sm" to="/account">
                  Watchlist
                </Link>
                {summary?.profile?.default_portfolio?.id ? (
                  <Link className="btn sm" to={`/analysis/${summary.profile.default_portfolio.id}`}>
                    Quick analysis
                  </Link>
                ) : null}
              </div>
            </div>
          </div>
          <div className="muted small" style={{ marginTop: 10 }}>
            Data via yfinance (cached). For a “live” feel we refresh manually (or later polling/WebSocket).
          </div>
        </section>

        <section className="card" id="watchlistPreviewSection" style={{ gridColumn: "1 / -1" }}>
          <h3>Watchlist preview</h3>
          <div className="muted small">Manage full watchlist + alerts in Account.</div>
          <div className="table">
            <div className="row head" style={{ gridTemplateColumns: "1.2fr 2fr 0.8fr 0.8fr" }}>
              <div>Symbol</div>
              <div>Name</div>
              <div className="right">Last</div>
              <div className="right">Action</div>
            </div>
            {(summary?.watchlist_preview || []).map((w) => (
              <div className="row" key={w.id} style={{ gridTemplateColumns: "1.2fr 2fr 0.8fr 0.8fr" }}>
                <div className="mono">{w.symbol}</div>
                <div>{w.name}</div>
                <div className="right">{w.last_price ?? "--"}</div>
                <div className="right">
                  <Link className="btn sm" to="/account">
                    Open
                  </Link>
                </div>
              </div>
            ))}
          </div>
          {(summary?.watchlist_preview || []).length === 0 ? <div className="muted" style={{ marginTop: 10 }}>No watchlist items yet.</div> : null}
        </section>

        <section className="card" id="recentActivitySection" style={{ gridColumn: "1 / -1" }}>
          <h3>Recent activity</h3>
          <div className="muted small">Recent BUY/SELL transactions across all portfolios.</div>
          <div className="table">
            <div className="row head" style={{ gridTemplateColumns: "1.2fr 1fr 0.8fr 0.8fr 1.4fr" }}>
              <div>Symbol</div>
              <div>Side</div>
              <div className="right">Qty</div>
              <div className="right">Price</div>
              <div>Portfolio</div>
            </div>
            {(summary?.recent_transactions || []).map((t) => (
              <div className="row" key={t.id} style={{ gridTemplateColumns: "1.2fr 1fr 0.8fr 0.8fr 1.4fr" }}>
                <div className="mono">{t.symbol}</div>
                <div className={t.side === "BUY" ? "pos" : "neg"}>{t.side}</div>
                <div className="right">{t.qty}</div>
                <div className="right">{fmt(t.price)}</div>
                <div>
                  <Link className="link" to={`/portfolio/${t.portfolio_id}`}>
                    {t.portfolio_name}
                  </Link>
                </div>
              </div>
            ))}
          </div>
          {(summary?.recent_transactions || []).length === 0 ? <div className="muted" style={{ marginTop: 10 }}>No transactions yet.</div> : null}
        </section>
      </main>

      <Footer />

      <InfoModal
        open={Boolean(infoKey)}
        infoKey={infoKey}
        summary={summary}
        onClose={() => setInfoKey("")}
      />
    </div>
  );
}

function InfoModal({ open, infoKey, summary, onClose }) {
  const nav = useNavigate();
  if (!open) return null;

  function scrollTo(id) {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const items = {
    portfolios: {
      title: "Portfolios",
      body: "Portfolios are separate baskets of holdings (example: IT portfolio, Banking portfolio). Use them to compare EDA results by theme/sector.",
      actions: [
        { label: "Go to portfolios", primary: true, onClick: () => { onClose(); scrollTo("portfoliosSection"); } },
        { label: "Create portfolio", onClick: () => { onClose(); scrollTo("createPortfolioSection"); } }
      ]
    },
    holdings: {
      title: "Holdings",
      body: "Holdings are the stocks you currently own (qty > 0). They come from your BUY/SELL transactions.",
      actions: summary?.profile?.default_portfolio?.id
        ? [
            { label: "Open default portfolio", primary: true, onClick: () => { onClose(); nav(`/portfolio/${summary.profile.default_portfolio.id}`); } }
          ]
        : [{ label: "Set default portfolio", primary: true, onClick: () => { onClose(); nav("/account"); } }]
    },
    pnl: {
      title: "Realized P&L",
      body: "Realized P&L is profit/loss from SELL trades only. Unrealized P&L is shown inside each portfolio holdings table.",
      actions: [{ label: "See recent activity", primary: true, onClick: () => { onClose(); scrollTo("recentActivitySection"); } }]
    },
    watchlist: {
      title: "Watchlist & Alerts",
      body: "Watchlist is your saved stock list. Alerts are ABOVE/BELOW price targets that auto-trigger when the condition is met.",
      actions: [{ label: "Open watchlist", primary: true, onClick: () => { onClose(); nav("/account"); } }]
    }
  };

  const item = items[infoKey] || { title: "Info", body: "", actions: [] };

  return (
    <div className="modalBackdrop" role="dialog" aria-modal="true">
      <div className="modal">
        <div className="modalHeader">
          <h2>{item.title}</h2>
          <button className="btn ghost" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <div className="muted" style={{ marginTop: 8 }}>
          {item.body}
        </div>
        <div style={{ marginTop: 14, display: "flex", gap: 10, flexWrap: "wrap" }}>
          {(item.actions || []).map((a, idx) => (
            <button
              key={idx}
              className={a.primary ? "btn primary" : "btn ghost"}
              onClick={a.onClick}
              type="button"
            >
              {a.label}
            </button>
          ))}
          <button className="btn ghost" onClick={onClose} type="button">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
