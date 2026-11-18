// First-party usage analytics. Events are posted to our own API on the same
// origin — no third-party script, no cookies.
//
// Two pseudonymous ids ride along: a session id in sessionStorage that dies
// with the tab, and a visitor id in localStorage so the dashboard can count a
// returning browser once. The visitor id is replaced every 90 days (the log
// retention), is never created when the browser sends Global Privacy Control
// or Do Not Track, and is deleted as soon as the API says it is not recording
// them. Neither id is tied to anything about the person.
//
// Only interactions the server cannot already see belong here. Facet, sort and
// paging changes drive the URL and therefore a fresh /api/colas request, so they
// are measured server-side and must not be duplicated.

const ENDPOINT = (import.meta.env.VITE_API_BASE || '/api') + '/events';
const SESSION_KEY = 'ttb-cola:sid';
const VISITOR_KEY = 'ttb-cola:vid';
// Set while the API says it is not recording visitor ids. Holds no id.
const VISITOR_OFF_KEY = 'ttb-cola:vid-off';
const VISITOR_MAX_AGE_MS = 90 * 24 * 60 * 60 * 1000;
// Mirrors VISITOR_POLICY_HEADER in src/api/analytics.py.
const VISITOR_POLICY_HEADER = 'X-Analytics-Visitor';
const FLUSH_DELAY = 1500;
const MAX_BATCH = 20;

let queue = [];
let timer = null;
let cachedSession = null;
let cachedVisitor = null;

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

function localStore() {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function optedOut() {
  try {
    return (
      navigator.globalPrivacyControl === true ||
      navigator.doNotTrack === '1' ||
      window.doNotTrack === '1'
    );
  } catch {
    return false;
  }
}

function forgetVisitor() {
  cachedVisitor = null;
  try {
    localStore()?.removeItem(VISITOR_KEY);
  } catch {
    /* nothing stored, or storage blocked */
  }
}

function serverSaidOff() {
  try {
    return localStore()?.getItem(VISITOR_OFF_KEY) === '1';
  } catch {
    return false;
  }
}

// An opt-out also clears an id stored before it.
const browserOptedOut = optedOut();
if (browserOptedOut) forgetVisitor();
let visitorsOff = browserOptedOut || serverSaidOff();

// Without localStorage there is no visitor id; the server counts the session
// instead.
function visitorId() {
  if (visitorsOff) return null;
  if (cachedVisitor) return cachedVisitor;
  const store = localStore();
  if (!store) return null;
  try {
    const now = Date.now();
    const saved = JSON.parse(store.getItem(VISITOR_KEY) || 'null');
    if (
      saved &&
      typeof saved.id === 'string' &&
      typeof saved.created === 'number' &&
      saved.created <= now &&
      now - saved.created < VISITOR_MAX_AGE_MS
    ) {
      cachedVisitor = saved.id;
      return cachedVisitor;
    }
    const id = crypto.randomUUID();
    store.setItem(VISITOR_KEY, JSON.stringify({ id, created: now }));
    cachedVisitor = id;
  } catch {
    cachedVisitor = null;
  }
  return cachedVisitor;
}

// Identity headers for a request to our own API.
export function identityHeaders() {
  const headers = {};
  const sid = sessionId();
  if (sid) headers['X-Client-Session'] = sid;
  const vid = visitorId();
  if (vid) headers['X-Client-Visitor'] = vid;
  return headers;
}

// Every API response says whether visitor ids are being recorded. "off" drops
// the stored id and is remembered, so later page loads do not mint one only to
// throw it away; "on" lifts that again.
export function noteVisitorPolicy(response) {
  try {
    const policy = response?.headers?.get(VISITOR_POLICY_HEADER);
    const store = localStore();
    if (policy === 'off' && !visitorsOff) {
      visitorsOff = true;
      forgetVisitor();
      store?.setItem(VISITOR_OFF_KEY, '1');
    } else if (policy === 'on' && serverSaidOff()) {
      store?.removeItem(VISITOR_OFF_KEY);
      visitorsOff = browserOptedOut;
    }
  } catch {
    /* analytics is best effort */
  }
}

function send(events) {
  const payload = JSON.stringify({ events });
  const headers = { 'Content-Type': 'application/json', ...identityHeaders() };

  try {
    // keepalive so events queued during a click-through still leave the page.
    fetch(ENDPOINT, { method: 'POST', body: payload, headers, keepalive: true })
      .then(noteVisitorPolicy)
      .catch(() => {});
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
