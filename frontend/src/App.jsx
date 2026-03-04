import React, { useEffect, useRef, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Landing from "./pages/Landing.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Portfolio from "./pages/Portfolio.jsx";
import Analysis from "./pages/Analysis.jsx";
import Chart from "./pages/Chart.jsx";
import Account from "./pages/Account.jsx";
import { getToken } from "./api.js";

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
          ×
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
  const [introState, setIntroState] = useState("enter"); // enter | exiting | hidden

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
    </>
  );
}
