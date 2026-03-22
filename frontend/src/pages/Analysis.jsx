import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, clearTokens } from "../api.js";
import LineChart from "../components/LineChart.jsx";
import NavBar from "../components/NavBar.jsx";
import Footer from "../components/Footer.jsx";

function fmt(n) {
  if (n === null || n === undefined) return "--";
  const num = Number(n);
  if (Number.isNaN(num)) return "--";
  return num.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function pct(n) {
  if (n === null || n === undefined) return "--";
  const num = Number(n);
  if (Number.isNaN(num)) return "--";
  return `${num.toFixed(2)}%`;
}

function valueOrNotAvailable(n, formatter = fmt) {
  if (n === null || n === undefined) return "Not available";
  const out = formatter(n);
  return out === "--" ? "Not available" : out;
}

function hasCompleteMarketContext(insight) {
  const mc = insight?.market_context || {};
  return mc.pe !== null && mc.pe !== undefined && mc.market_cap !== null && mc.market_cap !== undefined && mc.range_position_pct !== null && mc.range_position_pct !== undefined;
}

function cacheKey(portfolioId) {
  return `analysisPage:${portfolioId}`;
}

function readCache(portfolioId) {
  try {
    const raw = localStorage.getItem(cacheKey(portfolioId));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeCache(portfolioId, payload) {
  try {
    localStorage.setItem(cacheKey(portfolioId), JSON.stringify({ savedAt: Date.now(), ...payload }));
  } catch {}
}

function sentimentTone(label) {
  const normalized = String(label || "").toLowerCase();
  if (normalized === "bullish" || normalized === "positive") return "pos";
  if (normalized === "bearish" || normalized === "negative") return "neg";
  return "neutral";
}

function verdictTone(label) {
  return sentimentTone(label);
}

function triggerBlobDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function fmtDocNum(value, digits = 2) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "Not available";
  return num.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function fmtDocPct(value, digits = 2) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "Not available";
  return `${num.toFixed(digits)}%`;
}

function buildFallbackMarkdown(insight) {
  if (!insight) return "# Stock Insight Report\n\nNot available.";
  const verdict = insight.verdict || {};
  const news = (insight.top_news || [])
    .map((n) => `| ${(n.headline || "Untitled").replaceAll("|", "\\|")} | ${n.sentiment_label || "Unknown"} | ${n.impact_level || "Unknown"} | ${n.source || "Unknown"} |`)
    .join("\n");
  const risks = (insight.risk_flags || []).length ? (insight.risk_flags || []).map((r) => `- ${r}`).join("\n") : "- No major risk flags";
  return `# ${insight.stock?.symbol || "Stock"} Sentiment Report

## Verdict
${verdict.reason || "Based on available sentiment evidence."}

## Overall Signal
| Metric | Value |
|---|---|
| Signal | ${insight.overall_signal?.label || "Neutral"} |
| Score | ${fmtDocNum(insight.overall_signal?.sentiment_score)} |
| Confidence | ${fmtDocPct((insight.overall_signal?.confidence || 0) * 100)} |
| Coverage | ${insight.overall_signal?.based_on || "Not available"} |
| Verdict | ${verdict.label || insight.overall_signal?.label || "Neutral"} |

## Market Context
| Metric | Value |
|---|---|
| Last Price | ${fmtDocNum(insight.market_context?.last_price)} |
| Daily Change % | ${fmtDocPct(insight.market_context?.daily_change_pct)} |
| P/E | ${fmtDocNum(insight.market_context?.pe)} |
| Market Cap | ${fmtDocNum(insight.market_context?.market_cap, 0)} |
| 52W Position % | ${fmtDocPct(insight.market_context?.range_position_pct)} |
| Dominant Event | ${(insight.score_breakdown?.dominant_event_type || "other").replaceAll("_", " ")} |

## Why This Changed
${(insight.why_it_changed || []).map((w) => `- ${w}`).join("\n") || "- Not available"}

## Risk Flags
${risks}

## Top News
| Headline | Sentiment | Impact | Source |
|---|---|---|---|
${news || "| No news available. | - | - | - |"}
`;
}

function buildFallbackCsvRows(insight) {
  const rows = insight?.top_news || [];
  if (!rows.length) {
    return "ticker,headline,source,published_at,sentiment_label,impact_level,event_type,confidence_score,weighted_score\n";
  }
  const esc = (v) => `"${String(v ?? "").replaceAll('"', '""')}"`;
  const header = "ticker,headline,source,published_at,sentiment_label,impact_level,event_type,confidence_score,weighted_score";
  const lines = rows.map((r) =>
    [
      esc(r.ticker || insight?.stock?.symbol || ""),
      esc(r.headline),
      esc(r.source),
      esc(r.published_at),
      esc(r.sentiment_label),
      esc(r.impact_level),
      esc(r.event_type),
      esc(r.confidence_score),
      esc(r.weighted_score)
    ].join(",")
  );
  return [header, ...lines].join("\n");
}

function buildPrintableHtml(insight) {
  const stock = insight?.stock || {};
  const overall = insight?.overall_signal || {};
  const market = insight?.market_context || {};
  const score = insight?.score_breakdown || {};
  const verdict = insight?.verdict || { label: overall?.label || "Neutral", reason: "" };
  const newsHtml = (insight?.top_news || [])
    .map(
      (item) =>
        `<tr><td>${item?.headline || "-"}</td><td>${item?.sentiment_label || "-"}</td><td>${item?.impact_level || "-"}</td><td>${item?.source || "-"}</td></tr>`
    )
    .join("");
  const risksHtml = (insight?.risk_flags || []).map((item) => `<li>${item}</li>`).join("");
  const whyHtml = (insight?.why_it_changed || []).map((item) => `<li>${item}</li>`).join("");

  return `
    <html>
      <head>
        <title>${stock?.symbol || "Stock"} Sentiment Report</title>
        <style>
          :root { color-scheme: light only; }
          body { font-family: "Segoe UI", Arial, sans-serif; padding: 28px; color: #0f172a; line-height: 1.45; }
          h1, h2 { margin: 0 0 8px; }
          .muted { color: #475569; }
          .pill { display: inline-block; padding: 6px 10px; border-radius: 999px; background: #dbeafe; margin-right: 8px; font-size: 12px; }
          .section { margin-top: 20px; }
          .card { border: 1px solid #cbd5e1; border-radius: 12px; padding: 12px; background: #f8fafc; }
          .kgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
          table { width: 100%; border-collapse: collapse; margin-top: 8px; }
          th, td { border: 1px solid #e2e8f0; text-align: left; padding: 8px; font-size: 13px; vertical-align: top; }
          th { background: #f1f5f9; }
          ul { padding-left: 18px; margin: 8px 0 0; }
        </style>
      </head>
      <body>
        <h1>${stock?.symbol || "Stock"} Stock Insight Report</h1>
        <div class="muted">${stock?.name || stock?.symbol || "-"}</div>
        <div style="margin-top: 12px;">
          <span class="pill">Signal: ${overall?.label || "Neutral"}</span>
          <span class="pill">Score: ${fmt(overall?.sentiment_score)}</span>
          <span class="pill">Confidence: ${pct((overall?.confidence || 0) * 100)}</span>
        </div>
        <div class="section">
          <h2>Verdict</h2>
          <p><strong>${verdict.label || overall?.label || "Neutral"}</strong> - ${verdict.reason || "Verdict from current sentiment evidence."}</p>
        </div>
        <div class="section">
          <h2>Analyst Summary</h2>
          <div class="card">${insight?.analyst_summary || "Not available."}</div>
        </div>
        <div class="section">
          <h2>Why This Changed</h2>
          <ul>${whyHtml || "<li>Not available.</li>"}</ul>
        </div>
        <div class="section">
          <h2>Top News</h2>
          <table>
            <thead><tr><th>Headline</th><th>Sentiment</th><th>Impact</th><th>Source</th></tr></thead>
            <tbody>${newsHtml || "<tr><td colspan='4'>No news available.</td></tr>"}</tbody>
          </table>
        </div>
        <div class="section">
          <h2>Risk Flags</h2>
          <ul>${risksHtml || "<li>No major risk flags detected.</li>"}</ul>
        </div>
        <div class="section">
          <h2>Market Context</h2>
          <div class="kgrid">
            <div class="card"><strong>Last price</strong><div>${valueOrNotAvailable(market?.last_price, fmt)}</div></div>
            <div class="card"><strong>Daily change</strong><div>${valueOrNotAvailable(market?.daily_change_pct, pct)}</div></div>
            <div class="card"><strong>P/E</strong><div>${valueOrNotAvailable(market?.pe, fmt)}</div></div>
            <div class="card"><strong>Market cap</strong><div>${valueOrNotAvailable(market?.market_cap, fmt)}</div></div>
            <div class="card"><strong>52W position</strong><div>${valueOrNotAvailable(market?.range_position_pct, pct)}</div></div>
            <div class="card"><strong>Dominant event</strong><div>${String(score?.dominant_event_type || "other").replaceAll("_", " ")}</div></div>
          </div>
        </div>
      </body>
    </html>
  `;
}

function openPrintReport(insight) {
  if (!insight) return false;
  try {
    const win = window.open("", "_blank", "noopener,noreferrer,width=980,height=760");
    if (!win) return false;
    const html = buildPrintableHtml(insight);
    win.document.open();
    win.document.write(html);
    win.document.close();
    win.focus();
    setTimeout(() => {
      try {
        win.print();
      } catch {}
    }, 250);
    return true;
  } catch {
    return false;
  }
}

export default function Analysis() {
  const { id } = useParams();
  const portfolioId = Number(id);
  const nav = useNavigate();
  const cached = readCache(portfolioId);

  const [data, setData] = useState(cached?.data || null);
  const [forecast, setForecast] = useState(cached?.forecast || null);
  const [sentiment, setSentiment] = useState(cached?.sentiment || null);
  const [selectedSymbol, setSelectedSymbol] = useState(cached?.selectedSymbol || "");
  const [stockInsight, setStockInsight] = useState(cached?.stockInsight || null);
  const [portfolios, setPortfolios] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [forecastBusy, setForecastBusy] = useState(true);
  const [sentimentBusy, setSentimentBusy] = useState(true);
  const [stockInsightBusy, setStockInsightBusy] = useState(false);
  const [reportBusy, setReportBusy] = useState("");
  const [showVerdictReason, setShowVerdictReason] = useState(false);
  const [reportError, setReportError] = useState("");

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setForecastBusy(true);
    setSentimentBusy(true);

    api
      .portfolioPE(portfolioId)
      .then((d) => {
        if (!alive) return;
        setData(d);
        writeCache(portfolioId, { data: d, forecast, sentiment, selectedSymbol, stockInsight });
        setError("");
        if (d?.meta?.stale) {
          api
            .portfolioPE(portfolioId, true)
            .then((fresh) => {
              if (!alive) return;
              setData(fresh);
              writeCache(portfolioId, { data: fresh, forecast, sentiment, selectedSymbol, stockInsight });
            })
            .catch(() => {});
        }
      })
      .catch((e) => {
        if (!alive) return;
        setError(e.message || "Failed to load analysis");
        if ((e.message || "").includes("HTTP 401") || (e.message || "").includes("HTTP 403")) {
          clearTokens();
          nav("/");
        }
      })
      .finally(() => {
        if (!alive) return;
        setLoading(false);
      });

    api
      .portfolioForecast(portfolioId, 90)
      .then((d) => {
        if (!alive) return;
        setForecast(d);
        writeCache(portfolioId, { data, forecast: d, sentiment, selectedSymbol, stockInsight });
      })
      .catch(() => {})
      .finally(() => {
        if (!alive) return;
        setForecastBusy(false);
      });

    api
      .portfolioSentiment(portfolioId)
      .then((d) => {
        if (!alive) return;
        setSentiment(d);
        const firstSymbol = cached?.selectedSymbol || d?.stocks?.[0]?.symbol || "";
        if (firstSymbol) setSelectedSymbol(firstSymbol);
        writeCache(portfolioId, { data, forecast, sentiment: d, selectedSymbol: firstSymbol, stockInsight });
      })
      .catch(() => {})
      .finally(() => {
        if (!alive) return;
        setSentimentBusy(false);
      });

    return () => {
      alive = false;
    };
  }, [portfolioId, nav]);

  useEffect(() => {
    let alive = true;
    api
      .listPortfolios()
      .then((items) => {
        if (!alive) return;
        setPortfolios(Array.isArray(items) ? items : []);
      })
      .catch(() => {
        if (!alive) return;
        setPortfolios([]);
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedSymbol) return;
    let alive = true;
    setStockInsightBusy(true);
    api
      .stockInsight(portfolioId, selectedSymbol)
      .then(async (d) => {
        if (!alive) return;
        let next = d;
        if (!hasCompleteMarketContext(d)) {
          try {
            const forced = await api.stockInsight(portfolioId, selectedSymbol, true);
            if (alive) next = forced;
          } catch {
            // Keep the initial payload if forced refresh fails.
          }
        }
        if (!alive) return;
        setStockInsight(next);
        writeCache(portfolioId, { data, forecast, sentiment, selectedSymbol, stockInsight: next });
      })
      .catch(() => {
        if (!alive) return;
        setStockInsight(null);
      })
      .finally(() => {
        if (!alive) return;
        setStockInsightBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [portfolioId, selectedSymbol]);

  useEffect(() => {
    setShowVerdictReason(false);
  }, [selectedSymbol]);

  const holdings = data?.holdings || [];
  const maxPE = useMemo(() => {
    const pes = holdings.map((h) => (h.pe === null || h.pe === undefined ? null : Number(h.pe))).filter((x) => x !== null && !Number.isNaN(x));
    return pes.length ? Math.max(...pes) : 0;
  }, [holdings]);

  const discountPoints = useMemo(() => {
    return holdings
      .map((h) => ({
        symbol: h.symbol,
        discount:
          h.discount_from_52w_high_pct === null || h.discount_from_52w_high_pct === undefined
            ? null
            : Number(h.discount_from_52w_high_pct)
      }))
      .filter((p) => p.discount !== null && Number.isFinite(p.discount));
  }, [holdings]);

  const maxDiscount = useMemo(() => (discountPoints.length ? Math.max(...discountPoints.map((p) => p.discount)) : 0), [discountPoints]);

  const forecastPoints = useMemo(() => {
    const s = forecast?.series || [];
    return s.map((p, idx) => ({
      x: p.date,
      xLabel: idx === 0 || idx === Math.floor(s.length / 2) || idx === s.length - 1 ? p.date : "",
      y: p.portfolio_value
    }));
  }, [forecast]);

  const sentimentSummary = sentiment?.portfolio_summary || null;
  const sentimentStocks = sentiment?.stocks || [];

  async function downloadReport(format) {
    if (!selectedSymbol) return;
    setReportBusy(format);
    setReportError("");
    try {
      const blob = await api.stockReport(portfolioId, selectedSymbol, format);
      const ext = format === "csv" ? "csv" : format === "pdf" ? "pdf" : "md";
      triggerBlobDownload(blob, `${selectedSymbol.replaceAll(".", "_")}_sentiment_report.${ext}`);
    } catch (e) {
      const message = e.message || "Failed to download report";
      const isNotFound = message.includes("Not found") || message.includes("404");
      if (isNotFound && stockInsight) {
        try {
          if (format === "md") {
            const md = buildFallbackMarkdown(stockInsight);
            triggerBlobDownload(new Blob([md], { type: "text/markdown;charset=utf-8" }), `${selectedSymbol.replaceAll(".", "_")}_sentiment_report.md`);
            setReportError("Smart fallback used: downloaded local Markdown report.");
            return;
          }
          if (format === "csv") {
            const csv = buildFallbackCsvRows(stockInsight);
            triggerBlobDownload(new Blob([csv], { type: "text/csv;charset=utf-8" }), `${selectedSymbol.replaceAll(".", "_")}_sentiment_report.csv`);
            setReportError("Smart fallback used: downloaded local CSV report.");
            return;
          }
          if (format === "pdf") {
            const printable = buildPrintableHtml(stockInsight);
            triggerBlobDownload(new Blob([printable], { type: "text/html;charset=utf-8" }), `${selectedSymbol.replaceAll(".", "_")}_sentiment_report_printable.html`);
            setReportError("PDF route unavailable. Downloaded printable HTML report.");
            return;
          }
        } catch {
          // fall through to normal error below
        }
      }
      setError(message);
      setReportError(message);
    } finally {
      setReportBusy("");
    }
  }

  function logout() {
    clearTokens();
    nav("/");
  }

  return (
    <div className="page">
      <NavBar
        title="Analysis"
        subtitle={
          <Link className="link" to={`/portfolio/${portfolioId}`}>
            Back to portfolio
          </Link>
        }
        links={[
          { to: "/dashboard", label: "Dashboard" },
          { to: `/portfolio/${portfolioId}`, label: "Holdings", match: (l) => l.pathname.startsWith("/portfolio/") },
          { to: `/analysis/${portfolioId}`, label: "Analysis", end: true, match: (l) => l.pathname.startsWith("/analysis/") },
          { to: `/chart/${portfolioId}`, label: "Charts", match: (l) => l.pathname.startsWith("/chart/") }
        ]}
        actions={
          <button className="btn danger sm" type="button" onClick={logout}>
            Logout
          </button>
        }
      />

      <main className="grid">
        <section className="card hero">
          <h1>Sentiment & stock insight</h1>
          <p className="muted">
            This page now combines portfolio valuation analysis with a teacher-demo-ready sentiment module built in a Databricks-ready response shape.
          </p>
          <div className="insightSelectorRow" style={{ marginTop: 14 }}>
            <label className="label" style={{ marginTop: 0, flex: "0 0 320px" }}>
              Select portfolio
              <select className="input" value={String(portfolioId)} onChange={(e) => nav(`/analysis/${e.target.value}`)}>
                {!portfolios.length ? <option value={String(portfolioId)}>Portfolio #{portfolioId}</option> : null}
                {portfolios.map((p) => (
                  <option key={p.id} value={String(p.id)}>
                    {p.name} (#{p.id})
                  </option>
                ))}
              </select>
            </label>
          </div>
        </section>

        <section className="card">
          <h3>Portfolio summary</h3>
          {loading ? <div className="skeleton h40" /> : null}
          {error ? <div className="error">{error}</div> : null}
          <div className="kpiRow">
            <div className="kpi">
              <div className="kpiLabel">Total Market Value</div>
              <div className="kpiValue">{fmt(data?.total_market_value)}</div>
            </div>
            <div className="kpi">
              <div className="kpiLabel">Weighted P/E</div>
              <div className="kpiValue">{fmt(data?.portfolio_pe_weighted)}</div>
            </div>
          </div>
          <div className="muted small">Portfolio: {data?.portfolio?.name || sentiment?.portfolio?.name || "--"}</div>
          <div className="muted small">Data uses yfinance. Some stocks may not have P/E.</div>
        </section>

        <section className="card" style={{ gridColumn: "1 / -1" }}>
          <div className="sectionRow">
            <div>
              <h3 style={{ marginBottom: 6 }}>Portfolio sentiment snapshot</h3>
              <div className="muted small">Gold-table style summary for your holdings, designed so Databricks can replace the source later.</div>
            </div>
            {sentimentSummary ? (
              <div className={`insightBadge ${sentimentTone(sentimentSummary.portfolio_signal)}`}>{sentimentSummary.portfolio_signal}</div>
            ) : null}
          </div>

          {sentimentBusy ? <div className="skeleton h200" style={{ marginTop: 12 }} /> : null}

          {sentimentSummary ? (
            <>
              <div className="insightGrid" style={{ marginTop: 14 }}>
                <div className="insightMetricCard">
                  <div className="insightMetricLabel">Portfolio signal</div>
                  <div className={`insightMetricValue ${sentimentTone(sentimentSummary.portfolio_signal)}`}>
                    {sentimentSummary.portfolio_signal}
                  </div>
                  <div className="muted small">Sentiment score {fmt(sentimentSummary.portfolio_sentiment_score)}</div>
                </div>
                <div className="insightMetricCard">
                  <div className="insightMetricLabel">Most positive stock</div>
                  <div className="insightMetricValue">{sentimentSummary.most_positive_stock?.symbol || "--"}</div>
                  <div className="muted small">{sentimentSummary.most_positive_stock?.signal || "No signal yet"}</div>
                </div>
                <div className="insightMetricCard">
                  <div className="insightMetricLabel">Most risky stock</div>
                  <div className="insightMetricValue">{sentimentSummary.most_risky_stock?.symbol || "--"}</div>
                  <div className="muted small">
                    {sentimentSummary.most_risky_stock?.risk_flags?.length || 0} active risk flag
                    {sentimentSummary.most_risky_stock?.risk_flags?.length === 1 ? "" : "s"}
                  </div>
                </div>
                <div className="insightMetricCard">
                  <div className="insightMetricLabel">Most mentioned stock</div>
                  <div className="insightMetricValue">{sentimentSummary.most_mentioned_stock?.symbol || "--"}</div>
                  <div className="muted small">{sentimentSummary.most_mentioned_stock?.news_count || 0} news items</div>
                </div>
              </div>

              <div className="insightSelectorRow">
                <label className="label" style={{ marginTop: 0, flex: "1 1 260px" }}>
                  Select stock insight
                  <select className="input" value={selectedSymbol} onChange={(e) => setSelectedSymbol(e.target.value)}>
                    {sentimentStocks.map((item) => (
                      <option key={item.symbol} value={item.symbol}>
                        {item.symbol} - {item.signal}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="insightSectorBox">
                  <div className="insightMetricLabel">Sector mix</div>
                  <div className="chipRow" style={{ marginTop: 8 }}>
                    {(sentimentSummary.sector_sentiment_mix || []).map((item) => (
                      <span key={item.sector} className="chip">
                        {item.sector}: {fmt(item.avg_sentiment_score)}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </>
          ) : !sentimentBusy ? (
            <div className="muted" style={{ marginTop: 12 }}>
              Sentiment data is not available yet for this portfolio.
            </div>
          ) : null}
        </section>

        <section className="card" style={{ gridColumn: "1 / -1" }}>
          <div className="sectionRow">
            <div>
              <h3 style={{ marginBottom: 6 }}>Stock insight module</h3>
              <div className="muted small">Overall signal, reasons, top news, risk flags, and report actions.</div>
            </div>
            {stockInsight ? <div className={`insightBadge ${sentimentTone(stockInsight.overall_signal.label)}`}>{stockInsight.overall_signal.label}</div> : null}
          </div>

          {stockInsightBusy ? <div className="skeleton h200" style={{ marginTop: 12 }} /> : null}

          {stockInsight ? (
            <>
              <div className="insightGrid" style={{ marginTop: 14 }}>
                <div className={`insightMetricCard verdictCard ${verdictTone((stockInsight.verdict || {}).label || stockInsight.overall_signal.label)}`}>
                  <div className="insightMetricLabel">Verdict</div>
                  <div className="insightMetricValue">{(stockInsight.verdict || {}).label || stockInsight.overall_signal.label}</div>
                  <button
                    className="btn ghost sm verdictBtn"
                    type="button"
                    onClick={() => setShowVerdictReason((v) => !v)}
                  >
                    {showVerdictReason ? "Hide reason" : "Why this verdict?"}
                  </button>
                  {showVerdictReason ? (
                    <div className="muted small verdictReason">
                      {(stockInsight.verdict || {}).reason || "Verdict is based on latest sentiment score, news mix, and risk flags."}
                    </div>
                  ) : null}
                </div>
                <div className="insightMetricCard">
                  <div className="insightMetricLabel">Overall signal</div>
                  <div className={`insightMetricValue ${sentimentTone(stockInsight.overall_signal.label)}`}>{stockInsight.overall_signal.label}</div>
                  <div className="muted small">{stockInsight.overall_signal.based_on}</div>
                </div>
                <div className="insightMetricCard">
                  <div className="insightMetricLabel">Sentiment score</div>
                  <div className="insightMetricValue">{fmt(stockInsight.overall_signal.sentiment_score)}</div>
                  <div className="muted small">Window: {stockInsight.overall_signal.window}</div>
                </div>
                <div className="insightMetricCard">
                  <div className="insightMetricLabel">Confidence meter</div>
                  <div className="insightMetricValue">{pct((stockInsight.overall_signal.confidence || 0) * 100)}</div>
                  <div className="muted small">Trend: {stockInsight.score_breakdown.trend_direction}</div>
                </div>
                <div className="insightMetricCard">
                  <div className="insightMetricLabel">Price context</div>
                  <div className="insightMetricValue">{fmt(stockInsight.market_context.last_price)}</div>
                  <div className="muted small">Daily move: {pct(stockInsight.market_context.daily_change_pct)}</div>
                </div>
              </div>

              <div className="insightColumns">
                <div className="insightPanel">
                  <div className="strong">Why this changed</div>
                  <ul className="insightList">
                    {(stockInsight.why_it_changed || []).map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
                <div className="insightPanel">
                  <div className="strong">Risk flags</div>
                  {(stockInsight.risk_flags || []).length ? (
                    <div className="chipRow" style={{ marginTop: 10 }}>
                      {stockInsight.risk_flags.map((item) => (
                        <span key={item} className="chip insightRiskChip">
                          {item}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <div className="muted small" style={{ marginTop: 10 }}>
                      No major risk flags in the current headline scan.
                    </div>
                  )}
                </div>
              </div>

              <div className="insightColumns">
                <div className="insightPanel">
                  <div className="strong">Top news</div>
                  <div className="insightNewsList">
                    {(stockInsight.top_news || []).map((item) => (
                      <a
                        key={`${item.headline}-${item.published_at || item.source}`}
                        className="insightNewsItem"
                        href={item.url || undefined}
                        target={item.url ? "_blank" : undefined}
                        rel={item.url ? "noreferrer" : undefined}
                      >
                        <div className="insightNewsHead">
                          <div className="strong">{item.headline}</div>
                          <div className={`insightMiniBadge ${sentimentTone(item.sentiment_label)}`}>{item.sentiment_label}</div>
                        </div>
                        <div className="muted small" style={{ marginTop: 6 }}>
                          {item.source} • {item.impact_level} impact • {item.event_type.replaceAll("_", " ")}
                        </div>
                        <div className="muted small" style={{ marginTop: 6 }}>
                          {item.short_explanation_tag}
                        </div>
                      </a>
                    ))}
                  </div>
                </div>
                <div className="insightPanel">
                  <div className="strong">Short analyst summary</div>
                  <p className="muted" style={{ marginTop: 10 }}>
                    {stockInsight.analyst_summary}
                  </p>
                  <div className="insightMarketGrid">
                    <div className="insightSubMetric">
                      <span>P/E</span>
                      <strong>{valueOrNotAvailable(stockInsight.market_context.pe)}</strong>
                    </div>
                    <div className="insightSubMetric">
                      <span>Market cap</span>
                      <strong>{valueOrNotAvailable(stockInsight.market_context.market_cap)}</strong>
                    </div>
                    <div className="insightSubMetric">
                      <span>52W position</span>
                      <strong>{valueOrNotAvailable(stockInsight.market_context.range_position_pct, pct)}</strong>
                    </div>
                    <div className="insightSubMetric">
                      <span>Dominant event</span>
                      <strong>{stockInsight.score_breakdown.dominant_event_type.replaceAll("_", " ")}</strong>
                    </div>
                  </div>
                </div>
              </div>

              <div className="insightActions reportActions">
                <button className={`btn primary sm ${reportBusy === "md" ? "btnBusy" : ""}`} type="button" onClick={() => downloadReport("md")} disabled={reportBusy === "md"}>
                  {reportBusy === "md" ? (
                    <>
                      <span className="btnLoader" aria-hidden="true" />
                      <span>Preparing Markdown...</span>
                    </>
                  ) : (
                    "Download Markdown"
                  )}
                </button>
                <button className={`btn ghost sm ${reportBusy === "csv" ? "btnBusy" : ""}`} type="button" onClick={() => downloadReport("csv")} disabled={reportBusy === "csv"}>
                  {reportBusy === "csv" ? (
                    <>
                      <span className="btnLoader" aria-hidden="true" />
                      <span>Preparing CSV...</span>
                    </>
                  ) : (
                    "Download CSV"
                  )}
                </button>
                <button className={`btn ghost sm ${reportBusy === "pdf" ? "btnBusy" : ""}`} type="button" onClick={() => downloadReport("pdf")} disabled={reportBusy === "pdf"}>
                  {reportBusy === "pdf" ? (
                    <>
                      <span className="btnLoader" aria-hidden="true" />
                      <span>Preparing PDF...</span>
                    </>
                  ) : (
                    "Download PDF"
                  )}
                </button>
                <button
                  className="btn ghost sm reportPrintBtn"
                  type="button"
                  onClick={() => {
                    const ok = openPrintReport(stockInsight);
                    if (!ok) {
                      setReportError("Popup blocked. Allow popups to save PDF.");
                    }
                  }}
                >
                  Print / Save PDF
                </button>
              </div>
              {reportError ? (
                <div className={`reportStatus ${String(reportError).toLowerCase().includes("blocked") ? "warn" : "info"}`}>
                  {reportError}
                </div>
              ) : null}
            </>
          ) : !stockInsightBusy ? (
            <div className="muted" style={{ marginTop: 12 }}>
              Select a stock above to load the full sentiment insight module.
            </div>
          ) : null}
        </section>

        <section className="card" style={{ gridColumn: "1 / -1" }}>
          <h3>P/E by holding</h3>
          {loading ? <div className="skeleton h200" /> : null}
          {holdings.length === 0 && !loading ? <div className="muted">No holdings yet.</div> : null}

          <div className="barList">
            {holdings.map((h) => {
              const pe = h.pe === null || h.pe === undefined ? null : Number(h.pe);
              const pctWidth = pe !== null && maxPE ? Math.max(2, Math.min(100, (pe / maxPE) * 100)) : 2;
              return (
                <div className="barRow" key={h.symbol}>
                  <div className="barLeft">
                    <div className="strong mono">{h.symbol}</div>
                    <div className="muted small">{h.name}</div>
                  </div>
                  <div className="barMid">
                    <div className="barTrack">
                      <div className="barFill" style={{ width: `${pctWidth}%` }} />
                    </div>
                  </div>
                  <div className="barRight mono">{pe === null || Number.isNaN(pe) ? "--" : fmt(pe)}</div>
                </div>
              );
            })}
          </div>
        </section>

        <section className="card" style={{ gridColumn: "1 / -1" }}>
          <h3>Discount from 52W high</h3>
          <div className="muted small">Discount % = (52W High - Last) / 52W High × 100.</div>
          {loading ? <div className="skeleton h200" /> : null}

          <div className="vbarWrap">
            <div className="vbarGrid">
              {discountPoints.map((p) => {
                const hPct = maxDiscount ? Math.max(2, Math.min(100, (p.discount / maxDiscount) * 100)) : 2;
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
        </section>

        <section className="card" style={{ gridColumn: "1 / -1" }}>
          <h3>Future forecast (Portfolio value)</h3>
          <div className="muted small">A simple, explainable forecast for the next 90 days (for EDA/demo only).</div>
          {forecastBusy ? <div className="skeleton h200" /> : null}
          {!forecastBusy && forecastPoints.length ? <LineChart points={forecastPoints} xLabel="Next 90 days" yLabel="Portfolio value" /> : null}
          <div className="muted small" style={{ marginTop: 10 }}>
            {forecast?.disclaimer || "Educational forecast only. Improve later with better models."}
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}
