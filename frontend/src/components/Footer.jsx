import React from "react";
import { Link } from "react-router-dom";
import { getToken } from "../api.js";

function ExternalLink({ href, children }) {
  return (
    <a className="footerLink" href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  );
}

export default function Footer() {
  const authed = Boolean(getToken());
  const repoUrl = import.meta?.env?.VITE_REPO_URL || "";

  return (
    <footer className="siteFooter" aria-label="Site footer">
      <div className="footerTop">
        <div className="footerBrand">
          <div className="footerLogo" aria-hidden="true">
            EDA
          </div>
          <div>
            <div className="footerTitle">Portfolio Analyzer</div>
            <div className="footerSub">Indian equities • Holdings • EDA • Forecast</div>
            <div className="footerMeta">
              <span className="footerBadge">Demo project</span>
              <span className="footerBadge soft">Best-effort data</span>
            </div>
          </div>
        </div>

        <div className="footerGrid">
          <div className="footerCol">
            <div className="footerHead">Product</div>
            <Link className="footerLink" to="/">
              Home
            </Link>
            {authed ? (
              <Link className="footerLink" to="/dashboard">
                Dashboard
              </Link>
            ) : null}
            {authed ? (
              <Link className="footerLink" to="/account">
                Account
              </Link>
            ) : null}
          </div>

          <div className="footerCol">
            <div className="footerHead">Insights</div>
            <div className="footerText">P/E, 52W range, discount, clustering and educational charts.</div>
            <div className="footerHint">Tip: Use 2–5 clusters for readability.</div>
          </div>

          <div className="footerCol">
            <div className="footerHead">Tech</div>
            <div className="footerText">React + Vite • Django + DRF • Postgres (Supabase).</div>
            <div className="footerText">Vercel (UI) + Render (API).</div>
            {repoUrl ? <ExternalLink href={repoUrl}>View source</ExternalLink> : null}
          </div>

          <div className="footerCol">
            <div className="footerHead">Disclaimer</div>
            <div className="footerText">
              Educational only. Not investment advice. Quotes and fundamentals are best-effort and may be delayed or unavailable.
            </div>
            <div className="footerHint">Data: Yahoo Finance via yfinance (where available).</div>
          </div>
        </div>
      </div>

      <div className="footerBottom">
        <div className="muted small">© {new Date().getFullYear()} Portfolio Analyzer</div>
        <div className="footerBottomRight muted small">Built for demos • Fast, lightweight insights</div>
      </div>
    </footer>
  );
}

