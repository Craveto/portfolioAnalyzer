import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, getToken } from "../api.js";
import LoginModal from "../components/LoginModal.jsx";
import NavBar from "../components/NavBar.jsx";
import Footer from "../components/Footer.jsx";
import MetalsPanel from "../components/MetalsPanel.jsx";

const MARKET_CACHE_KEY = "landing_market_summary_cache_v1";

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

export default function Landing() {
  const nav = useNavigate();
  const [market, setMarket] = useState(() => loadMarketCache()?.data || null);
  const [loading, setLoading] = useState(() => !loadMarketCache()?.data);
  const [error, setError] = useState("");
  const [loginOpen, setLoginOpen] = useState(false);

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
              <div className="badge soft">India-first EDA</div>
              <h1 className="landingH1">Understand your portfolio in minutes, not spreadsheets.</h1>
              <p className="muted landingLead">
                Track holdings, analyze P/E & discounts, and explore charts & forecasts. Designed for Indian equities with live-ish quotes via yfinance.
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

              <div className="landingHighlights">
                <div className="landingMini">
                  <div className="landingMiniTitle">Portfolio tracking</div>
                  <div className="muted small">Holdings, realized & unrealized PnL.</div>
                </div>
                <div className="landingMini">
                  <div className="landingMiniTitle">Valuation context</div>
                  <div className="muted small">P/E, 52W range, discount.</div>
                </div>
                <div className="landingMini">
                  <div className="landingMiniTitle">EDA charts</div>
                  <div className="muted small">P/E bars, discount bars, forecast.</div>
                </div>
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

              <div className="muted small" style={{ marginTop: 10 }}>
                {market?.note || "Demo movers computed from a fixed universe."}
              </div>
            </div>
          </div>
        </section>

        <section className="landingSection">
          <MetalsPanel />
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
