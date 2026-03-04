import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, clearTokens } from "../api.js";
import LineChart from "../components/LineChart.jsx";
import NavBar from "../components/NavBar.jsx";

function fmt(n) {
  if (n === null || n === undefined) return "--";
  const num = Number(n);
  if (Number.isNaN(num)) return "--";
  return num.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export default function Analysis() {
  const { id } = useParams();
  const portfolioId = Number(id);
  const nav = useNavigate();

  const [data, setData] = useState(null);
  const [forecast, setForecast] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [forecastBusy, setForecastBusy] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setForecastBusy(true);
    api
      .portfolioPE(portfolioId)
      .then((d) => {
        if (!alive) return;
        setData(d);
        setError("");
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
      })
      .catch(() => {})
      .finally(() => {
        if (!alive) return;
        setForecastBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [portfolioId, nav]);

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
          <h1>P/E overview</h1>
          <p className="muted">
            First Analysis module: current P/E per holding (best-effort). Next we can add returns, volatility, drawdowns, allocation, and prediction charts.
          </p>
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
          <div className="muted small">Data uses yfinance. Some stocks may not have P/E.</div>
        </section>

        <section className="card" style={{ gridColumn: "1 / -1" }}>
          <h3>P/E by holding</h3>
          {loading ? <div className="skeleton h200" /> : null}
          {holdings.length === 0 && !loading ? <div className="muted">No holdings yet.</div> : null}

          <div className="barList">
            {holdings.map((h) => {
              const pe = h.pe === null || h.pe === undefined ? null : Number(h.pe);
              const pct = pe !== null && maxPE ? Math.max(2, Math.min(100, (pe / maxPE) * 100)) : 2;
              return (
                <div className="barRow" key={h.symbol}>
                  <div className="barLeft">
                    <div className="strong mono">{h.symbol}</div>
                    <div className="muted small">{h.name}</div>
                  </div>
                  <div className="barMid">
                    <div className="barTrack">
                      <div className="barFill" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                  <div className="barRight mono">{pe === null || Number.isNaN(pe) ? "--" : fmt(pe)}</div>
                </div>
              );
            })}
          </div>
        </section>

        <section className="card" style={{ gridColumn: "1 / -1" }}>
          <h3>Discount from 52W High</h3>
          <div className="muted small">Discount % = (52W High − Last) / 52W High × 100.</div>
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
    </div>
  );
}
