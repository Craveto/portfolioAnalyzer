import React, { useEffect, useRef, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Landing from "./pages/Landing.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Portfolio from "./pages/Portfolio.jsx";
import Analysis from "./pages/Analysis.jsx";
import Chart from "./pages/Chart.jsx";
import Account from "./pages/Account.jsx";
import { api, getToken } from "./api.js";
import EdachiAssistant from "./components/EdachiAssistant.jsx";

const DASHBOARD_CACHE_KEY = "dashboard_summary_cache_v1";
const ACCOUNT_CACHE_KEY = "account_page_cache_v1";

function saveJson(key, data) {
  try {
    localStorage.setItem(key, JSON.stringify({ savedAt: Date.now(), data }));
  } catch {}
}

function savePortfolioBundle(portfolioId, bundle) {
  try {
    localStorage.setItem(`portfolioPage:${portfolioId}`, JSON.stringify({ ...bundle, cachedAt: Date.now() }));
  } catch {}
}

function saveAnalysisBundle(portfolioId, bundle) {
  try {
    localStorage.setItem(`analysisPage:${portfolioId}`, JSON.stringify({ savedAt: Date.now(), ...bundle }));
  } catch {}
}

function saveChartBundle(portfolioId, data) {
  try {
    localStorage.setItem(`chartPage:${portfolioId}`, JSON.stringify({ savedAt: Date.now(), data }));
  } catch {}
}

function PrivateRoute({ children }) {
  return getToken() ? children : <Navigate to="/" replace />;
}

function IntroSplash({ state, onDone }) {
  const out = state === "exiting";
  return (
    <div className={out ? "splashBackdrop splashOut" : "splashBackdrop"} role="presentation" onClick={onDone}>
      <div
        className={out ? "splashCard splashOut" : "splashCard"}
        role="dialog"
        aria-modal="true"
        aria-label="Loading"
        onClick={(e) => e.stopPropagation()}
      >
        <button className="splashClose" type="button" onClick={onDone} aria-label="Close">
          x
        </button>
        <div className="splashCenter">
          <div className="splashMark" aria-hidden="true">
            EDA
          </div>
          <div className="splashText">
            <div className="splashTitle">Portfolio Analyzer</div>
            <div className="splashSub">Markets • Holdings • EDA • Forecast</div>
          </div>
        </div>
        <div className="splashDots" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <div className="splashTimer" aria-hidden="true">
          <div className="splashTimerFill" />
        </div>
        <div className="muted small" style={{ marginTop: 10 }}>
          Tap anywhere to close
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const didInit = useRef(false);
  const [introState, setIntroState] = useState("enter");

  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;

    const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) setIntroState("hidden");
    return () => {};
  }, []);

  useEffect(() => {
    if (introState === "hidden") return;
    const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) return;

    const close = () => {
      setIntroState((s) => (s === "hidden" || s === "exiting" ? s : "exiting"));
    };

    const t = setTimeout(close, 2000);
    return () => clearTimeout(t);
  }, [introState]);

  useEffect(() => {
    if (introState !== "exiting") return;
    const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const ms = reduceMotion ? 0 : 260;
    const t = setTimeout(() => setIntroState("hidden"), ms);
    return () => clearTimeout(t);
  }, [introState]);

  const closeIntro = () => setIntroState((s) => (s === "hidden" || s === "exiting" ? s : "exiting"));

  useEffect(() => {
    if (!getToken()) return;
    let alive = true;

    async function warmApp() {
      try {
        const [summary, account, watchlist, alerts] = await Promise.all([
          api.dashboardSummary(false).catch(() => null),
          api.account().catch(() => null),
          api.listWatchlist().catch(() => []),
          api.listAlerts().catch(() => []),
        ]);

        api.edachiBootstrap().then((d) => {
          try {
            localStorage.setItem("edachi_bootstrap_cache_v1_user", JSON.stringify({ savedAt: Date.now(), data: d || {} }));
          } catch {}
        }).catch(() => {});

        if (!alive) return;

        if (summary) saveJson(DASHBOARD_CACHE_KEY, summary);

        let portfolios = summary?.portfolios || [];
        if (!portfolios.length) {
          portfolios = await api.listPortfolios().catch(() => []);
        }

        if (account) {
          saveJson(ACCOUNT_CACHE_KEY, {
            user: account.user,
            profile: account.profile,
            portfolios,
            watchlist,
            alerts,
          });
        }

        const preferredPortfolioId =
          summary?.profile?.default_portfolio?.id || portfolios?.[0]?.id || null;

        if (!preferredPortfolioId) return;

        const [portfolioData, peData, forecastData, txs] = await Promise.all([
          api.getPortfolio(preferredPortfolioId).catch(() => null),
          api.portfolioPE(preferredPortfolioId).catch(() => null),
          api.portfolioForecast(preferredPortfolioId, 90).catch(() => null),
          api.listTransactions(preferredPortfolioId).catch(() => []),
        ]);

        if (!alive) return;

        const metricsBySymbol = {};
        for (const item of peData?.holdings || []) {
          if (item?.symbol) metricsBySymbol[String(item.symbol)] = item;
        }

        if (portfolioData) {
          savePortfolioBundle(preferredPortfolioId, {
            portfolio: portfolioData,
            holdings: portfolioData.holdings || [],
            transactions: txs || [],
            holdingMetricsBySymbol: metricsBySymbol,
          });
        }
        if (peData) {
          saveAnalysisBundle(preferredPortfolioId, { data: peData, forecast: forecastData });
          saveChartBundle(preferredPortfolioId, peData);
        }
      } catch {
        // warmup is best-effort only
      }
    }

    warmApp();
    return () => {
      alive = false;
    };
  }, []);

  return (
    <>
      {introState !== "hidden" ? <IntroSplash state={introState} onDone={closeIntro} /> : null}
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route
          path="/dashboard"
          element={
            <PrivateRoute>
              <Dashboard />
            </PrivateRoute>
          }
        />
        <Route
          path="/portfolio/:id"
          element={
            <PrivateRoute>
              <Portfolio />
            </PrivateRoute>
          }
        />
        <Route
          path="/analysis/:id"
          element={
            <PrivateRoute>
              <Analysis />
            </PrivateRoute>
          }
        />
        <Route
          path="/account"
          element={
            <PrivateRoute>
              <Account />
            </PrivateRoute>
          }
        />
        <Route
          path="/chart/:id"
          element={
            <PrivateRoute>
              <Chart />
            </PrivateRoute>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <EdachiAssistant />
    </>
  );
}
