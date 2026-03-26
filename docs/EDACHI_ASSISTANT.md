# EDACHI Assistant - Implementation Guide

## 1) What EDACHI Assistant does
EDACHI Assistant is the in-app chatbot for PortfolioAnalyzer. It is designed for:

- Portfolio-aware Q&A
- Fast answers for logged-in users
- Lightweight memory ("learning" from previous user Q&A)
- Optional LLM enrichment when an API key is configured

The assistant can answer:

- "Show my portfolio list"
- "Show my holdings"
- "Give me a summary"
- "Recommend stocks to review"

It reads real user data from the existing database through Django ORM.

## 2) Architecture

### Backend
- File: `backend/api/edachi.py`
- Endpoints:
  - `GET /api/chat/bootstrap/`
  - `POST /api/chat/ask/`
  - `POST /api/chat/reset/`
- Persistence:
  - Uses `api.CachedPayload` (JSON cache table) for:
    - session messages
    - FAQ memory pairs (Q -> A)

### Frontend
- Component: `frontend/src/components/EdachiAssistant.jsx`
- API hooks: `frontend/src/api.js`
- App integration: `frontend/src/App.jsx`
- UI styles: `frontend/src/styles.css`, `frontend/src/mobile.css`

## 3) Data flow

1. User logs in.
2. App warm-up triggers `GET /api/chat/bootstrap/`.
3. Bootstrap data is cached in localStorage (`edachi_bootstrap_cache_v1`) for fast open.
4. User opens EDACHI floating button.
5. User asks question -> `POST /api/chat/ask/`.
6. Backend pipeline:
   - Build user context from DB (portfolios, holdings, sectors, exposure).
   - Try memory hit (previous similar question).
   - Try deterministic intent response (fast rules).
   - Optional LLM call for advanced free-form answers.
   - Save Q&A back to session + memory.
7. Response returns answer + cards + updated message history.

## 4) LLM strategy (best-practice for speed + quality)

EDACHI uses a hybrid approach:

- Layer A: Deterministic intent engine (very fast, low cost)
- Layer B: User-memory retrieval (personalized repeat Q&A)
- Layer C: Optional LLM generation (only when needed)

This gives:

- predictable latency
- lower token cost
- better personalization
- resilient fallback if model/API fails

## 5) Environment variables

Add to `backend/.env`:

```env
# Optional: enable richer LLM responses
OPENAI_API_KEY=your_openai_api_key

# Optional model routing
EDACHI_MODEL_FAST=gpt-4.1-mini
EDACHI_MODEL_REASONING=gpt-4.1
```

If `OPENAI_API_KEY` is missing, EDACHI still works using rules + memory + DB context.

## 6) API contract

### Bootstrap
`GET /api/chat/bootstrap/`

Returns:
- assistant name
- user summary (portfolio/holding counts)
- recent messages
- suggested starter prompts

### Ask
`POST /api/chat/ask/`

Body:
```json
{ "question": "Show my holdings" }
```

Returns:
- `answer`
- `cards` (summary/portfolios/holdings/recommendations)
- `source` (`memory`, `rule`, `llm`, `fallback`)
- `messages` (rolling chat history)

### Reset
`POST /api/chat/reset/`
Clears current user session history.

## 7) Performance decisions

- Bootstrap prefetch during app warm-up.
- localStorage cache for instant open.
- Bounded message history (`last 24`) to keep payload small.
- No heavy DB joins in chat loop beyond holdings/portfolios snapshot.

## 8) Security and privacy

- Chat endpoints require authenticated user token.
- EDACHI only reads the requesting user's data.
- No cross-user memory sharing.
- Keep API key server-side only (never expose in frontend env).

## 9) Suggested next upgrades

1. Add semantic embeddings for stronger memory retrieval.
2. Add tool calling for:
   - creating watchlist alerts
   - opening target portfolio directly
   - generating report on selected stock
3. Add "action chips" in answers (Open Portfolio, Add to Watchlist, Run Analysis).
4. Add guardrails for compliance phrasing in final answers.

## 10) Testing checklist

1. Login -> open EDACHI -> see summary chips.
2. Ask:
   - "Show my portfolio list"
   - "Show holdings"
   - "Give me a summary"
   - "Recommend stocks to review"
3. Refresh page and open EDACHI again (should feel faster due cache).
4. Click reset and verify history clears.
5. (If API key configured) ask free-form strategic question and verify LLM response source.
