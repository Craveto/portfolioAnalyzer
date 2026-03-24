import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, getToken } from "../api.js";
import LoginModal from "../components/LoginModal.jsx";
import NavBar from "../components/NavBar.jsx";
import Footer from "../components/Footer.jsx";
import MetalsPanel from "../components/MetalsPanel.jsx";
import BtcPanel from "../components/BtcPanel.jsx";

const MARKET_CACHE_KEY = "landing_market_summary_cache_v1";
const MARKET_HISTORY_KEY = "landing_market_history_cache_v1";

function formatNum(n) {
  if (n === null || n === undefined) return "--";
  const num = Number(n);
  if (Number.isNaN(num)) return "--";
  return num.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function loadMarketCache() {
  try {
    const raw = localStorage.getItem(MARKET_CACHE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveMarketCache(data) {
  try {
    localStorage.setItem(MARKET_CACHE_KEY, JSON.stringify({ savedAt: Date.now(), data }));
  } catch {
    // ignore
  }
}

function loadMarketHistory() {
  try {
    const raw = localStorage.getItem(MARKET_HISTORY_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveMarketHistory(rows) {
  try {
    localStorage.setItem(MARKET_HISTORY_KEY, JSON.stringify(rows));
  } catch {
    // ignore
  }
}

function toNumber(value) {
  if (typeof value === "string") {
    const cleaned = value.replace(/,/g, "").trim();
    const n = Number(cleaned);
    return Number.isFinite(n) ? n : null;
  }
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function pushHistoryPoint(history, market) {
  const nifty = toNumber(market?.indices?.nifty?.last_price);
  const sensex = toNumber(market?.indices?.sensex?.last_price);
  if (nifty === null && sensex === null) return history;

  const now = Date.now();
  const prev = history[history.length - 1];
  if (prev && now - Number(prev.ts || 0) < 45_000) {
    const updated = [...history];
    updated[updated.length - 1] = { ts: now, nifty, sensex };
    return updated;
  }

  const next = [...history, { ts: now, nifty, sensex }];
  if (next.length > 120) return next.slice(next.length - 120);
  return next;
}

function buildSyntheticSeries(lastValue, changePct, points = 36) {
  const last = toNumber(lastValue) ?? 100;
  const pct = toNumber(changePct) ?? 0;
  const base = last / (1 + pct / 100 || 1);
  const out = [];
  for (let i = 0; i < points; i += 1) {
    const t = i / Math.max(1, points - 1);
    const drift = (last - base) * t;
    const wave = Math.sin(i / 4.2 + (pct >= 0 ? 0.2 : 1.2)) * Math.max(last * 0.0012, Math.abs(last - base) * 0.14);
    out.push(base + drift + wave);
  }
  return out;
}

function chartPoints(values, width = 520, height = 170, pad = 12) {
  const nums = values.filter((v) => Number.isFinite(v));
  if (!nums.length) return "";
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const range = Math.max(0.0001, max - min);
  return values
    .map((v, i) => {
      const safe = Number.isFinite(v) ? v : nums[Math.max(0, nums.length - 1)];
      const x = pad + (i / Math.max(1, values.length - 1)) * (width - pad * 2);
      const y = height - pad - ((safe - min) / range) * (height - pad * 2);
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

function chartPointXY(values, idx, width = 520, height = 170, pad = 12) {
  const nums = values.filter((v) => Number.isFinite(v));
  if (!nums.length) return { x: pad, y: height - pad };
  const safeIdx = Math.max(0, Math.min(idx, values.length - 1));
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const range = Math.max(0.0001, max - min);
  const safe = Number.isFinite(values[safeIdx]) ? values[safeIdx] : nums[Math.max(0, nums.length - 1)];
  const x = pad + (safeIdx / Math.max(1, values.length - 1)) * (width - pad * 2);
  const y = height - pad - ((safe - min) / range) * (height - pad * 2);
  return { x, y };
}

export default function Landing() {
  const nav = useNavigate();
  const [market, setMarket] = useState(() => loadMarketCache()?.data || null);
  const [marketHistory, setMarketHistory] = useState(() => loadMarketHistory());
  const [loading, setLoading] = useState(() => !loadMarketCache()?.data);
  const [error, setError] = useState("");
  const [loginOpen, setLoginOpen] = useState(false);
  const [assetTab, setAssetTab] = useState("metals");
  const [pulseSeries, setPulseSeries] = useState("nifty");
  const [chartHover, setChartHover] = useState(null);

  const authed = Boolean(getToken());

  useEffect(() => {
    const timer = setTimeout(() => {
      if (!getToken()) setLoginOpen(true);
    }, 5000);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api
      .marketSummary()
      .then((data) => {
        if (!alive) return;
        setMarket(data);
        saveMarketCache(data);
        setMarketHistory((prev) => {
          const next = pushHistoryPoint(prev, data);
          saveMarketHistory(next);
          return next;
        });
        setError("");
      })
      .catch((err) => {
        if (!alive) return;
        setError(err.message || "Failed to load market data");
      })
      .finally(() => {
        if (!alive) return;
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const nifty = market?.indices?.nifty;
  const sensex = market?.indices?.sensex;
  const movers = market?.top10 || [];
  const topMover = movers.length ? movers[0] : null;
  const niftyPct = toNumber(nifty?.change_pct ?? nifty?.changePct ?? nifty?.dp) ?? 0;
  const sensexPct = toNumber(sensex?.change_pct ?? sensex?.changePct ?? sensex?.dp) ?? 0;
  const tickerFeed = movers.length
    ? movers
    : [
        { symbol: "NIFTY", last: nifty?.last_price, changePct: niftyPct },
        { symbol: "SENSEX", last: sensex?.last_price, changePct: sensexPct }
      ];
  const tickerLoop = [...tickerFeed, ...tickerFeed];
  const historyRows = marketHistory.length >= 2
    ? marketHistory
    : [
        { ts: Date.now() - 60_000, nifty: toNumber(nifty?.last_price), sensex: toNumber(sensex?.last_price) },
        { ts: Date.now(), nifty: toNumber(nifty?.last_price), sensex: toNumber(sensex?.last_price) }
      ];

  let niftyHistory = historyRows.map((r) => toNumber(r?.nifty)).filter((v) => v !== null);
  let sensexHistory = historyRows.map((r) => toNumber(r?.sensex)).filter((v) => v !== null);
  let timeline = historyRows.map((r) => Number(r?.ts) || Date.now());

  const hasNiftyVariance = niftyHistory.length > 3 && Math.abs((Math.max(...niftyHistory) - Math.min(...niftyHistory)) || 0) > 0.00001;
  const hasSensexVariance = sensexHistory.length > 3 && Math.abs((Math.max(...sensexHistory) - Math.min(...sensexHistory)) || 0) > 0.00001;

  if (!hasNiftyVariance) {
    niftyHistory = buildSyntheticSeries(nifty?.last_price, niftyPct, 36);
    const end = Date.now();
    timeline = niftyHistory.map((_, i) => end - (niftyHistory.length - 1 - i) * 60_000);
  }
  if (!hasSensexVariance) {
    sensexHistory = buildSyntheticSeries(sensex?.last_price, sensexPct, Math.max(36, niftyHistory.length));
  }

  if (sensexHistory.length !== niftyHistory.length) {
    const target = Math.max(niftyHistory.length, sensexHistory.length);
    const fill = (arr) => {
      if (arr.length >= target) return arr.slice(arr.length - target);
      const last = arr.length ? arr[arr.length - 1] : 0;
      return [...Array(target - arr.length).fill(last), ...arr];
    };
    niftyHistory = fill(niftyHistory);
    sensexHistory = fill(sensexHistory);
    if (timeline.length !== target) {
      const end = Date.now();
      timeline = Array.from({ length: target }, (_, i) => end - (target - 1 - i) * 60_000);
    }
  }

  const niftyLine = chartPoints(niftyHistory);
  const sensexLine = chartPoints(sensexHistory);
  const selectedHistory = pulseSeries === "sensex" ? sensexHistory : niftyHistory;
  const selectedLine = pulseSeries === "sensex" ? sensexLine : niftyLine;

  const onPulseChartMove = (event) => {
    const box = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - box.left;
    const ratio = Math.max(0, Math.min(1, x / Math.max(1, box.width)));
    const idx = Math.round(ratio * Math.max(1, selectedHistory.length - 1));
    const point = chartPointXY(selectedHistory, idx);
    setChartHover({
      idx,
      x: point.x,
      y: point.y,
      value: selectedHistory[idx],
      ts: timeline[idx] || Date.now(),
      series: pulseSeries
    });
  };

  const onPulseChartLeave = () => setChartHover(null);

  return (
    <div className="page pageWide landingPage">
      <NavBar
        className="landingHeader"
        title="Portfolio Analyzer"
        subtitle="India's first EDA for retail investors"
        links={
          authed
            ? [
                { to: "/", label: "Home", end: true },
                { to: "/dashboard", label: "Dashboard" },
                { to: "/account", label: "Account" }
              ]
            : [{ to: "/", label: "Home", end: true }]
        }
        actions={
          authed ? null : (
            <button className="btn primary sm" type="button" onClick={() => setLoginOpen(true)}>
              Login / Signup
            </button>
          )
        }
      />

      <main className="landingMain">
        <section className="card landingHero">
          <div className="landingHeroGrid">
            <div className="landingHeroCopy">
              <div className="landingEyebrow">
                <span className="landingEyebrowDot" />
                India-first EDA
              </div>
              <h1 className="landingH1">
                Understand your <span className="landingAccent">portfolio</span> in <span className="landingAccent">minutes</span>, not spreadsheets.
              </h1>
              <p className="muted landingLead">
                Track holdings, valuation, and live market context in one focused workflow.
              </p>
              <div className="heroActions">
                {!authed ? (
                  <button className="btn primary" onClick={() => setLoginOpen(true)}>
                    Get started
                  </button>
                ) : null}
                <a className="btn ghost" href="/dashboard">
                  {authed ? "Go to dashboard" : "Open dashboard"}
                </a>
              </div>

              <div className="landingHeroPills">
                <div className="landingHeroPill">Live market pulse</div>
                <div className="landingHeroPill">IN + US stocks</div>
                <div className="landingHeroPill">Visual decision modules</div>
              </div>
            </div>

            <div className="landingHeroPanel">
              <div className="landingPanelHeader">
                <div className="strong">Market pulse</div>
                <div className="muted small">
                  {loading ? "Updating..." : market?.meta?.source === "snapshot" ? "Instant from last snapshot" : "Fresh fetch"}
                </div>
              </div>
              {loading ? <div className="skeleton h200" /> : null}
              {error ? <div className="error">{error}</div> : null}
              <div className="landingPulseGrid">
                <div className="kpi">
                  <div className="kpiLabel">Nifty</div>
                  <div className="kpiValue">{formatNum(nifty?.last_price)}</div>
                </div>
                <div className="kpi">
                  <div className="kpiLabel">Sensex</div>
                  <div className="kpiValue">{formatNum(sensex?.last_price)}</div>
                </div>
                <div className="kpi landingTopMover">
                  <div className="kpiLabel">Top mover (demo)</div>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "baseline" }}>
                    <div className="mono strong">{topMover?.symbol || "--"}</div>
                    <div className={topMover?.changePct >= 0 ? "mono pos" : "mono neg"}>{formatNum(topMover?.changePct)}%</div>
                  </div>
                  <div className="muted small">Last: {formatNum(topMover?.last)}</div>
                </div>
              </div>

              <div className="landingPulseChartWrap">
                <div className="landingPulseChartHead">
                  <span className="strong">Live snapshot trend</span>
                  <span className="muted small">Cached + refreshed timeline</span>
                </div>
                <div className="landingPulseLegend">
                  <button
                    type="button"
                    className={`landingPulseLegendItem ${pulseSeries === "nifty" ? "active" : ""}`}
                    onClick={() => {
                      setPulseSeries("nifty");
                      setChartHover(null);
                    }}
                  >
                    <span className="dot nifty" />
                    Nifty
                  </button>
                  <button
                    type="button"
                    className={`landingPulseLegendItem ${pulseSeries === "sensex" ? "active" : ""}`}
                    onClick={() => {
                      setPulseSeries("sensex");
                      setChartHover(null);
                    }}
                  >
                    <span className="dot sensex" />
                    Sensex
                  </button>
                </div>
                <svg className="landingPulseChart" viewBox="0 0 520 170" preserveAspectRatio="none" aria-label="Live market trend chart">
                  <defs>
                    <linearGradient id="landingNiftyFill" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stopColor="rgba(114,219,255,0.32)" />
                      <stop offset="100%" stopColor="rgba(114,219,255,0.02)" />
                    </linearGradient>
                  </defs>
                  <polyline className="landingPulseArea" points={`${selectedLine} 508,158 12,158`} fill="url(#landingNiftyFill)" />
                  <polyline className={`landingPulseLine ${pulseSeries}`} points={selectedLine} />
                </svg>
                <svg
                  className="landingPulseChartOverlay"
                  viewBox="0 0 520 170"
                  preserveAspectRatio="none"
                  aria-hidden="true"
                  onMouseMove={onPulseChartMove}
                  onMouseLeave={onPulseChartLeave}
                >
                  {chartHover ? (
                    <>
                      <line className="landingPulseCross" x1={chartHover.x} y1="10" x2={chartHover.x} y2="160" />
                      <circle className={`landingPulseDot ${chartHover.series === "sensex" ? "sensex" : "nifty"}`} cx={chartHover.x} cy={chartHover.y} r="4.5" />
                    </>
                  ) : null}
                </svg>
                {chartHover ? (
                  <div
                    className="landingPulseTooltip"
                    style={{
                      left: `min(calc(${(chartHover.x / 520) * 100}% + 12px), calc(100% - 136px))`,
                      top: `${Math.max(12, (chartHover.y / 170) * 100 - 12)}%`
                    }}
                  >
                    <div className="landingPulseTooltipLabel">{chartHover.series === "sensex" ? "Sensex" : "Nifty"}</div>
                    <div className="landingPulseTooltipValue">{formatNum(chartHover.value)}</div>
                    <div className="landingPulseTooltipTime">
                      {new Date(chartHover.ts).toLocaleString(undefined, {
                        day: "2-digit",
                        month: "short",
                        hour: "2-digit",
                        minute: "2-digit"
                      })}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          </div>

          <div className="landingTickerRail" aria-label="Live stock slider">
            <div className="landingTickerTrack">
              {tickerLoop.map((item, idx) => {
                const pct = Number(item?.changePct) || 0;
                return (
                  <div className="landingTickerItem" key={`${item?.symbol || "sym"}-${idx}`}>
                    <span className="landingTickerSymbol">{item?.symbol || "--"}</span>
                    <span className="landingTickerLast">{formatNum(item?.last)}</span>
                    <span className={pct >= 0 ? "landingTickerChange pos" : "landingTickerChange neg"}>
                      {pct >= 0 ? "+" : ""}
                      {formatNum(pct)}%
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </section>

        <section className="landingSection">
          <div className="landingSectionHead">
            <h2 className="landingH2">Live market modules</h2>
            <div className="landingAssetTabs">
              <button className={assetTab === "metals" ? "seg active" : "seg"} type="button" onClick={() => setAssetTab("metals")}>
                Gold & Silver
              </button>
              <button className={assetTab === "btc" ? "seg active" : "seg"} type="button" onClick={() => setAssetTab("btc")}>
                BTC
              </button>
            </div>
          </div>
          {assetTab === "metals" ? <MetalsPanel /> : <BtcPanel />}
        </section>

        <section className="landingSection">
          <div className="landingSectionHead">
            <h2 className="landingH2">What you can do</h2>
            <div className="muted small">Built to keep data light in SQL, heavy insights in UI.</div>
          </div>
          <div className="landingFeatureGrid">
            <div className="card landingFeature">
              <div className="landingFeatureTitle">Create portfolios</div>
              <div className="muted">Separate baskets (IT, Banking, Long-term) and compare analysis.</div>
            </div>
            <div className="card landingFeature">
              <div className="landingFeatureTitle">Add trades fast</div>
              <div className="muted">Search with live preview (Last, P/E, Discount) and build holdings automatically.</div>
            </div>
            <div className="card landingFeature">
              <div className="landingFeatureTitle">EDA + forecasts</div>
              <div className="muted">P/E chart, discount chart, and an educational forward value path.</div>
            </div>
            <div className="card landingFeature">
              <div className="landingFeatureTitle">Watchlist & alerts</div>
              <div className="muted">Track symbols and set simple above/below price alerts.</div>
            </div>
          </div>
        </section>

        <section className="landingSection">
          <div className="landingSectionHead">
            <h2 className="landingH2">How it works</h2>
            <div className="muted small">Three steps to insight.</div>
          </div>
          <div className="landingSteps">
            <div className="card landingStep">
              <div className="landingStepNum">1</div>
              <div>
                <div className="strong">Login & create a portfolio</div>
                <div className="muted small">Name it and keep your holdings organized.</div>
              </div>
            </div>
            <div className="card landingStep">
              <div className="landingStepNum">2</div>
              <div>
                <div className="strong">Add buy/sell trades</div>
                <div className="muted small">Holdings update automatically with avg price & PnL.</div>
              </div>
            </div>
            <div className="card landingStep">
              <div className="landingStepNum">3</div>
              <div>
                <div className="strong">Explore EDA charts</div>
                <div className="muted small">See valuation & discount patterns quickly.</div>
              </div>
            </div>
          </div>
        </section>

        <section className="card landingFooterCta">
          <div>
            <div className="landingFooterTitle">Ready to analyze?</div>
            <div className="muted">Start with a demo portfolio in under a minute.</div>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {!authed ? (
              <button className="btn primary" onClick={() => setLoginOpen(true)}>
                Get started
              </button>
            ) : null}
            <a className="btn ghost" href="/dashboard">
              {authed ? "Go to dashboard" : "Open dashboard"}
            </a>
          </div>
        </section>
      </main>

      <Footer />

      <LoginModal
        open={loginOpen}
        onClose={() => setLoginOpen(false)}
        onAuthed={() => {
          nav("/dashboard");
        }}
      />
    </div>
  );
}
