/* ============================================================
   status-preact.js — Preact + htm port of the Status tab.

   PROTOTYPE / A-B. Loaded as an ES module AFTER status.js, it takes
   over VIEWS.status but keeps the vanilla version reachable:

       #tab=status            → this Preact view
       #tab=status&legacy=1   → original vanilla status.js

   What this demonstrates vs the vanilla version:
     • The 15s refresh diffs ONLY the status subtree. The vanilla
       Status.load() calls the global window.render(), which tears
       down and rebuilds the ENTIRE app (chrome + footer + main)
       every tick. Here the interval lives in a useEffect and calls
       setSnap() — Preact patches just what changed.
     • Data + lifecycle are colocated in the component (useState +
       useEffect), not a global mutable singleton that pokes render().
     • No build step: preact+hooks+htm are vendored as one local file
       (vendor/htm-preact-standalone.mjs), same pattern as Sortable.
   ============================================================ */

import { html, render } from '/static/vendor/htm-preact-standalone.mjs';
import { useState, useEffect } from '/static/vendor/htm-preact-standalone.mjs';

const REFRESH_MS = 15_000;

/* ---------- pure helpers (ported from status-api.js, no `this`) ---------- */
function lagSec(snap, ts) {
  if (!ts) return null;
  const nowMs = snap?.now ? +new Date(snap.now) : Date.now();
  return Math.max(0, Math.round((nowMs - +new Date(ts)) / 1000));
}
function hostHealth(snap, row) {
  const m = lagSec(snap, row.last_metric_ts);
  if (m == null) return 'noagent';
  return m <= 90 ? 'good' : m <= 300 ? 'warn' : 'stale';
}
function alarmCount(snap) {
  const lv = snap?.levels_1h || {};
  return (lv.error || 0) + (lv.fatal || 0);
}
const fmtLag = (v) => (v == null ? 'never' : v < 90 ? v + 's' : v < 5400 ? Math.round(v / 60) + 'm' : Math.round(v / 3600) + 'h');

/* ---------- presentational components ---------- */
function Banner({ snap }) {
  const lv = snap.levels_1h || {};
  const alarms = alarmCount(snap);
  const deadHosts = (snap.hosts || []).filter((r) => hostHealth(snap, r) === 'stale');
  const bad = alarms > 0 || deadHosts.length > 0;
  const label = bad
    ? [alarms ? `${alarms} error${alarms > 1 ? 's' : ''} /1h` : null,
       deadHosts.length ? `${deadHosts.map((r) => r.host).join(', ')} silent` : null]
        .filter(Boolean).join(' · ')
    : 'all clear';
  const onClick = () => bad && setState({ tab: 'logs', level_min: 'error' });
  return html`
    <div class=${'st-banner ' + (bad ? 'bad' : 'ok')} onClick=${onClick}>
      <span class="st-big">${bad ? '▲ ' + label : '● ' + label}</span>
      <span class="st-sub num">warn ${lv.warn || 0} · err ${lv.error || 0} · fatal ${lv.fatal || 0} — last hour</span>
    </div>`;
}

function Bar({ label, pct, hot }) {
  if (pct == null) return null;
  return html`
    <div class="st-bar">
      <span class="st-bl">${label}</span>
      <span class="st-track"><i class=${hot ? 'hot' : ''} style=${{ width: Math.min(100, pct) + '%' }}></i></span>
      <span class="st-bv num">${Math.round(pct) + '%'}</span>
    </div>`;
}

