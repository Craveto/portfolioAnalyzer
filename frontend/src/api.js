const configuredApiBase = (import.meta.env.VITE_API_BASE_URL || "").trim();
const API_BASE = configuredApiBase || (import.meta.env.DEV ? "http://localhost:8000" : "");

if (!configuredApiBase && !import.meta.env.DEV) {
  console.warn("VITE_API_BASE_URL is not set for this production build; frontend will use same-origin /api paths.");
}

export function getToken() {
  return localStorage.getItem("authToken");
}

export function setToken(token) {
  localStorage.setItem("authToken", token);
}

export function clearTokens() {
  localStorage.removeItem("authToken");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function apiFetch(path, { method = "GET", body, auth = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const token = getToken();
    if (token) headers.Authorization = `Token ${token}`;
  }

  const url = `${API_BASE}${path}`;
  const isGet = String(method).toUpperCase() === "GET";
  const maxAttempts = isGet ? 3 : 1;

  let lastErr = null;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const res = await fetch(url, {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined
      });

      const text = await res.text();
      let data = null;
      if (text) {
        try {
          data = JSON.parse(text);
        } catch {
          data = text;
        }
      }

      // Retry transient upstream errors on GET (Render cold start / yfinance hiccups).
      if (isGet && !res.ok && [502, 503, 504].includes(res.status) && attempt < maxAttempts) {
        await sleep(350 * attempt * attempt);
        continue;
      }

      if (!res.ok) {
        const msg = (() => {
          if (!data) return `HTTP ${res.status}`;
          if (typeof data === "string") return data;
          if (typeof data === "object") {
            if (data.detail) return String(data.detail);
            if (data.message) return String(data.message);
            const entries = Object.entries(data);
            if (entries.length) {
              const [k, v] = entries[0];
              if (Array.isArray(v) && v.length) return `${k}: ${String(v[0])}`;
              return `${k}: ${String(v)}`;
            }
          }
          return `HTTP ${res.status}`;
        })();
        throw new Error(msg);
      }

      return data;
    } catch (e) {
      lastErr = e;
      // Network error / cold start: retry only for GET.
      if (isGet && attempt < maxAttempts) {
        await sleep(350 * attempt * attempt);
        continue;
      }
      throw e;
    }
  }

  throw lastErr || new Error("Request failed");
}

