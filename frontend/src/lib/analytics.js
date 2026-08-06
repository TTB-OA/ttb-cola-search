// First-party usage analytics. Events are posted to our own API on the same
// origin — no third-party script, no cookies, no cross-session identity.
//
// Only interactions the server cannot already see belong here. Facet, sort and
// paging changes drive the URL and therefore a fresh /api/colas request, so they
// are measured server-side and must not be duplicated.

const ENDPOINT = (import.meta.env.VITE_API_BASE || '/api') + '/events';
const SESSION_KEY = 'ttb-cola:sid';
const FLUSH_DELAY = 1500;
const MAX_BATCH = 20;

let queue = [];
let timer = null;
let cachedSession = null;

// Storage can be blocked (private mode, hardened browsers); analytics must
// degrade rather than throw into a click handler.
function safeStorage() {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function sessionId() {
  if (cachedSession) return cachedSession;
  const store = safeStorage();
  try {
    const existing = store && store.getItem(SESSION_KEY);
    if (existing) {
      cachedSession = existing;
      return cachedSession;
    }
    cachedSession = crypto.randomUUID();
    if (store) store.setItem(SESSION_KEY, cachedSession);
  } catch {
    cachedSession = cachedSession || null;
  }
  return cachedSession;
}

export function clientSessionId() {
  return sessionId();
}

function send(events) {
  const payload = JSON.stringify({ events });
  const headers = { 'Content-Type': 'application/json' };
  const sid = sessionId();
  if (sid) headers['X-Client-Session'] = sid;

  try {
    // keepalive so events queued during a click-through still leave the page.
    fetch(ENDPOINT, { method: 'POST', body: payload, headers, keepalive: true }).catch(() => {});
  } catch {
    /* analytics is best effort */
  }
}

function flush() {
  clearTimeout(timer);
  timer = null;
  if (!queue.length) return;
  const batch = queue;
  queue = [];
  send(batch);
}

export function track(name, props) {
  try {
    queue.push({ name, props: props || {} });
    if (queue.length >= MAX_BATCH) {
      flush();
      return;
    }
    if (!timer) timer = setTimeout(flush, FLUSH_DELAY);
  } catch {
    /* never let instrumentation break the UI */
  }
}

if (typeof document !== 'undefined') {
  // Page hide is the last reliable moment to ship queued events.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush();
  });
}
