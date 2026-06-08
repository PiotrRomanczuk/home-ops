/**
 * home-ops-log — drop-in client for emitting app:<slug> events from Node.
 *
 * Single-file ESM, no deps. Vendored into Node projects (Next.js, scripts,
 * services) that want to surface lifecycle and errors in the home-ops console.
 *
 * Usage:
 *   import * as hops from './lib/home-ops-log.mjs';
 *   hops.init('guitar-crm');
 *
 *   hops.event('stripe webhook received', { data: { event_id: evt.id } });
 *   hops.event('twilio 429', { level: 'error', data: { pid: process.pid } });
 *
 *   await hops.lifecycle('send_reminders', async (life) => {
 *     life.setData({ count: batch.length });
 *     // …work…
 *   });
 *   // on resolve: emits send_reminders_succeeded
 *   // on reject:  emits send_reminders_failed and re-throws
 *
 * Env:
 *   INGEST_URL    e.g. http://elitedesk.tail266853.ts.net:64421/api/ingest
 *                 or http://192.168.1.75:64421/api/ingest on LAN
 *   INGEST_TOKEN  shared secret (same one the watchers use)
 *   HOME_OPS_HOST optional override for the host field; defaults to os.hostname()
 *
 * Failure mode: emit is best-effort. A failed POST writes to stderr and
 * resolves; the calling code never sees the error.
 */
import os from 'node:os';

let _slug = null;
let _url = '';
let _token = '';
let _host = '';

export function init(slug, { ingestUrl, ingestToken, host } = {}) {
  _slug = slug;
  _url = (ingestUrl || process.env.INGEST_URL || '').replace(/\/+$/, '');
  _token = ingestToken || process.env.INGEST_TOKEN || '';
  _host = host || process.env.HOME_OPS_HOST || os.hostname();
}

/**
 * Emit a single event. Returns the promise; awaiting is optional —
 * callers normally fire-and-forget.
 *
 * @param {string} message
 * @param {{ level?: 'debug'|'info'|'warn'|'error'|'fatal', data?: Record<string, unknown> }} [opts]
 * @returns {Promise<void>}
 */
export async function event(message, { level = 'info', data } = {}) {
  if (!_slug || !_url || !_token) return;
  const body = {
    host: _host,
    source: `app:${_slug}`,
    level,
    message: String(message).slice(0, 8000),
  };
  if (data) body.data = data;
  try {
    const r = await fetch(_url, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'X-Ingest-Token': _token },
      body: JSON.stringify({ events: [body] }),
      signal: AbortSignal.timeout(2000),
    });
    if (!r.ok) {
      process.stderr.write(`home-ops-log: non-2xx ${r.status}\n`);
    }
  } catch (e) {
    process.stderr.write(`home-ops-log: emit failed (${e?.name || 'Error'}): ${message.toString().slice(0, 80)}\n`);
  }
}

/**
 * Run `fn` between `<stage>_started` and `<stage>_succeeded`/`_failed` events.
 * Re-throws on rejection so the caller can still handle the error.
 *
 * @template T
 * @param {string} stage
 * @param {(life: { setData: (more: Record<string, unknown>) => void, durationMs: () => number }) => Promise<T>} fn
 * @param {Record<string, unknown>} [startData]
 * @returns {Promise<T>}
 */
export async function lifecycle(stage, fn, startData) {
  const data = { ...(startData || {}) };
  const startedAt = Date.now();
  const life = {
    setData: (more) => Object.assign(data, more),
    durationMs: () => Date.now() - startedAt,
  };
  event(`${stage}_started`, { data: Object.keys(data).length ? data : undefined });
  try {
    const result = await fn(life);
    event(`${stage}_succeeded`, { data: { ...data, duration_ms: life.durationMs() } });
    return result;
  } catch (err) {
    event(`${stage}_failed`, {
      level: 'error',
      data: { ...data, duration_ms: life.durationMs(), error: String(err?.message ?? err).slice(0, 500) },
    });
    throw err;
  }
}