async function apiFetchMultipart(path, { method = "POST", formData, auth = false, signal } = {}) {
  const headers = {};
  if (auth) {
    const token = getToken();
    if (token) headers.Authorization = `Token ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: formData,
    signal
  });

  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const msg = (() => {
      if (!data) return `HTTP ${res.status}`;
      if (typeof data === "string") return data;
      if (typeof data === "object" && data.detail) return String(data.detail);
      return `HTTP ${res.status}`;
    })();
    throw new Error(msg);
  }
  return data;
}

export const api = {
  marketSummary() {
    return apiFetch("/api/market/summary/");
  },
  metalsSummary(days = 7) {
    return apiFetch(`/api/market/metals/summary/?days=${encodeURIComponent(String(days))}`);
  },
  metalsNews(limit = 6) {
    return apiFetch(`/api/market/metals/news/?limit=${encodeURIComponent(String(limit))}`);
  },
  metalsQuote(ttl = 20) {
    return apiFetch(`/api/market/metals/quote/?ttl=${encodeURIComponent(String(ttl))}`);
  },
  metalsForecast(horizon = "1w") {
    return apiFetch(`/api/market/metals/forecast/?horizon=${encodeURIComponent(String(horizon))}`);
  },
  btcSummary(days = 30) {
    return apiFetch(`/api/market/btc/summary/?days=${encodeURIComponent(String(days))}`);
  },
  btcNews(limit = 6) {
    return apiFetch(`/api/market/btc/news/?limit=${encodeURIComponent(String(limit))}`);
  },
  btcQuote(ttl = 20) {
    return apiFetch(`/api/market/btc/quote/?ttl=${encodeURIComponent(String(ttl))}`);
  },
  btcPredictions(horizon = "1m") {
    return apiFetch(`/api/market/btc/predictions/?horizon=${encodeURIComponent(String(horizon))}`);
  },
  quote(symbol) {
    return apiFetch(`/api/market/quote/?symbol=${encodeURIComponent(symbol)}`);
  },
  register({ username, email, password }) {
    return apiFetch("/api/auth/register/", { method: "POST", body: { username, email, password } });
  },
  login({ username, password }) {
    return apiFetch("/api/auth/login/", { method: "POST", body: { username, password } });
  },
  me() {
    return apiFetch("/api/auth/me/", { auth: true });
  },
  account() {
    return apiFetch("/api/auth/account/", { auth: true });
  },
  updateAccount(patch) {
    return apiFetch("/api/auth/account/", { method: "PATCH", body: patch, auth: true });
  },
  changePassword({ old_password, new_password }) {
    return apiFetch("/api/auth/password/change/", { method: "POST", body: { old_password, new_password }, auth: true });
  },
  listWatchlist() {
    return apiFetch("/api/watchlist/", { auth: true });
  },
  addWatchlist({ stock_symbol, stock_name }) {
    return apiFetch("/api/watchlist/", { method: "POST", body: { stock_symbol, stock_name }, auth: true });
  },
  deleteWatchlistItem(itemId) {
    return apiFetch(`/api/watchlist/${itemId}/`, { method: "DELETE", auth: true });
  },
  listAlerts() {
    return apiFetch("/api/alerts/", { auth: true });
  },
  createAlert({ stock_symbol, stock_name, direction, target_price }) {
    return apiFetch("/api/alerts/", { method: "POST", body: { stock_symbol, stock_name, direction, target_price }, auth: true });
  },
  deleteAlert(alertId) {
    return apiFetch(`/api/alerts/${alertId}/`, { method: "DELETE", auth: true });
  },
  dashboardSummary(force = false) {
    const qs = force ? "?force=1" : "";
    return apiFetch(`/api/dashboard/summary/${qs}`, { auth: true });
  },
  listStocks(q) {
    const qs = q ? `?q=${encodeURIComponent(q)}` : "";
    return apiFetch(`/api/stocks/${qs}`);
  },
  searchStocksLive(q) {
    const qs = q ? `?q=${encodeURIComponent(q)}` : "";
    return apiFetch(`/api/stocks/live/${qs}`);
  },
  stockDetail(symbol) {
    return apiFetch(`/api/stocks/detail/?symbol=${encodeURIComponent(symbol)}`);
  },
  stocksPreview(symbols) {
    const list = Array.isArray(symbols) ? symbols : [];
    const qs = list.length ? `?symbols=${encodeURIComponent(list.join(","))}` : "";
    return apiFetch(`/api/stocks/preview/${qs}`);
  },
  listPortfolios() {
    return apiFetch("/api/portfolios/", { auth: true });
  },
  createPortfolio({ name }) {
    return apiFetch("/api/portfolios/", { method: "POST", body: { name }, auth: true });
  },
  previewPortfolioCsv({ file, groupBySector = false, baseName, signal } = {}) {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("mode", "preview");
    fd.append("group_by_sector", groupBySector ? "true" : "false");
    if (typeof baseName === "string" && baseName.trim()) fd.append("base_name", baseName.trim());
    return apiFetchMultipart("/api/portfolios/import-csv/", { method: "POST", formData: fd, auth: true, signal });
  },
  importPortfolioCsv({ file, groupBySector = false, baseName, signal } = {}) {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("mode", "import");
    fd.append("group_by_sector", groupBySector ? "true" : "false");
    if (typeof baseName === "string" && baseName.trim()) fd.append("base_name", baseName.trim());
    return apiFetchMultipart("/api/portfolios/import-csv/", { method: "POST", formData: fd, auth: true, signal });
  },
  getPortfolio(portfolioId, force = false) {
    const qs = force ? "?force=1" : "";
    return apiFetch(`/api/portfolios/${portfolioId}/${qs}`, { auth: true });
  },
  deletePortfolio(portfolioId) {
    return apiFetch(`/api/portfolios/${portfolioId}/`, { method: "DELETE", auth: true });
  },
  listTransactions(portfolioId) {
    return apiFetch(`/api/portfolios/${portfolioId}/transactions/`, { auth: true });
  },
  createTransaction(portfolioId, { stock_symbol, stock_name, side, qty, price }) {
    return apiFetch(`/api/portfolios/${portfolioId}/transactions/`, {
      method: "POST",
      body: { stock_symbol, stock_name, side, qty, price },
      auth: true
    });
  },
  deleteHolding(portfolioId, holdingId) {
    return apiFetch(`/api/portfolios/${portfolioId}/holdings/${holdingId}/`, { method: "DELETE", auth: true });
  },
  portfolioPE(portfolioId, force = false) {
    const qs = force ? "?force=1" : "";
    return apiFetch(`/api/analysis/portfolio/${portfolioId}/pe/${qs}`, { auth: true });
  },
  portfolioForecast(portfolioId, days = 90) {
    return apiFetch(`/api/analysis/portfolio/${portfolioId}/forecast/?days=${encodeURIComponent(days)}`, { auth: true });
  },
  portfolioSentiment(portfolioId) {
    return apiFetch(`/api/analysis/portfolio/${portfolioId}/sentiment/`, { auth: true });
  },
  stockInsight(portfolioId, symbol, force = false) {
    const qs = force ? "?force=1" : "";
    return apiFetch(`/api/analysis/portfolio/${portfolioId}/stocks/${encodeURIComponent(symbol)}/insight/${qs}`, { auth: true });
  },
  quickStockSentiment(symbol, name = "", force = false) {
    const qs = `?symbol=${encodeURIComponent(symbol || "")}${name ? `&name=${encodeURIComponent(name)}` : ""}${force ? "&force=1" : ""}`;
    return apiFetch(`/api/analysis/stock/quick-sentiment/${qs}`, { auth: true });
  },
  async stockReport(portfolioId, symbol, format = "md") {
    const token = getToken();
    const res = await fetch(
      `${API_BASE}/api/analysis/portfolio/${portfolioId}/stocks/${encodeURIComponent(symbol)}/report/?format=${encodeURIComponent(format)}`,
      {
        method: "GET",
        headers: token ? { Authorization: `Token ${token}` } : {}
      }
    );
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    return blob;
  },
  cluster({ portfolioIds = [], k = 3 } = {}) {
    const ids = Array.isArray(portfolioIds) ? portfolioIds.filter(Boolean) : [];
    const qs = `?portfolio_ids=${encodeURIComponent(ids.join(","))}&k=${encodeURIComponent(String(k))}`;
    return apiFetch(`/api/analysis/cluster/${qs}`, { auth: true });
  },
  async clusterCsv({ portfolioIds = [], k = 3 } = {}) {
    const ids = Array.isArray(portfolioIds) ? portfolioIds.filter(Boolean) : [];
    const token = getToken();
    const qs = `?portfolio_ids=${encodeURIComponent(ids.join(","))}&k=${encodeURIComponent(String(k))}`;
    const res = await fetch(`${API_BASE}/api/analysis/cluster/csv/${qs}`, {
      method: "GET",
      headers: token ? { Authorization: `Token ${token}` } : {}
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    return blob;
  }
};
