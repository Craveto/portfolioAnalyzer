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

function fmtNum(v, nd = 2) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "--";
  return n.toLocaleString(undefined, { maximumFractionDigits: nd, minimumFractionDigits: nd });
}

function safePctForUi(item) {
  const invested = Number(item?.invested);
  const pct = Number(item?.unrealized_pnl_pct);
  if (!Number.isFinite(pct)) return null;
  if (!Number.isFinite(invested) || invested < 100) return null;
  if (Math.abs(pct) > 500) return null;
  return pct;
}

function parseLegacyHoldingsCard(content) {
  const text = asText(content, "");
  if (!text) return null;
  const lines = text.split("\n").map((x) => x.trim()).filter(Boolean);
  const items = [];
  for (const line of lines) {
    if (!line.startsWith("- ")) continue;
    const raw = line.slice(2);
    const symbolMatch = raw.match(/^([A-Za-z0-9.\-_]+)\s*:/) || raw.match(/^([A-Za-z0-9.\-_]+)/);
    const symbol = String(symbolMatch?.[1] || "").replace(":", "").trim().toUpperCase();
    if (!symbol) continue;
    const item = { symbol };
    const normalized = raw.replace(/\|/g, ",");
    const chunks = normalized.split(",").map((p) => p.trim()).filter(Boolean);
    for (const p of chunks) {
      const low = p.toLowerCase();
      const num = Number(String(p).replace(/[^0-9.\-]/g, ""));
      if (low.startsWith("qty")) item.qty = Number.isFinite(num) ? num : null;
      if (low.startsWith("avg") || low.startsWith("buy")) item.avg_buy_price = Number.isFinite(num) ? num : null;
      if (low.startsWith("ltp") || low.startsWith("now")) item.last_price = Number.isFinite(num) ? num : null;
      if (low.startsWith("p/e")) item.pe = Number.isFinite(num) ? num : null;
    }
    const pnlMatch = raw.match(/un(?:rlz|realized)\s*p\/?l\s*([-+]?[0-9,]+(?:\.[0-9]+)?)\s*(?:\(([-+]?[0-9,]+(?:\.[0-9]+)?)%\))?/i);
    if (pnlMatch) {
      const pnl = Number(String(pnlMatch[1]).replace(/,/g, ""));
      if (Number.isFinite(pnl)) item.unrealized_pnl = pnl;
      if (pnlMatch[2]) {
        const pct = Number(String(pnlMatch[2]).replace(/,/g, ""));
        if (Number.isFinite(pct)) item.unrealized_pnl_pct = pct;
      }
    }
    items.push(item);
  }
  if (!items.length) return null;
  return { type: "holdings_metrics", items };
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
        const patched = full.map((m) => ({ ...m }));
        const lastAssistant = [...patched].reverse().find((m) => m?.role === "assistant");
        if (lastAssistant && Array.isArray(out?.cards) && out.cards.length) {
          lastAssistant.cards = out.cards;
        }
        setMessages(patched);
      } else {
        const assistantMsg = {
          role: "assistant",
          content: asText(out?.answer, "I could not generate a response right now."),
          at: new Date().toISOString(),
          source: out?.source || "fallback",
          cards: Array.isArray(out?.cards) ? out.cards : [],
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
                const cards = Array.isArray(m?.cards) ? m.cards : [];
                const holdingsCard =
                  cards.find((c) => c?.type === "holdings_metrics" && Array.isArray(c?.items))
                  || parseLegacyHoldingsCard(m?.content);
                const visualCards = holdingsCard
                  ? [holdingsCard, ...cards.filter((c) => c?.type !== "holdings_metrics")]
                  : cards;
                const messageText = holdingsCard
                  ? asText(m?.content, "--").split("\n")[0]
                  : asText(m?.content, "--");
                const renderCard = (card, cardIndex) => {
                  if (!card || typeof card !== "object") return null;
                  if (card.type === "holdings_metrics" && Array.isArray(card.items)) {
                    return (
                      <div className="edachiMetricsCard" key={`card:${cardIndex}:${card.type}`}>
                        <div className="edachiMetricsHead">
                          <span>Symbol</span>
                          <span>P/L</span>
                        </div>
                        <div className="edachiMetricsRows">
                          {card.items.slice(0, 8).map((it) => {
                            const pct = safePctForUi(it);
                            return (
                              <div className="edachiMetricsRow" key={`${it.symbol}:${it.portfolio_name || ""}`}>
                                <div className="edachiMetricsMain">
                                  <div className="edachiMetricsSymbol">{it.symbol}</div>
                                  <div className="edachiMetricsMeta">
                                    Qty {fmtNum(it.qty, 0)} | Avg {fmtNum(it.avg_buy_price)} | LTP {fmtNum(it.last_price)} | P/E {fmtNum(it.pe)}
                                  </div>
                                </div>
                                <div className={`edachiMetricsPnl ${(Number(it.unrealized_pnl) || 0) >= 0 ? "up" : "down"}`}>
                                  {fmtNum(it.unrealized_pnl)}{pct !== null ? ` (${fmtNum(pct)}%)` : ""}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  }
                  if (card.type === "portfolios" && Array.isArray(card.items)) {
                    return (
                      <div className="edachiMiniCard" key={`card:${cardIndex}:${card.type}`}>
                        <div className="edachiMiniTitle">Portfolios</div>
                        <div className="edachiTagGrid">
                          {card.items.slice(0, 8).map((it) => (
                            <span className="edachiTag" key={`${it.id}:${it.name}`}>{it.name} ({it.market || "--"})</span>
                          ))}
                        </div>
                      </div>
                    );
                  }
                  if (card.type === "holdings" && Array.isArray(card.items)) {
                    return (
                      <div className="edachiMiniCard" key={`card:${cardIndex}:${card.type}`}>
                        <div className="edachiMiniTitle">Holdings Snapshot</div>
                        <div className="edachiSimpleList">
                          {card.items.slice(0, 8).map((it) => (
                            <div className="edachiSimpleRow" key={`${it.symbol}:${it.portfolio_name}`}>
                              <span>{it.symbol}</span>
                              <span>Qty {fmtNum(it.qty, 0)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  }
                  if (card.type === "recommendations" && Array.isArray(card.items)) {
                    return (
                      <div className="edachiMiniCard" key={`card:${cardIndex}:${card.type}`}>
                        <div className="edachiMiniTitle">Recommendations</div>
                        <div className="edachiTagGrid">
                          {card.items.slice(0, 8).map((it) => {
                            const label = typeof it === "string" ? it : `${it.symbol || "--"}${Number.isFinite(Number(it.score)) ? ` (Fit ${Math.round(Number(it.score))})` : ""}`;
                            return <span className="edachiTag" key={label}>{label}</span>;
                          })}
                        </div>
                      </div>
                    );
                  }
                  if (card.type === "quote" && card.data) {
                    return (
                      <div className="edachiMiniCard" key={`card:${cardIndex}:${card.type}`}>
                        <div className="edachiMiniTitle">{card.data.ticker || "Quote"}</div>
                        <div className="edachiSimpleRow">
                          <span>Last</span>
                          <strong>{fmtNum(card.data.last_price)}</strong>
                        </div>
                        <div className="edachiSimpleRow">
                          <span>Prev Close</span>
                          <span>{fmtNum(card.data.previous_close)}</span>
                        </div>
                      </div>
                    );
                  }
                  if (card.type === "market" && card.data) {
                    const n = card.data.nifty || {};
                    const s = card.data.sensex || {};
                    return (
                      <div className="edachiMiniCard" key={`card:${cardIndex}:${card.type}`}>
                        <div className="edachiMiniTitle">Market Snapshot</div>
                        <div className="edachiSimpleRow"><span>Nifty</span><strong>{fmtNum(n.last_price)}</strong></div>
                        <div className="edachiSimpleRow"><span>Sensex</span><strong>{fmtNum(s.last_price)}</strong></div>
                      </div>
                    );
                  }
                  return null;
                };
                return (
                  <div
                    key={`${m?.at || idx}:${idx}`}
                    className={`edachiMsg ${m?.role === "user" ? "user" : "assistant"}`}
                    style={{ animationDelay: `${Math.min(idx, 10) * 40}ms` }}
                  >
                    <div className="edachiMsgRole">{m?.role === "user" ? "You" : "EDACHI"}</div>
                    <div className="edachiMsgContent">{asText(m?.content, "--")}</div>
                    <div className="edachiMsgContent">{messageText}</div>
                    {m?.role === "assistant" && visualCards.length ? (
                      <div className="edachiCards">
                        {visualCards.slice(0, 3).map((c, cardIdx) => renderCard(c, cardIdx))}
                      </div>
                    ) : null}
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
