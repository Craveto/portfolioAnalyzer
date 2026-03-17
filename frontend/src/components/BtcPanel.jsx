import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import LineChart from "./LineChart.jsx";

function fmt(n, digits = 2) {
  if (n === null || n === undefined) return "--";
  const num = Number(n);
  if (!Number.isFinite(num)) return "--";
  return num.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function pct(n) {
  if (n === null || n === undefined) return "--";
  const num = Number(n);
  if (!Number.isFinite(num)) return "--";
  const s = num >= 0 ? "+" : "";
  return `${s}${fmt(num, 2)}%`;
}

const HORIZON_OPTIONS = [
  { value: "1w", label: "1 week" },
  { value: "1m", label: "1 month" },
  { value: "3m", label: "3 months" }
];

const ALGO_ORDER = ["linear", "logistic", "arima", "momentum", "mean_reversion", "ema_trend", "correlation"];

export default function BtcPanel() {
  const [summary, setSummary] = useState(null);
  const [predictions, setPredictions] = useState(null);
  const [news, setNews] = useState([]);
  const [busy, setBusy] = useState(true);
  const [predBusy, setPredBusy] = useState(false);
  const [err, setErr] = useState("");
  const [predErr, setPredErr] = useState("");
  const [activeAlgo, setActiveAlgo] = useState("linear");
  const [horizon, setHorizon] = useState("1m");
  const [liveQuote, setLiveQuote] = useState(null);

  async function refreshSummary({ silent = false } = {}) {
    if (!silent) setBusy(true);
    setErr("");
    try {
      const d = await api.btcSummary(30);
      setSummary(d);
      localStorage.setItem("btcSummaryCache", JSON.stringify(d));
    } catch (e) {
      setErr(e?.message || "BTC data unavailable right now");
      setSummary((prev) => prev || null);
    } finally {
      if (!silent) setBusy(false);
    }
  }

  useEffect(() => {
    let alive = true;
    try {
      const raw = localStorage.getItem("btcSummaryCache");
      if (raw) {
        const cached = JSON.parse(raw);
        if (cached && typeof cached === "object") {
          setSummary(cached);
          setBusy(false);
        }
      }
    } catch {}
    const t = setTimeout(() => {
      refreshSummary({ silent: true }).finally(() => {
        if (alive) setBusy(false);
      });
    }, 50);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, []);

  useEffect(() => {
    let alive = true;
    const loadQuote = () =>
      api
        .btcQuote(20)
        .then((d) => {
          if (alive) setLiveQuote(d);
        })
        .catch(() => {});
    loadQuote();
    const id = setInterval(loadQuote, 20000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    let alive = true;
    api
      .btcNews(5)
      .then((d) => {
        if (alive) setNews(d?.items || []);
      })
      .catch(() => {
        if (alive) setNews([]);
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    let alive = true;
    setPredBusy(true);
    setPredErr("");
    api
      .btcPredictions(horizon)
      .then((d) => {
        if (alive) setPredictions(d);
      })
      .catch((e) => {
        if (alive) {
          setPredictions(null);
          setPredErr(e?.message || "Predictions unavailable");
        }
      })
      .finally(() => {
        if (alive) setPredBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [horizon]);

  const quote = liveQuote?.last_price !== undefined ? liveQuote : summary?.quote;
  const last = quote?.last_price ?? null;
  const prev = quote?.previous_close ?? null;
  const changePct = last !== null && prev !== null && Number(prev) !== 0 ? ((Number(last) - Number(prev)) / Number(prev)) * 100 : null;
  const records = summary?.records || {};
  const metrics = summary?.metrics || {};
  const correlations = predictions?.correlations || summary?.correlations || [];

  const historyPoints = useMemo(() => {
    const s = summary?.series || [];
    if (!s.length) return [];
    const lastIdx = s.length - 1;
    return s.map((p, idx) => ({
      x: p.date,
      xLabel: idx === 0 ? p.date.slice(5, 10) : idx === lastIdx ? p.date.slice(5, 10) : "",
      y: p.close
    }));
  }, [summary]);

  const algoData = predictions?.algorithms?.[activeAlgo] || null;
  const algoPoints = useMemo(() => {
    const s = algoData?.series || [];
    if (!s.length) return [];
    return s.map((p) => ({
      x: String(p.t),
      xLabel: p.xLabel || "",
      y: p.price
    }));
  }, [algoData]);

  const quickTake = useMemo(() => {
    const notes = [];
    if (metrics.return_30d_pct !== null && metrics.return_30d_pct !== undefined) {
      notes.push(`30d momentum: ${pct(metrics.return_30d_pct)}.`);
    }
    if (metrics.volatility_30d_annualized_pct !== null && metrics.volatility_30d_annualized_pct !== undefined) {
      notes.push(`Annualized volatility: ${fmt(metrics.volatility_30d_annualized_pct)}% — expect larger swings than equities.`);
    }
    if (records.ath_5y !== null && records.ath_5y !== undefined && last !== null) {
      const gap = ((Number(records.ath_5y) - Number(last)) / Number(records.ath_5y)) * 100;
      notes.push(`Distance from 5y high: ${pct(-gap)} from the record zone.`);
    }
    if (correlations.length) {
      const strongest = [...correlations]
        .filter((c) => c.correlation !== null && c.correlation !== undefined)
        .sort((a, b) => Math.abs(Number(b.correlation)) - Math.abs(Number(a.correlation)))[0];
      if (strongest) notes.push(`Strongest recent relationship: ${strongest.label} (${fmt(strongest.correlation, 2)}).`);
    }
    notes.push("Use forecasts as scenario tools, not price promises.");
    return notes.slice(0, 5);
  }, [correlations, last, metrics, records]);

  return (
    <section className="card btcCard">
      <div className="metalsHead">
        <div>
          <div className="badge soft">Crypto</div>
          <h2 className="landingH2" style={{ margin: "10px 0 0" }}>
            Bitcoin live desk
          </h2>
          <div className="muted small" style={{ marginTop: 6 }}>
            Live-ish BTC value, key records, predictive models, and market relationships.
          </div>
        </div>

        <div className="metalsBadges">
          <div className={`metalsPill ${changePct !== null && changePct >= 0 ? "pos" : "neg"}`}>
            24h move: <span className="mono strong">{pct(changePct)}</span>
          </div>
          <div className="metalsPill">
            30d vol: <span className="mono strong">{metrics.volatility_30d_annualized_pct === null || metrics.volatility_30d_annualized_pct === undefined ? "--" : `${fmt(metrics.volatility_30d_annualized_pct)}%`}</span>
          </div>
        </div>
      </div>

      {busy && !summary ? (
        <div className="metalsLoading">
          <div className="metalsSpinner" aria-hidden="true" />
          <div>
            <div className="strong">Loading BTC snapshot…</div>
            <div className="muted small">Fetching crypto records and live quote.</div>
          </div>
        </div>
      ) : null}

      {summary ? (
        <div className="btcGrid">
          <div className="btcLeft">
            <div className="btcKpis">
              <div className="kpi metalsKpi">
                <div className="kpiLabel">BTC/USD</div>
                <div className="kpiValue">{fmt(last)}</div>
                <div className={changePct === null ? "muted small mono" : changePct >= 0 ? "small mono pos" : "small mono neg"}>
                  {pct(changePct)}
                </div>
              </div>
              <div className="kpi metalsKpi">
                <div className="kpiLabel">24h range</div>
                <div className="kpiValue">{fmt(records.day_high)}</div>
                <div className="muted small">Low: {fmt(records.day_low)}</div>
              </div>
              <div className="kpi metalsKpi">
                <div className="kpiLabel">52W range</div>
                <div className="kpiValue">{fmt(records.high_52w)}</div>
                <div className="muted small">Low: {fmt(records.low_52w)}</div>
              </div>
              <div className="kpi metalsKpi">
                <div className="kpiLabel">5Y record</div>
                <div className="kpiValue">{fmt(records.ath_5y)}</div>
                <div className="muted small">30d ret: {pct(metrics.return_30d_pct)}</div>
              </div>
            </div>

            <div className="metalsBox">
              <div className="sectionRow" style={{ marginBottom: 8 }}>
                <div className="strong">BTC trend</div>
                <div className="muted small">Recent close history</div>
              </div>
              {historyPoints.length ? <LineChart points={historyPoints} height={240} xLabel="Days" yLabel="USD" /> : <div className="skeleton h200" />}
            </div>

            <div className="metalsBox">
              <div className="strong">Quick context</div>
              <ul className="metalsBullets">
                {quickTake.map((t, idx) => (
                  <li key={idx}>{t}</li>
                ))}
              </ul>
            </div>

            <div className="metalsBox">
              <div className="sectionRow" style={{ marginBottom: 6 }}>
                <div className="strong">BTC headlines</div>
                <div className="muted small">Best-effort</div>
              </div>
              {news.length === 0 ? <div className="muted small">News unavailable right now.</div> : null}
              <div className="metalsNews">
                {news.slice(0, 5).map((n) => (
                  <a key={n.link} className="metalsNewsItem" href={n.link} target="_blank" rel="noreferrer">
                    <div className="strong" style={{ fontSize: 13 }}>{n.title}</div>
                    <div className="muted small">{n.publisher || "Source"}</div>
                  </a>
                ))}
              </div>
            </div>

            {err ? (
              <div className="metalsBox">
                <div className="sectionRow">
                  <div className="strong">Having trouble loading</div>
                  <button className="btn ghost sm" type="button" onClick={() => refreshSummary()}>
                    Retry
                  </button>
                </div>
                <div className="muted small" style={{ marginTop: 8 }}>{err}</div>
              </div>
            ) : null}
          </div>

          <div className="btcRight">
            <div className="metalsChartCard">
              <div className="btcPredictHead">
                <div>
                  <div className="strong">Prediction lab</div>
                  <div className="muted small">Switch models to compare scenarios.</div>
                </div>
                <label className="metalsSelect">
                  <div className="muted small" style={{ marginBottom: 6 }}>Horizon</div>
                  <select className="input" value={horizon} onChange={(e) => setHorizon(e.target.value)}>
                    {HORIZON_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                </label>
              </div>

              <div className="btcAlgoTabs">
                {ALGO_ORDER.map((key) => (
                  <button
                    key={key}
                    className={activeAlgo === key ? "seg active" : "seg"}
                    type="button"
                    onClick={() => setActiveAlgo(key)}
                  >
                    {predictions?.algorithms?.[key]?.label || key}
                  </button>
                ))}
              </div>

              {predBusy ? <div className="metalsForecastLoading"><div className="metalsSpinner" /> <div className="muted small">Computing model outputs…</div></div> : null}
              {predErr ? <div className="muted small" style={{ marginTop: 10 }}>{predErr}</div> : null}

              {activeAlgo !== "correlation" ? (
                <>
                  <div className="btcAlgoSummary">
                    <div className="kpi metalsKpi">
                      <div className="kpiLabel">{algoData?.label || "Model"}</div>
                      <div className="kpiValue">{fmt(algoData?.predicted_end)}</div>
                      <div className="muted small">{algoData?.summary || "Educational scenario path."}</div>
                    </div>
                  </div>
                  {algoPoints.length ? <LineChart points={algoPoints} height={240} xLabel="Forecast" yLabel="USD" /> : <div className="skeleton h200" />}
                  {activeAlgo === "logistic" && algoData?.probability_up !== undefined ? (
                    <div className="muted small" style={{ marginTop: 8 }}>
                      Probability of upside continuation: <span className="mono strong">{fmt(Number(algoData.probability_up) * 100)}%</span>
                    </div>
                  ) : null}
                </>
              ) : (
                <div className="btcCorrelationGrid">
                  {correlations.map((row) => {
                    const corr = row?.correlation;
                    const pctWidth = corr === null || corr === undefined ? 4 : Math.max(6, Math.abs(Number(corr)) * 100);
                    return (
                      <div key={row.label} className="btcCorrelationRow">
                        <div>
                          <div className="strong">{row.label}</div>
                          <div className="muted small">{row.symbol}</div>
                        </div>
                        <div className="btcCorrelationBar">
                          <div
                            className={corr === null || corr === undefined ? "btcCorrelationFill" : Number(corr) >= 0 ? "btcCorrelationFill pos" : "btcCorrelationFill neg"}
                            style={{ width: `${pctWidth}%` }}
                          />
                        </div>
                        <div className="mono">{corr === null || corr === undefined ? "--" : fmt(corr, 2)}</div>
                      </div>
                    );
                  })}
                  <div className="muted small">{algoData?.summary || "Compare BTC against risk and commodity assets over recent returns."}</div>
                </div>
              )}

              <div className="muted small" style={{ marginTop: 10 }}>
                {predictions?.disclaimer || "Educational only. Use this to compare scenarios, not to trade blindly."}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