function HostRow({ snap, row }) {
  const hd = hostHealth(snap, row);
  const evLag = lagSec(snap, row.last_event_ts);
  const mLag = lagSec(snap, row.last_metric_ts);
  return html`
    <div class="st-host" onClick=${() => setState({ tab: 'hosts', focus: row.host })}>
      <div class="st-host-hd">
        <span class=${'hd ' + hd}></span>
        <span class="st-hn">${row.host}</span>
        ${row.data && row.data.is_gaming
          ? html`<span class="st-gaming" title="a game is running — GPU jobs pause">🎮 ${row.data.game || 'gaming'}</span>`
          : null}
        <span class="grow"></span>
        <span class="st-lag num" title="last log event / last metric sample">ev ${fmtLag(evLag)} · m ${fmtLag(mLag)}</span>
      </div>
      <div class="st-bars">
        <${Bar} label="cpu" pct=${row.cpu_pct} hot=${row.cpu_pct > 80} />
        <${Bar} label="mem" pct=${row.mem_pct} hot=${row.mem_pct > 85} />
        <${Bar} label="disk" pct=${row.disk_pct} hot=${row.disk_pct > 75} />
        ${row.gpu_pct != null ? html`<${Bar} label="gpu" pct=${row.gpu_pct} hot=${row.gpu_pct > 85} />` : null}
      </div>
    </div>`;
}

function Queue({ snap }) {
  const q = snap.jobs || {};
  const order = ['running', 'queued', 'paused', 'cancelling', 'failed', 'done'];
  const chips = order.filter((k) => q[k]);
  return html`
    <div class="st-sec">
      <div class="st-sec-hd">queue</div>
      ${chips.length
        ? html`<div class="st-chips">${chips.map((k) => html`
            <span class=${'st-chip q-' + k}><b class="num">${String(q[k])}</b> ${k}</span>`)}</div>`
        : html`<div class="st-empty">queue empty</div>`}
    </div>`;
}

function Errors({ snap }) {
  const rows = snap.recent_errors || [];
  return html`
    <div class="st-sec">
      <div class="st-sec-hd">recent errors <span class="faint">24h</span></div>
      ${rows.length
        ? html`<div>${rows.map((l) => html`
            <div class="st-err" onClick=${() => setState({ tab: 'logs', level_min: 'error', host: l.host })}>
              <span class="st-et num">${relShort(l.ts)}</span>
              <span class="st-eh">${l.host}</span>
              <span class="st-em">${l.message}</span>
            </div>`)}</div>`
        : html`<div class="st-empty">✓ no errors in 24h</div>`}
    </div>`;
}

/* ---------- container: owns data + refresh lifecycle ---------- */
export function StatusView() {
  const [snap, setSnap] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const s = await window.api('GET', '/api/status');
        if (alive) { setSnap(s); setErr(null); }
      } catch (e) {
        if (alive) setErr(e.message);
      }
    };
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => { alive = false; clearInterval(timer); }; // real cleanup on unmount
  }, []);

  if (!snap) {
    return html`<div class="status-view"><div class="empty">${err ? '✕ ' + err : 'loading…'}</div></div>`;
  }

  return html`
    <div class="status-view">
      <${Banner} snap=${snap} />
      <div class="st-sec">
        <div class="st-sec-hd">hosts</div>
        ${(snap.hosts || []).map((row) => html`<${HostRow} snap=${snap} row=${row} />`)}
      </div>
      <${Queue} snap=${snap} />
      <${Errors} snap=${snap} />
      <div class="st-meta num">
        db ${snap.db_size || '—'} · refreshed ${new Date(snap.now).toTimeString().slice(0, 8)} · every 15s
      </div>
    </div>`;
}

/* ---------- register: swap into the existing router, keep legacy A/B ---------- */
// The vanilla router clears #app and hands us a fresh `main` on every global
// render(). Preact never sees the old container get detached, so its effect
// cleanup (clearInterval) wouldn't fire — the refresh timer would leak. Track
// the previous container and unmount it (render(null, ...)) before re-mounting.
let prevMain = null;
const legacyStatus = VIEWS.status;
VIEWS.status = function (st, main) {
  if (prevMain && prevMain !== main) render(null, prevMain); // unmount → runs cleanup
  prevMain = null;
  if (st.legacy) return legacyStatus(st, main); // #tab=status&legacy=1 → vanilla
  render(html`<${StatusView} />`, main);
  prevMain = main;
};
