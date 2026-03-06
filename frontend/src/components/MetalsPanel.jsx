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

function clamp(v, a, b) {
  return Math.max(a, Math.min(b, v));
}

function SparkDual({ series = [] }) {
  const w = 520;
  const h = 180;
  const pad = 14;
  const plotW = w - pad * 2;
  const plotH = h - pad * 2;

  const pts = useMemo(() => {
    const xs = series.map((_, i) => i);
    const gold = series.map((p) => Number(p.gold)).filter((x) => Number.isFinite(x));
    const silver = series.map((p) => Number(p.silver)).filter((x) => Number.isFinite(x));
    if (!gold.length || !silver.length || series.length < 2) return null;

    const gMin = Math.min(...gold);
    const gMax = Math.max(...gold);
    const sMin = Math.min(...silver);
    const sMax = Math.max(...silver);

    const toY = (v, min, max) => {
      if (max === min) return pad + plotH / 2;
      const t = (v - min) / (max - min);
      return pad + (1 - t) * plotH;
    };
    const toX = (i) => pad + (i / (series.length - 1)) * plotW;

    const gPath = series
      .map((p, i) => {
        const v = Number(p.gold);
        if (!Number.isFinite(v)) return null;
        const x = toX(i);
        const y = toY(v, gMin, gMax);
        return `${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
      })
      .filter(Boolean)
      .join(" ");

    const sPath = series
      .map((p, i) => {
        const v = Number(p.silver);
        if (!Number.isFinite(v)) return null;
        const x = toX(i);
        const y = toY(v, sMin, sMax);
        return `${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
      })
      .filter(Boolean)
      .join(" ");

    const last = series[series.length - 1];
    const lastX = toX(series.length - 1);
    return { gPath, sPath, lastX, last };
  }, [series]);

  if (!pts) {
    return <div className="skeleton h200" />;
  }

  return (
    <svg className="metalsSpark" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Gold and Silver (7d)">
      <defs>
        <linearGradient id="gLine" x1="0" x2="1">
          <stop offset="0" stopColor="rgba(255,210,120,0.2)" />
          <stop offset="1" stopColor="rgba(255,210,120,0.85)" />
        </linearGradient>
        <linearGradient id="sLine" x1="0" x2="1">
          <stop offset="0" stopColor="rgba(160,210,255,0.2)" />
          <stop offset="1" stopColor="rgba(160,210,255,0.85)" />
        </linearGradient>
        <linearGradient id="gridFade" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="rgba(255,255,255,0.08)" />
          <stop offset="1" stopColor="rgba(255,255,255,0.02)" />
        </linearGradient>
      </defs>

      {/* grid */}
      <rect x="0" y="0" width={w} height={h} fill="transparent" />
      {[0.25, 0.5, 0.75].map((t) => (
        <line
          key={t}
          x1={pad}
          x2={w - pad}
          y1={pad + t * plotH}
          y2={pad + t * plotH}
          stroke="url(#gridFade)"
          strokeWidth="1"
        />
      ))}

      {/* lines */}
      <path d={pts.gPath} fill="none" stroke="url(#gLine)" strokeWidth="3" strokeLinecap="round" />
      <path d={pts.sPath} fill="none" stroke="url(#sLine)" strokeWidth="3" strokeLinecap="round" />

      {/* last marker */}
      <line x1={pts.lastX} x2={pts.lastX} y1={pad} y2={h - pad} stroke="rgba(255,255,255,0.08)" />
      <circle cx={pts.lastX} cy={pad + 8} r="3.5" fill="rgba(255,210,120,0.8)" />
      <circle cx={pts.lastX} cy={pad + 22} r="3.5" fill="rgba(160,210,255,0.8)" />
    </svg>
  );
}

export default function MetalsPanel() {
  const [data, setData] = useState(null);
  const [news, setNews] = useState([]);
  const [busy, setBusy] = useState(true);
  const [newsBusy, setNewsBusy] = useState(false);
  const [liveQuote, setLiveQuote] = useState(null);
  const [err, setErr] = useState("");
  const [horizon, setHorizon] = useState("1w");
  const [forecast, setForecast] = useState(null);
  const [forecastBusy, setForecastBusy] = useState(false);
  const [forecastErr, setForecastErr] = useState("");
  const [forecastOpen, setForecastOpen] = useState(false);
  const [forecastCache, setForecastCache] = useState({});

  async function refreshSummary({ silent = false } = {}) {
    if (!silent) setBusy(true);
    setErr("");
    try {
      const d = await api.metalsSummary(7);
      setData(d);
      try {
        localStorage.setItem("metalsSummaryCache", JSON.stringify(d));
      } catch {}
    } catch (e) {
      setErr(e?.message || "Metals data unavailable right now");
      setData((prev) => prev || null);
    } finally {
      if (!silent) setBusy(false);
    }
  }

  useEffect(() => {
    let alive = true;
    setBusy(true);
    // Instant paint from local cache (so hosted "cold starts" feel fast).
    try {
      const raw = localStorage.getItem("metalsSummaryCache");
      if (raw) {
        const cached = JSON.parse(raw);
        if (cached && typeof cached === "object") {
          setData(cached);
          setBusy(false);
        }
      }
    } catch {}

    // Refresh in background (does not block render)
    const t = setTimeout(() => {
      refreshSummary({ silent: true }).finally(() => {
        if (!alive) return;
        setBusy(false);
      });
    }, 50);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, []);

  // Poll tiny quote endpoint to update only last/prev every ~20s (fast, cached server-side).
  useEffect(() => {
    let alive = true;
    const fetchQuote = () =>
      api
        .metalsQuote(20)
        .then((q) => {
          if (!alive) return;
          setLiveQuote(q);
        })
        .catch(() => {});

    fetchQuote();
    const id = setInterval(fetchQuote, 20000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    let alive = true;
    if (!data) return;
    setNewsBusy(true);
    const t = setTimeout(() => {
      api
        .metalsNews(6)
        .then((d) => {
          if (!alive) return;
          setNews(d?.items || []);
        })
        .catch(() => {
          if (!alive) return;
          setNews([]);
        })
        .finally(() => {
          if (!alive) return;
          setNewsBusy(false);
        });
    }, 400);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [data]);

  // Load forecast only when the modal is open (keeps landing fast).
  useEffect(() => {
    let alive = true;
    if (!forecastOpen) return () => {};

    const cached = forecastCache?.[horizon];
    if (cached) {
      setForecast(cached);
      setForecastErr("");
      setForecastBusy(false);
      return () => {
        alive = false;
      };
    }

    setForecastErr("");
    setForecastBusy(true);
    api
      .metalsForecast(horizon)
      .then((d) => {
        if (!alive) return;
        setForecast(d);
        setForecastCache((prev) => ({ ...(prev || {}), [horizon]: d }));
      })
      .catch((e) => {
        if (!alive) return;
        setForecastErr(e?.message || "Forecast unavailable");
        setForecast(null);
      })
      .finally(() => {
        if (!alive) return;
        setForecastBusy(false);
      });

    return () => {
      alive = false;
    };
  }, [forecastOpen, horizon, forecastCache]);

  const gold = liveQuote?.gold?.last_price !== undefined ? { ...data?.gold, ...liveQuote?.gold } : data?.gold;
  const silver = liveQuote?.silver?.last_price !== undefined ? { ...data?.silver, ...liveQuote?.silver } : data?.silver;
  const series = data?.series || [];
  const m = data?.metrics || {};

  const goldLast = gold?.last_price ?? null;
  const goldPrev = gold?.previous_close ?? null;
  const silverLast = silver?.last_price ?? null;
  const silverPrev = silver?.previous_close ?? null;

  const goldChgPct =
    goldLast !== null && goldPrev !== null && Number(goldPrev) !== 0 ? ((Number(goldLast) - Number(goldPrev)) / Number(goldPrev)) * 100 : null;
  const silverChgPct =
    silverLast !== null && silverPrev !== null && Number(silverPrev) !== 0
      ? ((Number(silverLast) - Number(silverPrev)) / Number(silverPrev)) * 100
      : null;

  const corr = m?.corr_7d ?? null;
  const corrLabel = corr === null ? "--" : fmt(corr, 2);
  const corrTone = corr === null ? "" : corr >= 0.6 ? "pos" : corr <= -0.6 ? "neg" : "";

  const ratio = m?.gold_silver_ratio ?? null;
  const gold7 = m?.gold_7d_return_pct ?? null;
  const sil7 = m?.silver_7d_return_pct ?? null;

  const quickTake = useMemo(() => {
    const out = [];
    if (gold7 !== null && Number.isFinite(Number(gold7))) {
      out.push(`Gold 7d momentum: ${pct(gold7)} (${Number(gold7) >= 0 ? "bid" : "soft"}).`);
    }
    if (sil7 !== null && Number.isFinite(Number(sil7))) {
      out.push(`Silver 7d momentum: ${pct(sil7)} (${Number(sil7) >= 0 ? "strength" : "pullback"}).`);
    }
    if (corr !== null && Number.isFinite(Number(corr))) {
      const c = Number(corr);
      out.push(c >= 0.6 ? "High co-move: moves are usually aligned." : c <= -0.6 ? "Inverse co-move: hedge-like behavior." : "Mixed co-move: drivers differ this week.");
    }
    if (ratio !== null && Number.isFinite(Number(ratio))) {
      const r = Number(ratio);
      out.push(`Gold/Silver ratio: ${fmt(r, 1)} (context: higher = gold relatively expensive).`);
    }
    // small, explainable “prediction”
    if (gold7 !== null && sil7 !== null) {
      const g = Number(gold7);
      const s = Number(sil7);
      if (Number.isFinite(g) && Number.isFinite(s)) {
        const tilt = s - g;
        if (tilt > 2) out.push("Quick take: Silver is leading — if risk-on continues, silver often stays more volatile.");
        else if (tilt < -2) out.push("Quick take: Gold is leading — could signal defensive positioning.");
        else out.push("Quick take: Both are moving similarly — watch USD/rates news for the next impulse.");
      }
    }
    out.push("Educational only — not investment advice.");
    return out.slice(0, 6);
  }, [corr, gold7, ratio, sil7]);

  const unavailable = !busy && (!data || data?.available === false);

  const horizonLabel =
    horizon === "1h" ? "Next 1 hour" : horizon === "1w" ? "Next 1 week" : horizon === "1m" ? "Next 1 month" : "Next 1 year";

  const goldPred = forecast?.gold?.predicted_end ?? null;
  const silverPred = forecast?.silver?.predicted_end ?? null;

  const forecastPointsGold = useMemo(() => {
    const s = forecast?.gold?.series || [];
    if (!s.length) return [];
    const last = s.length - 1;
    return s.map((p, idx) => ({
      x: String(p.t),
      xLabel: idx === 0 ? "Now" : idx === last ? "End" : "",
      y: p.base
    }));
  }, [forecast]);

  const forecastPointsSilver = useMemo(() => {
    const s = forecast?.silver?.series || [];
    if (!s.length) return [];
    const last = s.length - 1;
    return s.map((p, idx) => ({
      x: String(p.t),
      xLabel: idx === 0 ? "Now" : idx === last ? "End" : "",
      y: p.base
    }));
  }, [forecast]);

  function ForecastModal() {
    if (!forecastOpen) return null;
    return (
      <div className="modalBackdrop" role="dialog" aria-modal="true" onClick={() => setForecastOpen(false)}>
        <div className="modal metalsForecastModal" onClick={(e) => e.stopPropagation()}>
          <div className="modalHeader">
            <div>
              <h2 style={{ margin: 0 }}>Metals forecast</h2>
              <div className="muted small" style={{ marginTop: 4 }}>
                {horizonLabel} • Educational only
              </div>
            </div>
            <button className="btn ghost" type="button" onClick={() => setForecastOpen(false)} aria-label="Close">
              ×
            </button>
          </div>

          <div className="metalsForecastModalHead">
            <div className="metalsForecastKpis">
              <div className="kpi metalsKpi">
                <div className="kpiLabel">Gold predicted</div>
                <div className="kpiValue">{fmt(goldPred)}</div>
                <div className="muted small">USD</div>
              </div>
              <div className="kpi metalsKpi">
                <div className="kpiLabel">Silver predicted</div>
                <div className="kpiValue">{fmt(silverPred)}</div>
                <div className="muted small">USD</div>
              </div>
            </div>

            <label className="metalsSelect">
              <div className="muted small" style={{ marginBottom: 6 }}>
                Choose horizon
              </div>
              <select className="input" value={horizon} onChange={(e) => setHorizon(e.target.value)}>
                <option value="1h">1 hour</option>
                <option value="1w">1 week</option>
                <option value="1m">1 month</option>
                <option value="1y">1 year</option>
              </select>
            </label>
          </div>

          {forecastBusy ? (
            <div className="metalsForecastLoading">
              <div className="metalsSpinner" aria-hidden="true" /> <div className="muted small">Computing forecast…</div>
            </div>
          ) : null}
          {forecastErr ? <div className="muted small" style={{ marginTop: 8 }}>{forecastErr}</div> : null}

          <div className="metalsForecastCharts">
            <div className="metalsMiniChart">
              <div className="muted small" style={{ marginBottom: 6 }}>
                Gold path
              </div>
              {forecastPointsGold.length ? (
                <LineChart points={forecastPointsGold} height={220} xLabel="Horizon" yLabel="USD" />
              ) : (
                <div className="skeleton h200" />
              )}
            </div>
            <div className="metalsMiniChart">
              <div className="muted small" style={{ marginBottom: 6 }}>
                Silver path
              </div>
              {forecastPointsSilver.length ? (
                <LineChart points={forecastPointsSilver} height={220} xLabel="Horizon" yLabel="USD" />
              ) : (
                <div className="skeleton h200" />
              )}
            </div>
          </div>

          <div className="muted small" style={{ marginTop: 10 }}>
            {forecast?.disclaimer || "Educational forecast only."}
          </div>
        </div>
      </div>
    );
  }

  return (
    <section className="card metalsCard">
      <div className="metalsHead">
        <div>
          <div className="badge soft">Commodities</div>
          <h2 className="landingH2" style={{ margin: "10px 0 0" }}>
            Gold & Silver
          </h2>
          <div className="muted small" style={{ marginTop: 6 }}>
            7-day snapshot: spot quotes, co-move, and quick context.
          </div>
        </div>

        <div className="metalsBadges">
          <div className={`metalsPill ${corrTone}`}>
            Corr (7d): <span className="mono strong">{corrLabel}</span>
          </div>
          <div className="metalsPill">
            Ratio: <span className="mono strong">{ratio === null ? "--" : fmt(ratio, 1)}</span>
          </div>
        </div>
      </div>

      {busy && !data ? (
        <div className="metalsLoading">
          <div className="metalsSpinner" aria-hidden="true" />
          <div>
            <div className="strong">Loading metals snapshot…</div>
            <div className="muted small">Fetching gold & silver (cached).</div>
          </div>
        </div>
      ) : null}

      {data ? (
        <div className="metalsGrid">
          <div className="metalsLeft">
            <div className="metalsPrices">
              <div className="kpi metalsKpi">
                <div className="kpiLabel">Gold (spot)</div>
                <div className="kpiValue">{fmt(goldLast)}</div>
                <div className={goldChgPct === null ? "muted small mono" : goldChgPct >= 0 ? "small mono pos" : "small mono neg"}>
                  {goldChgPct === null ? "--" : pct(goldChgPct)}
                </div>
              </div>
              <div className="kpi metalsKpi">
                <div className="kpiLabel">Silver (spot)</div>
                <div className="kpiValue">{fmt(silverLast)}</div>
                <div className={silverChgPct === null ? "muted small mono" : silverChgPct >= 0 ? "small mono pos" : "small mono neg"}>
                  {silverChgPct === null ? "--" : pct(silverChgPct)}
                </div>
              </div>
              <div className="kpi metalsKpi">
                <div className="kpiLabel">7d returns</div>
                <div className="metalsTwo">
                  <div className={gold7 === null ? "muted small mono" : Number(gold7) >= 0 ? "small mono pos" : "small mono neg"}>
                    Gold: {gold7 === null ? "--" : pct(gold7)}
                  </div>
                  <div className={sil7 === null ? "muted small mono" : Number(sil7) >= 0 ? "small mono pos" : "small mono neg"}>
                    Silver: {sil7 === null ? "--" : pct(sil7)}
                  </div>
                </div>
                <div className="muted small" style={{ marginTop: 6 }}>
                  Cached • fast widget
                </div>
              </div>
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
                <div className="strong">Metals news</div>
                <div className="muted small">{newsBusy ? "Updating..." : "Best-effort"}</div>
              </div>
              {newsBusy ? <div className="skeleton h100" /> : null}
              {!newsBusy && news.length === 0 ? <div className="muted small">News unavailable right now.</div> : null}
              <div className="metalsNews">
                {news.slice(0, 5).map((n) => (
                  <a key={n.link} className="metalsNewsItem" href={n.link} target="_blank" rel="noreferrer">
                    <div className="strong" style={{ fontSize: 13 }}>
                      {n.title}
                    </div>
                    <div className="muted small">{n.publisher || "Source"}</div>
                  </a>
                ))}
              </div>
            </div>

            {unavailable || err ? (
              <div className="metalsBox" style={{ borderColor: "rgba(255,255,255,0.14)" }}>
                <div className="sectionRow">
                  <div className="strong">Having trouble loading</div>
                  <button className="btn ghost sm" type="button" onClick={() => refreshSummary()}>
                    Retry
                  </button>
                </div>
                <div className="muted small" style={{ marginTop: 8 }}>
                  {err || "Metals feed returned no data (this happens sometimes on hosted environments)."}
                </div>
                <div className="muted small" style={{ marginTop: 8 }}>
                  Tip: refresh after a few seconds; we also fall back to futures tickers when spot quotes fail.
                </div>
              </div>
            ) : null}
          </div>

          <div className="metalsRight">
            <div className="metalsChartCard">
              <div className="metalsChartHead">
                <div className="strong">7-day co-move</div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                  <button className="btn ghost sm" type="button" onClick={() => setForecastOpen(true)}>
                    Forecast
                  </button>
                  <div className="muted small">Gold vs Silver (scaled)</div>
                </div>
              </div>
              {series.length ? <SparkDual series={series} /> : <div className="skeleton h200" />}
              <div className="metalsLegend">
                <span className="metalsKey gold" /> Gold
                <span className="metalsKey silver" /> Silver
              </div>
              <div className="muted small" style={{ marginTop: 8 }}>
                {data?.note || "Educational only."}
              </div>
            </div>
          </div>
        </div>
      ) : null}

      <ForecastModal />
    </section>
  );
}
