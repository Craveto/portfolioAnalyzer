const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export function getToken() {
  return localStorage.getItem("authToken");
}

export function setToken(token) {
  localStorage.setItem("authToken", token);
}

export function clearTokens() {
  localStorage.removeItem("authToken");
}

async function apiFetch(path, { method = "GET", body, auth = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const token = getToken();
    if (token) headers.Authorization = `Token ${token}`;
  }
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
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
}

export const api = {
  marketSummary() {
    return apiFetch("/api/market/summary/");
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
  dashboardSummary() {
    return apiFetch("/api/dashboard/summary/", { auth: true });
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
  getPortfolio(portfolioId) {
    return apiFetch(`/api/portfolios/${portfolioId}/`, { auth: true });
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
  portfolioPE(portfolioId) {
    return apiFetch(`/api/analysis/portfolio/${portfolioId}/pe/`, { auth: true });
  },
  portfolioForecast(portfolioId, days = 90) {
    return apiFetch(`/api/analysis/portfolio/${portfolioId}/forecast/?days=${encodeURIComponent(days)}`, { auth: true });
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
