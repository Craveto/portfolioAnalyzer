import React, { useEffect, useRef, useState } from "react";
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
  const [quickImportOpen, setQuickImportOpen] = useState(false);
  const [quickImportFile, setQuickImportFile] = useState(null);
  const [quickImportGroupBySector, setQuickImportGroupBySector] = useState(false);
  const [quickImportPreview, setQuickImportPreview] = useState(null);
  const [quickPreviewBusy, setQuickPreviewBusy] = useState(false);
  const [quickImportBusy, setQuickImportBusy] = useState(false);
  const [quickImportError, setQuickImportError] = useState("");
  const [quickImportResult, setQuickImportResult] = useState(null);
  const [quickProgress, setQuickProgress] = useState(0);
  const [quickPhase, setQuickPhase] = useState("");
  const progressTimerRef = useRef(null);

  useEffect(() => {
    refreshSummary(false);
  }, [nav]);

  useEffect(() => {
    // keep the dashboard snappy; portfolios are loaded via summary
  }, []);

  function stopProgress(finalPercent = null) {
    if (progressTimerRef.current) {
      clearInterval(progressTimerRef.current);
      progressTimerRef.current = null;
    }
    if (finalPercent !== null) setQuickProgress(finalPercent);
  }

  function startProgress(phaseLabel) {
    stopProgress(8);
    setQuickPhase(phaseLabel);
    progressTimerRef.current = setInterval(() => {
      setQuickProgress((prev) => (prev >= 92 ? prev : prev + (prev < 40 ? 8 : prev < 75 ? 4 : 1)));
    }, 180);
  }

  useEffect(() => () => stopProgress(null), []);

  async function refreshSummary(force = false) {
    try {
      const d = await api.dashboardSummary(force);
      setMe(d.user);
      setSummary(d);
      setPortfolios(d.portfolios || []);
      setMarketFetchedAt(Date.now());
      saveDashboardCache(d);
      setError("");
    } catch (e) {
      const msg = e?.message || "Failed to load dashboard";
      if (msg.includes("401") || /not authenticated|credentials|token/i.test(msg)) {
        clearTokens();
        nav("/");
        return;
      }
      setError(msg);
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
          {error ? <div className="error" style={{ marginTop: 10 }}>{error}</div> : null}
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
            <button className="btn ghost" type="button" onClick={() => setQuickImportOpen(true)}>
              Quick Stocks Add
            </button>
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

      <QuickStocksAddModal
        open={quickImportOpen}
        file={quickImportFile}
        groupBySector={quickImportGroupBySector}
        preview={quickImportPreview}
        previewBusy={quickPreviewBusy}
        busy={quickImportBusy}
        progress={quickProgress}
        phase={quickPhase}
        error={quickImportError}
        result={quickImportResult}
        onClose={() => {
          if (quickImportBusy || quickPreviewBusy) return;
          setQuickImportOpen(false);
          setQuickImportError("");
          setQuickImportResult(null);
          setQuickImportPreview(null);
          setQuickProgress(0);
          setQuickPhase("");
          stopProgress(0);
        }}
        onFileChange={(f) => {
          setQuickImportFile(f);
          setQuickImportError("");
          setQuickImportResult(null);
          setQuickImportPreview(null);
          setQuickProgress(0);
          setQuickPhase("");
          stopProgress(0);
        }}
        onToggleGroupBySector={(v) => {
          setQuickImportGroupBySector(v);
          setQuickImportPreview(null);
          setQuickImportResult(null);
        }}
        onPreview={async () => {
          if (!quickImportFile || quickImportBusy || quickPreviewBusy) return;
          setQuickPreviewBusy(true);
          setQuickImportError("");
          setQuickImportResult(null);
          startProgress("Previewing CSV");
          try {
            const preview = await api.previewPortfolioCsv({
              file: quickImportFile,
              groupBySector: quickImportGroupBySector,
              baseName: `CSV Import ${new Date().toISOString().slice(0, 10)}`
            });
            setQuickImportPreview(preview);
            stopProgress(100);
          } catch (e) {
            setQuickImportError(e.message || "CSV preview failed");
            setQuickImportPreview(null);
            stopProgress(0);
          } finally {
            setQuickPreviewBusy(false);
            window.setTimeout(() => {
              setQuickProgress((p) => (p === 100 ? 0 : p));
              setQuickPhase("");
            }, 700);
          }
        }}
        onImport={async () => {
          if (!quickImportFile || quickImportBusy || quickPreviewBusy) return;
          if (!quickImportPreview || !Number(quickImportPreview.rows_resolved || 0)) {
            setQuickImportError("Please run Preview first and ensure at least one stock is resolved.");
            return;
          }
          setQuickImportBusy(true);
          setQuickImportError("");
          setQuickImportResult(null);
          startProgress("Creating portfolios");
          try {
            const imported = await api.importPortfolioCsv({
              file: quickImportFile,
              groupBySector: quickImportGroupBySector,
              baseName: `CSV Import ${new Date().toISOString().slice(0, 10)}`
            });
            setQuickImportResult(imported);
            await refreshSummary(true);
            stopProgress(100);
          } catch (e) {
            setQuickImportError(e.message || "CSV import failed");
            stopProgress(0);
          } finally {
            setQuickImportBusy(false);
            window.setTimeout(() => {
              setQuickProgress((p) => (p === 100 ? 0 : p));
              setQuickPhase("");
            }, 900);
          }
        }}
      />
    </div>
  );
}

