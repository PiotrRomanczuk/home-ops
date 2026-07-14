/* ============================================================
   shell.js — SKETCH: "Preact owns the shell".

   The endpoint of the migration. Preact owns chrome + <main> + footer
   and the router. app.js is still loaded, but ONLY for its helper
   library (h, getState/setState, TABS, icons, sparkline, DB, openCapture,
   the VIEWS registry, the keymap). Its render loop is dormant here:
   the four render() calls in app.js were changed to window.render(),
   which this file overrides.

   Two things this proves, because they're the only hard parts:
     1. Routing + chrome/footer as Preact components, re-rendering on
        hash changes via a useHashRoute() hook (no clear()-and-rebuild).
     2. The LEGACY BRIDGE — a not-yet-migrated tab (logs, chat, …) still
        rendered by its vanilla VIEWS[tab](state, el) function, mounted
        inside the Preact tree via a ref. This is what makes the
        migration incremental: migrate one tab at a time, the rest keep
        working untouched. `status` is already native Preact; everything
        else flows through the bridge.

   Load this INSTEAD of the vanilla boot by using index-shell.html.
   ============================================================ */

import { html, render as mount } from '/static/vendor/htm-preact-standalone.mjs';
import { useReducer, useEffect, useRef, useLayoutEffect } from '/static/vendor/htm-preact-standalone.mjs';
import { StatusView } from '/static/status-preact.js';

window.__SHELL = true;

/* ---------- routing: subscribe to hash, expose window.render as a bump ---------- */
let bump = () => {}; // reassigned by <Shell> on each render; window.render triggers it
window.render = () => bump();

function useHashRoute() {
  const [, force] = useReducer((x) => x + 1, 0);
  useEffect(() => {
    const on = () => force();
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return getState(); // app.js's global parser
}

/* ---------- chrome (top tab strip) — ported from app.js renderChrome ---------- */
function Chrome({ state }) {
  const counts = {
    chat: (window.Chat?.conversations || DB.CONVERSATIONS).filter((c) => c.status === 'running' || c.status === 'queued' || c.status === 'paused').length,
    projects: (window.Projects?.items || DB.PROJECTS).filter((p) => p.status === 'hot').length,
    logs: (window.Logs?.rows || DB.LOGS).filter((l) => LV_ORDER[l.level] >= 4).length,
    hosts: DB.HOSTS.filter((x) => x.hd !== 'good').length,
    evals: (window.Evals?.items || []).filter((t) => (t.stage === 'testing' || t.stage === 'active') && !t.has_files).length,
    board: (window.Board?.items || []).filter((t) => t.column_key === 'now' && !t.done).length,
  };
  return html`
    <header class="chrome">
      <div class="brand"><span class="dot"></span>home-ops<span class="ver">elitedesk</span></div>
      <nav class="tabs">
        ${TABS.map((t) => html`
          <button
            class=${'tab' + (state.tab === t.id ? ' on' : '')}
            title=${`${t.label}  (press ${t.key})`}
            onClick=${() => setState({ tab: t.id, conv: null, slug: null, eval: null })}>
            <span class="ico" dangerouslySetInnerHTML=${{ __html: t.ico() }}></span>
            <span class="label-hide">${t.label}</span>
            ${counts[t.id] ? html`<span class="ct num">${String(counts[t.id])}</span>` : null}
          </button>`)}
      </nav>
      <div class="right">
        <button class="chrome-btn" title="toggle absolute / relative time  (t)" onClick=${toggleTimeMode}>
          <span dangerouslySetInnerHTML=${{ __html: icon('<circle cx="8" cy="8" r="5.5"/><path d="M8 5v3l2 1.5"/>') }}></span>
          <span>${window.__abs ? 'abs' : 'rel'}</span>
        </button>
        <button class="chrome-btn" title="keyboard map"><kbd>?</kbd></button>
      </div>
    </header>`;
}

/* ---------- ambient footer — ported from app.js renderFooter ---------- */
function Footer() {
  const q = DB.HEALTH;
  const vram = DB.MODELS_LOADED.map((m) => m.name).join(', ');
  const totVram = DB.MODELS_LOADED.reduce((a, m) => a + m.vram, 0).toFixed(1);
  return html`
    <footer class="foot">
      ${DB.HOSTS.map((host) => html`
        <div class="seg" style="cursor:pointer" title=${`${host.id} · ${host.role} · up ${host.up} · last event ${host.lag}s ago`}
             onClick=${() => setState({ tab: 'hosts', focus: host.id })}>
          <span class=${'hd ' + lagClass(host.lag)}></span>
          <span class="hn">${host.id}</span>
          <span class="lag num">${host.lag + 's'}</span>
        </div>`)}
      <div class="seg" style="cursor:pointer" title="ingest health — probes /api/health"
           onClick=${() => setState({ tab: 'logs', source: 'app:home-ops' })}>
        <span class=${'hd ' + (q.ingest === 'ok' ? 'good' : 'stale')}></span>
        <span>ingest ${q.ingest}</span>
      </div>
      <div class="seg num" style="cursor:pointer" title="gpu_jobs queue" onClick=${() => setState({ tab: 'chat' })}>
        queue <b style=${{ color: q.q_running ? 'var(--s-running)' : 'var(--fg-muted)', fontWeight: 600 }}>${q.q_running + 'r'}</b>/<b style=${{ color: q.q_queued ? 'var(--s-queued)' : 'var(--fg-muted)', fontWeight: 600 }}>${q.q_queued + 'q'}</b>
      </div>
      <div class="seg vram" title="models resident in win10 VRAM">vram <b>${vram}</b><span class="faint"> ${totVram}GB</span></div>
      <div class="spacer"></div>
      <button class="foot-add" title="quick-capture → inbox.md  (press c)" onClick=${openCapture}>
        <span class="plus">+</span><span class="lbl" style="color:inherit">inbox</span>
      </button>
    </footer>`;
}

/* ---------- the legacy bridge: run a vanilla VIEWS[tab] inside Preact ---------- */
// Migrated tabs render as native Preact; everything else flows through here.
// The vanilla view appends its DOM into our ref'd div. window.render() (→ bump)
// re-renders the shell, which re-runs this effect, re-invoking the view with
// fresh singleton data — same update path the vanilla app had, now scoped.
const MIGRATED = { status: StatusView };

function LegacyTab({ tab, state }) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.replaceChildren();
    const view = window.VIEWS[tab];
    if (view) view(state, el);
    else el.append(Object.assign(document.createElement('div'), { className: 'empty', textContent: 'unknown tab: ' + tab }));
  }); // no deps: re-invoke on every shell render, mirroring the vanilla loop
  return html`<div ref=${ref} class="legacy-host"></div>`;
}

function Main({ state }) {
  const Native = MIGRATED[state.tab];
  return html`
    <main id="main">
      ${Native ? html`<${Native} />` : html`<${LegacyTab} tab=${state.tab} state=${state} />`}
    </main>`;
}

/* ---------- root ---------- */
function Shell() {
  const [, force] = useReducer((x) => x + 1, 0);
  bump = force; // window.render() → force a shell re-render
  const state = useHashRoute();
  return html`
    <${Chrome} state=${state} />
    <${Main} state=${state} />
    <${Footer} />`;
}

/* ---------- boot: mount after app.js has set default hash + defined helpers ---------- */
window.addEventListener('DOMContentLoaded', () => {
  mount(html`<${Shell} />`, document.getElementById('app'));
});
