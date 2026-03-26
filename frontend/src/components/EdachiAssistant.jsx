import React, { useEffect, useMemo, useRef, useState } from "react";
import { api, getToken } from "../api.js";

const BOOT_CACHE_PREFIX = "edachi_bootstrap_cache_v1";
const GUEST_HISTORY_MAX = 16;
const HOVER_HINTS = [
  "Hi there, how can I help?",
  "Need portfolio insights?",
  "Ask me anything about markets.",
];

function asText(v, fallback = "") {
  if (v === null || v === undefined) return fallback;
  const s = String(v);
  return s.trim() ? s : fallback;
}

function readBootCache(cacheKey, ttlMs = 3 * 60 * 1000) {
  try {
    const raw = localStorage.getItem(cacheKey);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const age = Date.now() - Number(parsed?.savedAt || 0);
    if (age > ttlMs) return null;
    return parsed?.data || null;
  } catch {
    return null;
  }
}

function writeBootCache(cacheKey, data) {
  try {
    localStorage.setItem(cacheKey, JSON.stringify({ savedAt: Date.now(), data }));
  } catch {}
}

export default function EdachiAssistant() {
  const isAuthed = Boolean(getToken());
  const bootCacheKey = `${BOOT_CACHE_PREFIX}_${isAuthed ? "user" : "guest"}`;
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [feedbackByAt, setFeedbackByAt] = useState({});
  const [summary, setSummary] = useState(null);
  const [suggested, setSuggested] = useState([]);
  const [bootstrapped, setBootstrapped] = useState(false);
  const [hintIndex, setHintIndex] = useState(0);
  const [faceIndex, setFaceIndex] = useState(0);
  const bodyRef = useRef(null);

  useEffect(() => {
    if (!open || bootstrapped) return;
    const cached = readBootCache(bootCacheKey);
    if (cached) {
      setMessages(Array.isArray(cached?.recent_messages) ? cached.recent_messages : []);
      setSummary(cached?.summary || null);
      setSuggested(Array.isArray(cached?.suggested_questions) ? cached.suggested_questions : []);
      setBootstrapped(true);
      return;
    }

    let alive = true;
    setBusy(true);
    setError("");
    api
      .edachiBootstrap()
      .then((d) => {
        if (!alive) return;
        setMessages(Array.isArray(d?.recent_messages) ? d.recent_messages : []);
        setSummary(d?.summary || null);
        setSuggested(Array.isArray(d?.suggested_questions) ? d.suggested_questions : []);
        writeBootCache(bootCacheKey, d || {});
        setBootstrapped(true);
      })
      .catch((e) => {
        if (!alive) return;
        setError(e?.message || "Failed to load EDACHI");
      })
      .finally(() => {
        if (!alive) return;
        setBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [bootCacheKey, open, bootstrapped]);

  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, open]);

  useEffect(() => {
    if (!open || !bootstrapped) return;
    writeBootCache(bootCacheKey, {
      summary,
      suggested_questions: suggested,
      recent_messages: messages,
    });
  }, [bootCacheKey, bootstrapped, messages, open, suggested, summary]);

  useEffect(() => {
    setMessages([]);
    setFeedbackByAt({});
    setSummary(null);
    setSuggested([]);
    setBootstrapped(false);
  }, [isAuthed]);

  useEffect(() => {
    const t = setInterval(() => {
      setHintIndex((v) => (v + 1) % HOVER_HINTS.length);
    }, 3000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    const t = setInterval(() => {
      setFaceIndex((v) => (v + 1) % 3);
    }, 2200);
    return () => clearInterval(t);
  }, []);

  const canSend = useMemo(() => question.trim().length > 0 && !busy, [question, busy]);
  const displayMessages = useMemo(() => (Array.isArray(messages) ? messages.slice(-24) : []), [messages]);

  async function ask(qText) {
    const q = asText(qText || question, "");
    if (!q || busy) return;
    setBusy(true);
    setError("");
    try {
      const optimistic = { role: "user", content: q, at: new Date().toISOString() };
      const optimisticMessages = [...messages, optimistic];
      setMessages(optimisticMessages);
      setQuestion("");
      const out = await api.edachiAsk(q, { recent_messages: optimisticMessages });
      const full = Array.isArray(out?.messages) ? out.messages : [];
      if (full.length) {
        setMessages(full);
      } else {
        const assistantMsg = {
          role: "assistant",
          content: asText(out?.answer, "I could not generate a response right now."),
          at: new Date().toISOString(),
          source: out?.source || "fallback",
        };
        setMessages((prev) => [...prev, assistantMsg].slice(-GUEST_HISTORY_MAX));
      }
    } catch (e) {
      setError(e?.message || "Failed to get response");
    } finally {
      setBusy(false);
    }
  }

  async function resetChat() {
    if (busy) return;
    setBusy(true);
    try {
      await api.edachiReset();
      setMessages([]);
      setFeedbackByAt({});
      setError("");
      if (!isAuthed) {
        writeBootCache(bootCacheKey, { summary, suggested_questions: suggested, recent_messages: [] });
      }
    } catch (e) {
      setError(e?.message || "Failed to reset chat");
    } finally {
      setBusy(false);
    }
  }

  async function submitFeedback(messageIndex, helpful) {
    const msg = displayMessages[messageIndex];
    if (!msg || msg.role !== "assistant") return;
    const key = String(msg?.at || `${messageIndex}`);
    if (feedbackByAt[key]?.busy) return;

    let priorUserQuestion = "";
    for (let i = messageIndex - 1; i >= 0; i -= 1) {
      const p = displayMessages[i];
      if (p?.role === "user" && asText(p?.content, "")) {
        priorUserQuestion = asText(p.content, "");
        break;
      }
    }
    if (!priorUserQuestion) return;

    setFeedbackByAt((prev) => ({ ...prev, [key]: { busy: true, value: prev[key]?.value ?? null } }));
    try {
      await api.edachiFeedback({
        question: priorUserQuestion,
        answer: asText(msg?.content, ""),
        helpful: Boolean(helpful),
        source: asText(msg?.source, ""),
      });
      setFeedbackByAt((prev) => ({ ...prev, [key]: { busy: false, value: helpful ? "up" : "down" } }));
    } catch {
      setFeedbackByAt((prev) => ({ ...prev, [key]: { busy: false, value: prev[key]?.value ?? null } }));
    }
  }

  return (
    <>
      <button className={`edachiFab ${open ? "isOpen" : ""}`} type="button" onClick={() => setOpen(true)} aria-label="Open EDACHI Assistant">
        <span className="edachiFabPulse" aria-hidden="true" />
        <span className="edachiFabOrbit" aria-hidden="true" />
        <span className="edachiFabOrbit2" aria-hidden="true" />
        <span className="edachiFabIcon" aria-hidden="true">
          <span className={`edachiFabFace expr-${faceIndex}`}>
            <span />
            <span />
            <span className="edachiFabMouth" />
          </span>
        </span>
        <span className="edachiFabHint" aria-hidden="true">{HOVER_HINTS[hintIndex]}</span>
      </button>

      {open ? (
        <div className="edachiBackdrop" role="presentation" onClick={() => setOpen(false)}>
          <div className="edachiPanel" role="dialog" aria-modal="true" aria-label="EDACHI Assistant" onClick={(e) => e.stopPropagation()}>
            <div className="edachiHead">
              <div className="edachiHeadMeta">
                <div className="edachiAvatar" aria-hidden="true">
                  <span className="edachiAvatarCore">E</span>
                </div>
                <div>
                  <div className="strong">EDACHI Assistant</div>
                  <div className="edachiSubline">
                    <span className="edachiLiveDot" aria-hidden="true" />
                    <span>{isAuthed ? "Portfolio + Sentiment + Actions" : "Markets + Features + Guidance"}</span>
                  </div>
                </div>
              </div>
              <div className="edachiHeadActions">
                <span className="edachiModePill">{isAuthed ? "User Mode" : "Guest Mode"}</span>
                <button className="btn ghost sm" type="button" onClick={resetChat} disabled={busy}>
                  Reset
                </button>
                <button className="edachiCloseBtn" type="button" onClick={() => setOpen(false)} aria-label="Close chat">
                  x
                </button>
              </div>
            </div>

            {summary ? (
              <div className="edachiSummary">
                <div className="chip">Portfolios: {summary.portfolios ?? 0}</div>
                <div className="chip">Holdings: {summary.holdings ?? 0}</div>
                <div className="chip">Watchlist: {summary.watchlist_items ?? 0}</div>
              </div>
            ) : null}

            {error ? <div className="error">{error}</div> : null}

            <div className="edachiBody" ref={bodyRef}>
              {displayMessages.length === 0 && !busy ? (
                <div className="edachiEmpty">
                  <div className="edachiEmptyTitle">Ask anything. Get useful, actionable answers.</div>
                  <div className="muted small">
                    {isAuthed
                      ? "Try portfolio sentiment, add watchlist symbols, or create alerts with natural language."
                      : "Try market snapshot, product tour, or onboarding questions before login."}
                  </div>
                </div>
              ) : null}
              {displayMessages.map((m, idx) => {
                const key = String(m?.at || `${idx}`);
                const feedback = feedbackByAt[key] || { busy: false, value: null };
                return (
                  <div
                    key={`${m?.at || idx}:${idx}`}
                    className={`edachiMsg ${m?.role === "user" ? "user" : "assistant"}`}
                    style={{ animationDelay: `${Math.min(idx, 10) * 40}ms` }}
                  >
                    <div className="edachiMsgRole">{m?.role === "user" ? "You" : "EDACHI"}</div>
                    <div className="edachiMsgContent">{asText(m?.content, "--")}</div>
                    {m?.role === "assistant" ? (
                      <div className="edachiFeedbackRow">
                        <button
                          className={`edachiFeedbackBtn ${feedback.value === "up" ? "active" : ""}`}
                          type="button"
                          onClick={() => submitFeedback(idx, true)}
                          disabled={feedback.busy}
                          aria-label="Helpful response"
                        >
                          Useful
                        </button>
                        <button
                          className={`edachiFeedbackBtn ${feedback.value === "down" ? "active" : ""}`}
                          type="button"
                          onClick={() => submitFeedback(idx, false)}
                          disabled={feedback.busy}
                          aria-label="Not helpful response"
                        >
                          Not useful
                        </button>
                      </div>
                    ) : null}
                  </div>
                );
              })}
              {busy ? (
                <div className="edachiTyping">
                  <span />
                  <span />
                  <span />
                </div>
              ) : null}
            </div>

            <div className="edachiSuggestions">
              {suggested.slice(0, 3).map((s) => (
                <button key={s} className="chip" type="button" onClick={() => ask(s)} disabled={busy}>
                  {s}
                </button>
              ))}
            </div>

            <div className="edachiComposer">
              <input
                className="input edachiInput"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder={isAuthed ? "Ask EDACHI about your portfolios, stocks, risks..." : "Ask EDACHI about features, markets, or how to get started..."}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    ask();
                  }
                }}
              />
              <button className="btn primary sm edachiSend" type="button" onClick={() => ask()} disabled={!canSend}>
                <span>Send</span>
                <span aria-hidden="true">{"->"}</span>
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
