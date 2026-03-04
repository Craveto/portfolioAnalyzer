import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, clearTokens } from "../api.js";
import NavBar from "../components/NavBar.jsx";

function fmt(n) {
  if (n === null || n === undefined) return "--";
  const num = Number(n);
  if (Number.isNaN(num)) return "--";
  return num.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export default function Chart() {
  const { id } = useParams();
  const portfolioId = Number(id);
  const nav = useNavigate();

  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api
      .portfolioPE(portfolioId)
      .then((d) => {
        if (!alive) return;
        setData(d);
        setError("");
      })
      .catch((e) => {
        if (!alive) return;
        setError(e.message || "Failed to load chart data");
        if ((e.message || "").includes("HTTP 401") || (e.message || "").includes("HTTP 403")) {
          clearTokens();
          nav("/");
        }
      })
      .finally(() => {
        if (!alive) return;
        setLoading(false);
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

  function logout() {
    clearTokens();
    nav("/");
  }

  return (
    <div className="page">
      <NavBar
        title="Charts"
        subtitle={
          <>
            <span className="muted">Portfolio: </span>
            <span className="strong">{data?.portfolio?.name || "..."}</span>
          </>
        }
        links={[
          { to: "/dashboard", label: "Dashboard" },
          { to: `/portfolio/${portfolioId}`, label: "Holdings", match: (l) => l.pathname.startsWith("/portfolio/") },
          { to: `/analysis/${portfolioId}`, label: "Analysis", match: (l) => l.pathname.startsWith("/analysis/") },
          { to: `/chart/${portfolioId}`, label: "Charts", end: true, match: (l) => l.pathname.startsWith("/chart/") }
        ]}
        actions={
          <button className="btn danger sm" type="button" onClick={logout}>
            Logout
          </button>
        }
      />

      <main className="grid">
        <section className="card hero">
          <h1>P/E Ratio</h1>
          <p className="muted">Vertical bar chart of P/E for all holdings in your portfolio.</p>
        </section>

        <section className="card" style={{ gridColumn: "1 / -1" }}>
          <h3>P/E (vertical bar chart)</h3>
          {loading ? <div className="skeleton h200" /> : null}
          {error ? <div className="error">{error}</div> : null}
          {!loading && points.length === 0 ? <div className="muted">No P/E data available for holdings yet.</div> : null}

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
            P/E is fetched from yfinance fundamentals (best-effort). Some symbols may return no P/E.
          </div>
        </section>
      </main>
    </div>
  );
}
