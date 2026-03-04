import React, { useMemo, useState } from "react";
import { api, setToken } from "../api.js";

export default function LoginModal({ open, onClose, onAuthed }) {
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const title = useMemo(() => (mode === "login" ? "Login" : "Create account"), [mode]);

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (mode === "signup") {
        await api.register({ username, email, password });
      }
      const res = await api.login({ username, password });
      setToken(res.token);
      onAuthed?.();
      onClose?.();
    } catch (err) {
      setError(err.message || "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;

  return (
    <div className="modalBackdrop" role="dialog" aria-modal="true">
      <div className="modal">
        <div className="modalHeader">
          <h2>{title}</h2>
          <button className="btn ghost" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <div className="segmented">
          <button className={mode === "login" ? "seg active" : "seg"} onClick={() => setMode("login")}>
            Login
          </button>
          <button className={mode === "signup" ? "seg active" : "seg"} onClick={() => setMode("signup")}>
            Signup
          </button>
        </div>

        <form onSubmit={submit} className="form">
          <label className="label">
            Username
            <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} required />
          </label>

          {mode === "signup" ? (
            <label className="label">
              Email (optional)
              <input className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
          ) : null}

          <label className="label">
            Password
            <input
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>

          {error ? <div className="error">{error}</div> : null}

          <button className="btn primary" disabled={busy}>
            {busy ? "Please wait..." : mode === "login" ? "Login" : "Create account"}
          </button>
        </form>

        <div className="modalFooter">
          <span className="muted">Tip: For Day-1 demo, keep it simple and show end-to-end flow.</span>
        </div>
      </div>
    </div>
  );
}
