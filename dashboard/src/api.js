/**
 * dashboard/src/api.js
 * Thin fetch wrapper for the control-api with response validation.
 *
 * All API calls are relative paths — nginx proxies them to control-api:8003.
 * Write endpoints (POST /sim/run, POST /quarantine/.../release) have the
 * X-Internal-Key header injected by nginx at the proxy layer.
 * The secret key is NEVER present in client-side JavaScript.
 */

async function _fetch(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...options.headers };
  const res = await fetch(path, { ...options, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Response validators ────────────────────────────────────────────────────
// Guard against contract drift: if the API response shape changes and the
// dashboard doesn't match, we throw a descriptive error instead of rendering
// undefined values (which causes blank pages via React error #31).

function validateStats(data) {
  if (typeof data !== 'object' || data === null) throw new Error('stats: not an object');
  // total_events is the only field we render; others are optional
  if (!('total_events' in data) && !('total' in data)) throw new Error('stats: missing total_events');
  return data;
}

function validateEvents(data) {
  if (!Array.isArray(data?.data)) throw new Error('events: missing data array');
  return data;
}

function validateQuarantine(data) {
  if (!Array.isArray(data?.data)) throw new Error('quarantine: missing data array');
  return data;
}

function validateHoneytokens(data) {
  if (!Array.isArray(data?.tokens)) throw new Error('honeytokens: missing tokens array');
  // Each token must be either a string (old) or an object with .token (new)
  for (const t of data.tokens) {
    if (typeof t !== 'string' && typeof t?.token !== 'string') {
      throw new Error('honeytokens: token entry is neither string nor {token: string}');
    }
  }
  return data;
}

function validateSimStatus(data) {
  if (!('status' in data)) throw new Error('sim/status: missing status field');
  return data;
}

export const api = {
  getStats:       ()       => _fetch('/stats').then(validateStats),
  getEvents:      (params) => _fetch(`/events?${new URLSearchParams(params)}`).then(validateEvents),
  getQuarantine:  ()       => _fetch('/quarantine').then(validateQuarantine),
  getHoneytokens: ()       => _fetch('/honeytokens').then(validateHoneytokens),
  getSimStatus:   ()       => _fetch('/sim/status').then(validateSimStatus),

  // Write endpoints — X-Internal-Key is injected by nginx, not the browser
  releaseQuarantine: (identity) =>
    _fetch(`/quarantine/${encodeURIComponent(identity)}/release`, {
      method: 'POST',
    }),

  runSim: (scenario) =>
    _fetch('/sim/run', {
      method: 'POST',
      body: JSON.stringify({ scenario }),
    }),

  resetDemoData: () =>
    _fetch('/reset', {
      method: 'POST',
    }),
};