function QuickStocksAddModal({
  open,
  file,
  groupBySector,
  preview,
  previewBusy,
  busy,
  progress,
  phase,
  error,
  result,
  onClose,
  onFileChange,
  onToggleGroupBySector,
  onPreview,
  onImport
}) {
  const fileInputRef = useRef(null);
  const [dragActive, setDragActive] = useState(false);
  const previewRows = Array.isArray(preview?.resolved_preview) ? preview.resolved_preview.slice(0, 18) : [];
  const completedApprox = Math.floor((Math.max(0, Math.min(100, progress || 0)) / 100) * previewRows.length);
  const importLog = Array.isArray(result?.import_log) ? result.import_log.slice(0, 18) : [];

  if (!open) return null;

  return (
    <div className="modalBackdrop" role="dialog" aria-modal="true" aria-label="Quick stocks add">
      <div className="modal">
        <div className="modalHeader">
          <h2>Quick Stocks Add</h2>
          <button className="btn ghost" onClick={onClose} type="button" disabled={busy || previewBusy}>
            Close
          </button>
        </div>

        <div className="muted" style={{ marginTop: 8 }}>
          Step 1: Upload CSV. Step 2: Preview auto-matched stocks. Step 3: Create portfolios and BUY transactions.
        </div>

        <div
          className={`csvDropZone ${dragActive ? "active" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragEnter={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={(e) => {
            e.preventDefault();
            if (e.currentTarget.contains(e.relatedTarget)) return;
            setDragActive(false);
          }}
          onDrop={(e) => {
            e.preventDefault();
            setDragActive(false);
            const dropped = e.dataTransfer?.files?.[0];
            if (dropped) onFileChange(dropped);
          }}
        >
          <div className="strong">Drag & drop CSV here</div>
          <div className="muted small" style={{ marginTop: 4 }}>
            or choose a file manually
          </div>
          <div style={{ marginTop: 10 }}>
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,text/csv"
              style={{ display: "none" }}
              onChange={(e) => onFileChange(e.target.files?.[0] || null)}
            />
            <button className="btn sm" type="button" onClick={() => fileInputRef.current?.click()}>
              Browse CSV
            </button>
          </div>
          {file ? <div className="csvFileTag">{file.name}</div> : null}
        </div>

        <div className="modalFooter" style={{ marginTop: 12, display: "flex", justifyContent: "space-between" }}>
          <div className="muted small">Preview validates and matches your stocks before import.</div>
          <button className="btn sm" type="button" onClick={onPreview} disabled={!file || busy || previewBusy}>
            {previewBusy ? "Previewing..." : "Preview CSV"}
          </button>
        </div>

        {error ? <div className="error">{error}</div> : null}

        {(previewBusy || busy || progress > 0) ? (
          <div className="csvProgressWrap">
            <div className="csvProgressMeta">
              <span>{phase || (busy ? "Creating portfolios" : "Working...")}</span>
              <span>{Math.max(0, Math.min(100, Math.round(progress || 0)))}%</span>
            </div>
            <div className="csvProgressBar">
              <div className="csvProgressFill" style={{ width: `${Math.max(0, Math.min(100, progress || 0))}%` }} />
            </div>
          </div>
        ) : null}

        {preview ? (
          <div className="csvImportSummary">
            <div className="strong">Preview completed</div>
            <div className="muted small">
              Resolved {preview.rows_resolved}/{preview.rows_received} rows, skipped {preview.rows_skipped}.
            </div>
            <div className="muted small">
              Tentative portfolios: {(preview.tentative_portfolios || []).map((p) => `${p.name} (${p.stock_count})`).join(", ") || "None"}
            </div>
            {(preview.skipped_preview || []).length ? (
              <div className="muted small" style={{ marginTop: 6 }}>
                Skipped examples: {(preview.skipped_preview || []).slice(0, 5).map((s) => `#${s.row} ${s.reason}`).join(" | ")}
              </div>
            ) : null}
          </div>
        ) : null}

        {preview ? (
          <label className="label" style={{ marginTop: 12 }}>
            Create portfolios by
            <select
              className="input"
              value={groupBySector ? "sector" : "single"}
              onChange={(e) => onToggleGroupBySector(e.target.value === "sector")}
              disabled={busy || previewBusy}
            >
              <option value="single">No split (one portfolio)</option>
              <option value="sector">Split by sector</option>
            </select>
          </label>
        ) : null}

        {result ? (
          <div className="csvImportSummary">
            <div className="strong">Import completed</div>
            <div className="muted small">
              Processed {result.rows_processed}/{result.rows_received} rows.
            </div>
            <div className="muted small">BUY transactions created: {result.transactions_created ?? result.rows_processed ?? 0}</div>
            <div className="muted small">
              Created portfolios: {(result.created_portfolios || []).map((p) => `${p.name} (#${p.id})`).join(", ") || "None"}
            </div>
          </div>
        ) : null}

        {(previewRows.length && (previewBusy || busy || result)) ? (
          <div className="csvRuntimePanel">
            <div className="strong">Stock processing status</div>
            <div className="csvRuntimeList">
              {result
                ? (importLog.length ? importLog : previewRows).map((it, idx) => (
                    <div className="csvRuntimeRow" key={`done-${idx}-${it.symbol}`}>
                      <span className="mono">{it.symbol}</span>
                      <span className="csvRuntimeState done">Completed</span>
                    </div>
                  ))
                : previewRows.map((it, idx) => {
                    const state = idx < completedApprox ? "done" : idx === completedApprox ? "active" : "wait";
                    const label = state === "done" ? "Completed" : state === "active" ? "Processing..." : "Pending";
                    return (
                      <div className="csvRuntimeRow" key={`rt-${idx}-${it.symbol}`}>
                        <span className="mono">{it.symbol}</span>
                        <span className={`csvRuntimeState ${state}`}>{label}</span>
                      </div>
                    );
                  })}
            </div>
          </div>
        ) : null}

        <div className="modalFooter" style={{ marginTop: 14 }}>
          <button className="btn ghost" type="button" onClick={onClose} disabled={busy || previewBusy}>
            Cancel
          </button>
          <button className="btn primary" type="button" onClick={onImport} disabled={!file || !preview || busy || previewBusy}>
            {busy ? `Creating... ${Math.round(progress || 0)}%` : "Create Portfolios"}
          </button>
        </div>
      </div>
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
