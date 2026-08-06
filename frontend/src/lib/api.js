// Thin fetch client for the COLA API. No external data-fetching library —
// just fetch plus small typed helpers.

import { clientSessionId, track } from './analytics.js';

const BASE = import.meta.env.VITE_API_BASE || '/api';

class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

async function request(path, { method = 'GET', body, signal } = {}) {
  const opts = { method, signal, headers: {} };
  const sid = clientSessionId();
  if (sid) opts.headers['X-Client-Session'] = sid;
  if (body instanceof FormData) {
    opts.body = body;
  } else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(BASE + path, opts);
  if (!res.ok) {
    let detail;
    try {
      detail = await res.json();
    } catch {
      detail = await res.text().catch(() => '');
    }
    const message = (detail && detail.detail) || res.statusText || 'Request failed';
    // Endpoint only: the path can carry the user's search terms.
    if (path !== '/events') track('client_api_error', { endpoint: path.split('?')[0], status: res.status });
    throw new ApiError(message, res.status, detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

// Build a query string from a plain object, skipping empty values.
export function toQuery(params) {
  const usp = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v === undefined || v === null || v === '') return;
    usp.set(k, v);
  });
  const s = usp.toString();
  return s ? `?${s}` : '';
}

export const api = {
  reference: (signal) => request('/reference', { signal }),

  searchColas: (params, signal) => request(`/colas${toQuery(params)}`, { signal }),

  getCola: (id, signal) => request(`/colas/${encodeURIComponent(id)}`, { signal }),

  similar: (id, limit = 8, signal, scope) =>
    request(`/colas/${encodeURIComponent(id)}/similar${toQuery({ limit, scope })}`, { signal }),

  searchByImage: ({ file, commodity, limit = 24 }, signal) => {
    const form = new FormData();
    form.append('file', file);
    if (commodity) form.append('commodity', commodity);
    form.append('limit', String(limit));
    return request('/search/image', { method: 'POST', body: form, signal });
  },

  // GET, so the whole query lives in the URL and results stay deep-linkable.
  searchByDescription: ({ q, commodity, limit = 24 }, signal) =>
    request(`/search/describe${toQuery({ q, commodity, limit })}`, { signal }),

  // Unlisted usage dashboard. 404s unless the deployment enables it.
  analyticsDashboard: (params, signal) =>
    request(`/analytics/dashboard${toQuery(params)}`, { signal }),
};

export { ApiError };
