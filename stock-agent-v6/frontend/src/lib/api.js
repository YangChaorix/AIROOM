const BASE = "/api";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json();
}

export const api = {
  listRuns: (limit = 20) => request(`/runs?limit=${limit}`),
  getRun: (id) => request(`/runs/${id}`),
  getQueue: () => request("/queue"),
  listTriggers: (status, limit = 50, date) => {
    const qs = new URLSearchParams({ limit });
    if (status) qs.set("status", status);
    if (date) qs.set("date", date);
    return request(`/triggers?${qs}`);
  },
  consume: (n = 1) => request(`/queue/consume?n=${n}`, { method: "POST" }),
  startStock: (codeOrName, withPeers = true) => request("/stock", { method: "POST", body: JSON.stringify({ code_or_name: codeOrName, with_peers: withPeers }) }),
  getStockHistory: (code, limit = 50) => request(`/stocks/${code}/history?limit=${limit}`),
  listConditions: () => request("/conditions"),
  updateCondition: (id, payload) => request(`/conditions/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  listChannels: () => request("/channels"),
  updateChannel: (name, payload) => request(`/channels/${name}`, { method: "PUT", body: JSON.stringify(payload) }),
  runChannel: (name) => request(`/channels/${name}/run`, { method: "POST" }),
  runAllChannels: () => request(`/channels/run-all`, { method: "POST" }),
  runTriggerNow: () => request(`/triggers/run-now`, { method: "POST" }),
  getPrompt: (agent) => request(`/prompts/${agent}`),
  savePrompt: (agent, content, comment) => request(`/prompts/${agent}`, { method: "POST", body: JSON.stringify({ content, comment }) }),
  rollbackPrompt: (agent, versionCode) => request(`/prompts/${agent}/rollback/${versionCode}`, { method: "POST" }),
  agentsStatus: () => request("/agents/status"),
  listNews: ({ consumed, source, date, limit = 50 } = {}) => {
    const qs = new URLSearchParams();
    if (consumed !== undefined) qs.set("consumed", consumed);
    if (source) qs.set("source", source);
    if (date) qs.set("date", date);
    qs.set("limit", limit);
    return request(`/news?${qs}`);
  },
  listNewsByIds: (ids) => {
    if (!ids || ids.length === 0) return Promise.resolve([]);
    const qs = new URLSearchParams({ ids: ids.join(","), limit: ids.length });
    return request(`/news?${qs}`);
  },
  newsStats: () => request("/news/stats"),
  listLogs: ({ level, source_prefix, date, limit = 50 } = {}) => {
    const qs = new URLSearchParams();
    if (level) qs.set("level", level);
    if (source_prefix) qs.set("source_prefix", source_prefix);
    if (date) qs.set("date", date);
    qs.set("limit", limit);
    return request(`/logs?${qs}`);
  },
  getInfo: () => request("/info"),
  listRecommendations: (days = 7) => request(`/recommendations?days=${days}`),
};
