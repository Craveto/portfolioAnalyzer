import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, clearTokens } from "../api.js";
import NavBar from "../components/NavBar.jsx";
import Footer from "../components/Footer.jsx";

const ACCOUNT_CACHE_KEY = "account_page_cache_v1";

function loadAccountCache() {
  try {
    const raw = localStorage.getItem(ACCOUNT_CACHE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveAccountCache(data) {
  try {
    localStorage.setItem(ACCOUNT_CACHE_KEY, JSON.stringify({ savedAt: Date.now(), data }));
  } catch {}
}

export default function Account() {
  const nav = useNavigate();
  const cached = loadAccountCache()?.data || null;
  const [me, setMe] = useState(cached?.user || null);
  const [profile, setProfile] = useState(cached?.profile || null);
  const [portfolios, setPortfolios] = useState(cached?.portfolios || []);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [edit, setEdit] = useState(false);
  const [saving, setSaving] = useState(false);
  const [pwdBusy, setPwdBusy] = useState(false);

  const [form, setForm] = useState({
    username: "",
    email: "",
    full_name: "",
    bio: "",
    default_redirect: "dashboard",
    default_portfolio_id: null
  });

  const [pwd, setPwd] = useState({ old_password: "", new_password: "" });

  const [watchQ, setWatchQ] = useState("");
  const [watchResults, setWatchResults] = useState([]);
  const [watchSymbol, setWatchSymbol] = useState("");
  const [watchName, setWatchName] = useState("");
  const [watchlist, setWatchlist] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [alertForm, setAlertForm] = useState({ symbol: "", name: "", direction: "ABOVE", target: "" });
  const [watchBusy, setWatchBusy] = useState(false);

  useEffect(() => {
    api.account()
      .then((d) => {
        setMe(d.user);
        setProfile(d.profile);
        saveAccountCache({ user: d.user, profile: d.profile, portfolios, watchlist, alerts });
        setForm({
          username: d.user?.username || "",
          email: d.user?.email || "",
          full_name: d.profile?.full_name || "",
          bio: d.profile?.bio || "",
          default_redirect: d.profile?.default_redirect || "dashboard",
          default_portfolio_id: d.profile?.default_portfolio?.id ?? null
        });
      })
      .catch((e) => {
        const msg = e?.message || "Failed to load account";
        setError(msg);
        if (msg.includes("HTTP 401") || msg.includes("HTTP 403")) {
          clearTokens();
          nav("/");
        }
      });
  }, [nav]);

  useEffect(() => {
    api
      .listPortfolios()
      .then(setPortfolios)
      .then((list) => {
        saveAccountCache({ user: me, profile, portfolios: list, watchlist, alerts });
        return list;
      })
      .catch((e) => {
        const msg = e?.message || "Failed to load portfolios";
        setError(msg);
        if (msg.includes("HTTP 401") || msg.includes("HTTP 403")) {
          clearTokens();
          nav("/");
        }
      });
  }, []);

  useEffect(() => {
    api
      .listWatchlist()
      .then((items) => {
        setWatchlist(items);
        saveAccountCache({ user: me, profile, portfolios, watchlist: items, alerts });
      })
      .catch(() => {});
    api
      .listAlerts()
      .then((items) => {
        setAlerts(items);
        saveAccountCache({ user: me, profile, portfolios, watchlist, alerts: items });
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!watchQ.trim()) {
      setWatchResults([]);
      return;
    }
    const t = setTimeout(() => {
      api
        .searchStocksLive(watchQ.trim())
        .then((d) => setWatchResults(d))
        .catch(() => setWatchResults([]));
    }, 250);
    return () => clearTimeout(t);
  }, [watchQ]);

  function logout() {
    clearTokens();
    nav("/");
  }

  async function saveProfile() {
    setError("");
    setSuccess("");
    setSaving(true);
    try {
      const patch = {
        username: form.username,
        email: form.email,
        full_name: form.full_name,
        bio: form.bio,
        default_redirect: form.default_redirect,
        default_portfolio_id: form.default_portfolio_id === "" ? null : form.default_portfolio_id
      };
      const d = await api.updateAccount(patch);
      setMe(d.user);
      setProfile(d.profile);
      saveAccountCache({ user: d.user, profile: d.profile, portfolios, watchlist, alerts });
      setEdit(false);
      setSuccess("Profile updated.");
    } catch (e) {
      setError(e.message || "Failed to update profile");
    } finally {
      setSaving(false);
    }
  }

  async function changePassword() {
    setError("");
    setSuccess("");
    setPwdBusy(true);
    try {
      const res = await api.changePassword(pwd);
      setSuccess(res.detail || "Password changed. Please login again.");
      logout();
    } catch (e) {
      setError(e.message || "Failed to change password");
    } finally {
      setPwdBusy(false);
    }
  }

  function exportTransactionsCsv(portfolioId) {
    const p = portfolios.find((x) => x.id === portfolioId);
    api
      .listTransactions(portfolioId)
      .then((txs) => {
        const rows = (txs || []).map((t) => ({
          id: t.id,
          symbol: t.stock?.symbol,
          side: t.side,
          qty: t.qty,
          price: t.price,
          realized_pnl: t.realized_pnl,
          executed_at: t.executed_at
        }));
        const header = Object.keys(rows[0] || { id: "", symbol: "", side: "", qty: "", price: "", realized_pnl: "", executed_at: "" });
        const csv = [
          header.join(","),
          ...rows.map((r) => header.map((k) => `"${String(r[k] ?? "").replaceAll('"', '""')}"`).join(","))
        ].join("\n");
        const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `${(p?.name || "portfolio").replaceAll(" ", "_")}_transactions.csv`;
        a.click();
        URL.revokeObjectURL(a.href);
        setSuccess("Exported CSV.");
      })
      .catch((e) => setError(e.message || "Failed to export CSV"));
  }

  async function addToWatchlist() {
    if (!watchSymbol) {
      setError("Select a stock to add to watchlist.");
      return;
    }
    setError("");
    setSuccess("");
    setWatchBusy(true);
    try {
      const item = await api.addWatchlist({ stock_symbol: watchSymbol, stock_name: watchName });
      const next = [item, ...watchlist.filter((x) => x.id !== item.id)];
      setWatchlist(next);
      saveAccountCache({ user: me, profile, portfolios, watchlist: next, alerts });
      setSuccess("Added to watchlist.");
      setWatchQ("");
      setWatchSymbol("");
      setWatchName("");
    } catch (e) {
      setError(e.message || "Failed to add to watchlist");
    } finally {
      setWatchBusy(false);
    }
  }

  async function removeFromWatchlist(id) {
    setError("");
    setSuccess("");
    try {
      await api.deleteWatchlistItem(id);
      const next = watchlist.filter((x) => x.id !== id);
      setWatchlist(next);
      saveAccountCache({ user: me, profile, portfolios, watchlist: next, alerts });
    } catch (e) {
      setError(e.message || "Failed to remove");
    }
  }

  async function createAlert() {
    setError("");
    setSuccess("");
    if (!alertForm.symbol) return setError("Choose a stock for alert.");
    if (!alertForm.target) return setError("Enter target price.");
    try {
      const a = await api.createAlert({
        stock_symbol: alertForm.symbol,
        stock_name: alertForm.name,
        direction: alertForm.direction,
        target_price: alertForm.target
      });
      const next = [a, ...alerts];
      setAlerts(next);
      saveAccountCache({ user: me, profile, portfolios, watchlist, alerts: next });
      setSuccess("Alert created.");
      setAlertForm((f) => ({ ...f, target: "" }));
    } catch (e) {
      setError(e.message || "Failed to create alert");
    }
  }

  async function deleteAlert(id) {
    setError("");
    setSuccess("");
    try {
      await api.deleteAlert(id);
      const next = alerts.filter((x) => x.id !== id);
      setAlerts(next);
      saveAccountCache({ user: me, profile, portfolios, watchlist, alerts: next });
    } catch (e) {
      setError(e.message || "Failed to delete alert");
    }
  }

  return (
    <div className="page">
      <NavBar
        title="Account"
        subtitle="Profile • Preferences • Portfolio shortcuts"
        links={[
          { to: "/dashboard", label: "Dashboard" },
          { to: "/account", label: "Account", end: true },
          { to: "/", label: "Home" }
        ]}
        actions={
          <button className="btn danger sm" type="button" onClick={logout}>
            Logout
          </button>
        }
      />

      <main className="grid">
        <section className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12 }}>
            <h3 style={{ margin: 0 }}>Profile</h3>
            <button className="btn ghost" onClick={() => setEdit((v) => !v)}>
              {edit ? "Cancel" : "Edit"}
            </button>
          </div>
          {error ? <div className="error">{error}</div> : null}
          {success ? <div className="success">{success}</div> : null}
          <div className="kpiRow">
            <div className="kpi">
              <div className="kpiLabel">Username</div>
              {edit ? (
                <input className="input" value={form.username} onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))} />
              ) : (
                <div className="kpiValue">{me?.username || "..."}</div>
              )}
            </div>
            <div className="kpi">
              <div className="kpiLabel">Email</div>
              {edit ? (
                <input className="input" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
              ) : (
                <div className="kpiValue">{me?.email || "--"}</div>
              )}
            </div>
          </div>
          <div className="kpiRow" style={{ marginTop: 10 }}>
            <div className="kpi">
              <div className="kpiLabel">Full name</div>
              {edit ? (
                <input className="input" value={form.full_name} onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))} />
              ) : (
                <div className="kpiValue">{profile?.full_name || "--"}</div>
              )}
            </div>
            <div className="kpi">
              <div className="kpiLabel">Default redirect</div>
              {edit ? (
                <select className="input" value={form.default_redirect} onChange={(e) => setForm((f) => ({ ...f, default_redirect: e.target.value }))}>
                  <option value="dashboard">Dashboard</option>
                  <option value="account">Account</option>
                </select>
              ) : (
                <div className="kpiValue">{profile?.default_redirect || "dashboard"}</div>
              )}
            </div>
          </div>

          <div style={{ marginTop: 10 }}>
            <div className="kpiLabel">Bio</div>
            {edit ? (
              <textarea
                className="input"
                rows={3}
                value={form.bio}
                onChange={(e) => setForm((f) => ({ ...f, bio: e.target.value }))}
                placeholder="Short intro (optional)"
              />
            ) : (
              <div className="muted" style={{ marginTop: 6 }}>
                {profile?.bio || "—"}
              </div>
            )}
          </div>

          <div style={{ marginTop: 10 }}>
            <div className="kpiLabel">Default portfolio</div>
            {edit ? (
              <select
                className="input"
                value={form.default_portfolio_id ?? ""}
                onChange={(e) =>
                  setForm((f) => ({ ...f, default_portfolio_id: e.target.value ? Number(e.target.value) : null }))
                }
              >
                <option value="">(none)</option>
                {portfolios.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            ) : (
              <div className="muted" style={{ marginTop: 6 }}>
                {profile?.default_portfolio?.name || "(none)"}
              </div>
            )}
          </div>

          {edit ? (
            <div style={{ marginTop: 12, display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button className="btn primary" onClick={saveProfile} disabled={saving}>
                {saving ? "Saving..." : "Save changes"}
              </button>
              <button className="btn ghost" onClick={() => setEdit(false)} disabled={saving}>
                Cancel
              </button>
            </div>
          ) : null}
          <div className="muted small" style={{ marginTop: 10 }}>
            Ideas to add next (like real portfolio apps): watchlist sync, alerts, and CSV exports.
          </div>
        </section>

        <section className="card">
          <h3>Portfolio shortcuts</h3>
          <div className="muted small">Quick jump like Zerodha/Upstox style: pick your portfolio and open charts/analysis fast.</div>
          <div className="list" style={{ marginTop: 10 }}>
            {portfolios.slice(0, 5).map((p) => (
              <div key={p.id} className="listItemRow">
                <Link className="listItem" to={`/portfolio/${p.id}`}>
                  <div className="strong">{p.name}</div>
                  <div className="muted small">Open holdings & trades</div>
                </Link>
                <Link className="btn sm" to={`/analysis/${p.id}`}>
                  Analysis
                </Link>
              </div>
            ))}
            {portfolios.length === 0 ? <div className="muted">No portfolios yet.</div> : null}
          </div>
        </section>

        <section className="card" style={{ gridColumn: "1 / -1" }}>
          <h3>Watchlist (sync for analysis)</h3>
          <div className="muted small">
            Add any Indian stock (live search) to your watchlist. This is useful to “sync” the stocks you care about across the app.
          </div>

          <div className="twoCol" style={{ marginTop: 10 }}>
            <input className="input" value={watchQ} onChange={(e) => setWatchQ(e.target.value)} placeholder="Search stock (e.g., INFY)" />
            <select
              className="input"
              value={watchSymbol}
              onChange={(e) => {
                const sym = e.target.value;
                setWatchSymbol(sym);
                const item = watchResults.find((x) => x.symbol === sym);
                setWatchName(item?.name || "");
                setAlertForm((f) => ({ ...f, symbol: sym, name: item?.name || "" }));
              }}
            >
              <option value="">-- choose --</option>
              {watchResults.slice(0, 20).map((s) => (
                <option key={s.symbol} value={s.symbol}>
                  {s.symbol} — {s.name}
                </option>
              ))}
            </select>
          </div>
          <div style={{ marginTop: 10, display: "flex", gap: 10, flexWrap: "wrap" }}>
            <button className="btn primary" onClick={addToWatchlist} disabled={watchBusy}>
              {watchBusy ? "Adding..." : "Add to watchlist"}
            </button>
            <button
              className="btn ghost"
              onClick={() => {
                api.listWatchlist().then(setWatchlist).catch(() => {});
                api.listAlerts().then(setAlerts).catch(() => {});
              }}
            >
              Refresh prices
            </button>
          </div>

          <div className="table" style={{ marginTop: 12 }}>
            <div className="row head" style={{ gridTemplateColumns: "1.2fr 1.8fr 0.8fr 0.8fr" }}>
              <div>Symbol</div>
              <div>Name</div>
              <div className="right">Last</div>
              <div className="right">Action</div>
            </div>
            {watchlist.map((w) => (
              <div className="row" key={w.id} style={{ gridTemplateColumns: "1.2fr 1.8fr 0.8fr 0.8fr" }}>
                <div className="mono">{w.stock?.symbol}</div>
                <div>{w.stock?.name}</div>
                <div className="right">{w.last_price ?? "--"}</div>
                <div className="right">
                  <button className="btn danger sm" onClick={() => removeFromWatchlist(w.id)}>
                    Remove
                  </button>
                </div>
              </div>
            ))}
            {watchlist.length === 0 ? <div className="muted" style={{ marginTop: 10 }}>No watchlist items yet.</div> : null}
          </div>

          <div style={{ marginTop: 14 }}>
            <h3 style={{ marginBottom: 6 }}>Price alerts</h3>
            <div className="muted small">Create simple ABOVE/BELOW alerts. Alerts auto-trigger (become inactive) when condition is met.</div>
            <div className="twoCol" style={{ marginTop: 10 }}>
              <select className="input" value={alertForm.direction} onChange={(e) => setAlertForm((f) => ({ ...f, direction: e.target.value }))}>
                <option value="ABOVE">ABOVE</option>
                <option value="BELOW">BELOW</option>
              </select>
              <input
                className="input"
                placeholder="Target price"
                value={alertForm.target}
                onChange={(e) => setAlertForm((f) => ({ ...f, target: e.target.value }))}
              />
            </div>
            <div style={{ marginTop: 10, display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button className="btn primary" onClick={createAlert}>
                Create alert {alertForm.symbol ? `for ${alertForm.symbol}` : ""}
              </button>
            </div>

            <div className="table" style={{ marginTop: 12 }}>
              <div className="row head" style={{ gridTemplateColumns: "1.2fr 0.9fr 0.9fr 0.9fr 0.7fr" }}>
                <div>Symbol</div>
                <div>Direction</div>
                <div className="right">Target</div>
                <div className="right">Last</div>
                <div className="right">Action</div>
              </div>
              {alerts.map((a) => (
                <div className="row" key={a.id} style={{ gridTemplateColumns: "1.2fr 0.9fr 0.9fr 0.9fr 0.7fr" }}>
                  <div className="mono">
                    {a.stock?.symbol} {a.triggered_at ? <span className="badge">TRIGGERED</span> : a.is_active ? <span className="badge soft">ACTIVE</span> : <span className="badge soft">OFF</span>}
                  </div>
                  <div>{a.direction}</div>
                  <div className="right">{a.target_price}</div>
                  <div className="right">{a.last_price ?? "--"}</div>
                  <div className="right">
                    <button className="btn danger sm" onClick={() => deleteAlert(a.id)}>
                      Delete
                    </button>
                  </div>
                </div>
              ))}
              {alerts.length === 0 ? <div className="muted" style={{ marginTop: 10 }}>No alerts yet.</div> : null}
            </div>
          </div>
        </section>

        <section className="card" style={{ gridColumn: "1 / -1" }}>
          <h3>Tools & security</h3>

          <div className="kpiRow">
            <div className="kpi">
              <div className="kpiLabel">Data source</div>
              <div className="kpiValue">yfinance</div>
            </div>
            <div className="kpi">
              <div className="kpiLabel">Disclaimer</div>
              <div className="kpiValue" style={{ fontSize: 14, fontWeight: 700 }}>
                Educational EDA only
              </div>
            </div>
          </div>

          <div className="kpiRow" style={{ marginTop: 10 }}>
            <div className="kpi">
              <div className="kpiLabel">Export (CSV)</div>
              <div className="muted small" style={{ marginTop: 6 }}>
                Export transactions for any portfolio (useful for EDA in Excel/Python).
              </div>
              <div style={{ marginTop: 10, display: "flex", gap: 10, flexWrap: "wrap" }}>
                {portfolios.slice(0, 3).map((p) => (
                  <button key={p.id} className="btn sm" onClick={() => exportTransactionsCsv(p.id)}>
                    {p.name}
                  </button>
                ))}
                {portfolios.length > 3 ? (
                  <Link className="btn sm" to="/dashboard">
                    Choose portfolio…
                  </Link>
                ) : null}
              </div>
            </div>
            <div className="kpi">
              <div className="kpiLabel">Change password</div>
              <div className="twoCol" style={{ marginTop: 10 }}>
                <input
                  className="input"
                  type="password"
                  placeholder="Old password"
                  value={pwd.old_password}
                  onChange={(e) => setPwd((p) => ({ ...p, old_password: e.target.value }))}
                />
                <input
                  className="input"
                  type="password"
                  placeholder="New password"
                  value={pwd.new_password}
                  onChange={(e) => setPwd((p) => ({ ...p, new_password: e.target.value }))}
                />
              </div>
              <button className="btn danger" style={{ marginTop: 10 }} onClick={changePassword} disabled={pwdBusy}>
                {pwdBusy ? "Please wait..." : "Change password"}
              </button>
              <div className="muted small" style={{ marginTop: 8 }}>
                Changing password logs you out (token invalidated).
              </div>
            </div>
          </div>

          <div style={{ marginTop: 12, display: "flex", gap: 10, flexWrap: "wrap" }}>
            <Link className="btn primary" to="/dashboard">
              Manage portfolios
            </Link>
            <button className="btn ghost" onClick={logout}>
              Logout
            </button>
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}
