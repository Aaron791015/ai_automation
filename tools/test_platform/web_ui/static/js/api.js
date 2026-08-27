// fetch 包裝：統一 {ok,error} 解析、逾時、409 特別處理（帶 blocking_run_id）。
export class ApiError extends Error {
  constructor(msg, status, data) { super(msg); this.status = status; this.data = data || {}; }
}
async function req(method, url, body, { timeout = 30000 } = {}) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeout);
  try {
    const r = await fetch(url, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
      signal: ctl.signal,
    });
    let data = {};
    try { data = await r.json(); } catch { data = { ok: r.ok, error: r.statusText }; }
    if (!r.ok || data.ok === false) throw new ApiError(data.error || `HTTP ${r.status}`, r.status, data);
    return data;
  } finally { clearTimeout(t); }
}
export const api = {
  get: (u, o) => req('GET', u, null, o),
  post: (u, b, o) => req('POST', u, b || {}, o),
  put: (u, b, o) => req('PUT', u, b || {}, o),
  patch: (u, b, o) => req('PATCH', u, b || {}, o),
  del: (u, o) => req('DELETE', u, null, o),
  bootstrap: () => req('GET', '/api/bootstrap'),
  active: () => req('GET', '/api/runs/active', null, { timeout: 8000 }),
};
