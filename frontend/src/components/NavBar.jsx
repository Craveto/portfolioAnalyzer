import React, { useEffect, useMemo, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";

function cx(...parts) {
  return parts.filter(Boolean).join(" ");
}

function isFn(v) {
  return typeof v === "function";
}

function navIcon(to) {
  const p = String(to || "");
  const common = { width: 18, height: 18, viewBox: "0 0 24 24", fill: "none", "aria-hidden": true };
  if (p === "/" || p === "") {
    return (
      <svg {...common}>
        <path
          d="M4 11.5 12 5l8 6.5V20a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1v-8.5Z"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  if (p.includes("dashboard")) {
    return (
      <svg {...common}>
        <path
          d="M4 4h7v9H4V4Zm9 0h7v5h-7V4ZM4 15h7v5H4v-5Zm9-4h7v9h-7v-9Z"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  if (p.includes("portfolio")) {
    return (
      <svg {...common}>
        <path
          d="M7 7h10M7 12h10M7 17h7M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  if (p.includes("analysis")) {
    return (
      <svg {...common}>
        <path
          d="M5 19V5m0 14h14M8 16l3-5 3 3 4-7"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  if (p.includes("chart")) {
    return (
      <svg {...common}>
        <path
          d="M6 20V10m6 10V4m6 16v-7"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  if (p.includes("account")) {
    return (
      <svg {...common}>
        <path
          d="M12 12a4 4 0 1 0-4-4 4 4 0 0 0 4 4Zm7 9a7 7 0 0 0-14 0"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <path d="M6 12h12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

const THEME_KEY = "eda_theme";
const THEMES = [
  { id: "violet", label: "Violet" },
  { id: "emerald", label: "Emerald" },
  { id: "sunset", label: "Sunset" }
];

export default function NavBar({
  title,
  subtitle,
  homeTo = "/",
  links = [],
  actions = null,
  className = "",
  showThemeToggle = true,
  mobileTabs = true,
  mobileTabsMax = 4
}) {
  const loc = useLocation();
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useState(() => {
    try {
      const saved = localStorage.getItem(THEME_KEY);
      return saved || "violet";
    } catch {
      return "violet";
    }
  });

  const computedLinks = useMemo(() => {
    return (links || []).map((l) => {
      const match = l.match;
      const active = isFn(match) ? Boolean(match(loc)) : false;
      return { ...l, _active: active };
    });
  }, [links, loc]);

  const anyComputedActive = computedLinks.some((l) => l._active);
  const tabCount = Math.max(2, Math.min(5, Number(mobileTabsMax) || 4));
  const tabs = mobileTabs ? computedLinks.slice(0, tabCount) : [];
  const pinnedSet = useMemo(() => new Set((tabs || []).map((t) => t.to)), [tabs]);

  useEffect(() => {
    setOpen(false);
  }, [loc.pathname]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      // ignore
    }
  }, [theme]);

  const nextTheme = () => {
    const idx = Math.max(
      0,
      THEMES.findIndex((t) => t.id === theme)
    );
    const next = THEMES[(idx + 1) % THEMES.length]?.id || "violet";
    setTheme(next);
  };

  const themeLabel = THEMES.find((t) => t.id === theme)?.label || "Theme";
  const themeBtn = showThemeToggle ? (
    <button className="themeBtn" type="button" onClick={nextTheme} aria-label={`Theme: ${themeLabel}`} title={`Theme: ${themeLabel}`}>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M12 3.5c-4.7 0-8.5 3.8-8.5 8.5S7.3 20.5 12 20.5c3.6 0 6.7-2.2 7.9-5.4.2-.6-.3-1.1-.9-1.1h-2.2c-1.4 0-2.5-1.1-2.5-2.5V9.3c0-1.4-1.1-2.5-2.5-2.5H8.6c-.6 0-1.1-.6-.9-1.1C8.9 4.7 10.4 3.5 12 3.5Z"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
        <circle cx="16.7" cy="7.6" r="1" fill="currentColor" opacity="0.9" />
        <circle cx="18.2" cy="11.2" r="1" fill="currentColor" opacity="0.7" />
        <circle cx="15.2" cy="14.8" r="1" fill="currentColor" opacity="0.6" />
      </svg>
    </button>
  ) : null;

  return (
    <>
      <header className={cx("header appHeader", className)}>
        <div className="brand">
          <Link className="brandLink" to={homeTo} aria-label="Home">
            <div className="logo">EDA</div>
          </Link>
          <div>
            <div className="brandTitle">{title}</div>
            {subtitle ? <div className="brandSub">{subtitle}</div> : null}
          </div>
        </div>

        <div className="navRight">
          {computedLinks.length ? (
            <nav className="navLinks" aria-label="Primary">
              {computedLinks.map((l) => (
                <NavLink
                  key={l.to || l.label}
                  to={l.to}
                  end={Boolean(l.end)}
                  className={({ isActive }) => {
                    const active = anyComputedActive ? l._active : isActive;
                    return active ? "navItem active" : "navItem";
                  }}
                  title={l.title || l.label}
                >
                  {l.label}
                </NavLink>
              ))}
            </nav>
          ) : null}

          {actions || themeBtn ? <div className="navActions">{themeBtn}{actions}</div> : null}

          {computedLinks.length ? (
            <button
              className={open ? "navBurger open" : "navBurger"}
              type="button"
              aria-label="Menu"
              aria-expanded={open}
              onClick={() => setOpen((v) => !v)}
              title="More"
            >
              <span />
              <span />
              <span />
            </button>
          ) : null}
        </div>

        {open ? (
          <div className="navMobileBackdrop" role="presentation" onClick={() => setOpen(false)}>
            <div className="navMobile" role="menu" onClick={(e) => e.stopPropagation()}>
              <div className="navMobileHead">
                <div className="navMobileTitle">
                  <div className="strong">More</div>
                  <div className="muted small">Shortcuts & actions</div>
                </div>
                <button className="navMobileClose" type="button" onClick={() => setOpen(false)} aria-label="Close menu">
                  ×
                </button>
              </div>
              <div className="navMobileGrab" aria-hidden="true" />
              <div className="navMobileList">
                {computedLinks.map((l) => (
                  <NavLink
                    key={l.to || l.label}
                    to={l.to}
                    end={Boolean(l.end)}
                    className={({ isActive }) => {
                      const active = anyComputedActive ? l._active : isActive;
                      return active ? "navMobileItem active" : "navMobileItem";
                    }}
                    role="menuitem"
                  >
                    <span className="navMobileItemIcon">{navIcon(l.to)}</span>
                    <span className="navMobileItemText">
                      {l.label}
                      {mobileTabs && pinnedSet.has(l.to) ? <span className="navMobileBadge">Pinned</span> : null}
                    </span>
                  </NavLink>
                ))}
              </div>
              {actions || themeBtn ? (
                <div className="navMobileActions">
                  {themeBtn}
                  {actions}
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
      </header>

      {mobileTabs && tabs.length ? (
        <nav className="mobileTabsBar" aria-label="Mobile navigation">
          {tabs.map((l) => (
            <NavLink
              key={l.to || l.label}
              to={l.to}
              end={Boolean(l.end)}
              className={({ isActive }) => {
                const active = anyComputedActive ? l._active : isActive;
                return active ? "mobileTab active" : "mobileTab";
              }}
              title={l.title || l.label}
            >
              <span className="mobileTabIcon">{navIcon(l.to)}</span>
              <span className="mobileTabLabel">{l.label}</span>
            </NavLink>
          ))}
          <button className={open ? "mobileTab more active" : "mobileTab more"} type="button" onClick={() => setOpen((v) => !v)} aria-label="More">
            <span className="mobileTabIcon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M6 12h.01M12 12h.01M18 12h.01" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
              </svg>
            </span>
            <span className="mobileTabLabel">More</span>
          </button>
        </nav>
      ) : null}
    </>
  );
}
