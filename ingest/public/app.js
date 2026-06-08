/* ============================================================
   app.js — shell, router, chrome, ambient footer, quick-capture.
   State lives in the URL fragment: #tab=chat&conv=47 …
   ============================================================ */

/* ---------- hyperscript ---------- */
function h(tag, props, ...kids) {
  const e = document.createElement(tag);
  if (props) for (const k in props) {
    const v = props[k];
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'html') e.innerHTML = v;
    else if (k === 'dataset') Object.assign(e.dataset, v);
    else if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);
    else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k in e && k !== 'list') { try { e[k] = v; } catch { e.setAttribute(k, v); } }
    else e.setAttribute(k, v);
  }
  for (const kid of kids.flat(3)) {
    if (kid == null || kid === false) continue;
    e.append(kid.nodeType ? kid : document.createTextNode(kid));
  }
  return e;
}
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const clear = (e) => { while (e.firstChild) e.removeChild(e.firstChild); return e; };

/* ---------- hash state ---------- */
function getState() {
  const s = {};
  const raw = location.hash.replace(/^#/, '');
  for (const pair of raw.split('&')) {
    if (!pair) continue;
    const i = pair.indexOf('=');
    if (i < 0) { s[pair] = true; continue; }
    s[decodeURIComponent(pair.slice(0, i))] = decodeURIComponent(pair.slice(i + 1));
  }
  if (!s.tab) s.tab = 'chat';
  return s;
}
function setState(patch, replace) {
  const s = { ...getState(), ...patch };
  for (const k in s) if (s[k] === null || s[k] === undefined || s[k] === '') delete s[k];
  const str = Object.entries(s).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');
  if (replace) history.replaceState(null, '', '#' + str);
  else location.hash = str;
  if (replace) render();
}
window.setState = setState; window.getState = getState;

/* ---------- time helpers ---------- */
function parseTs(t) {
  if (t instanceof Date) return t;
  if (/^\d{2}:\d{2}:\d{2}$/.test(t)) return new Date('2026-06-08T' + t);
  return new Date(t);
}
function rel(t) {
  const d = parseTs(t), s = Math.round((DB.NOW - d) / 1000);
  if (s < 0) return 'now';
  if (s < 60) return s + 's ago';
  const m = Math.round(s / 60); if (m < 60) return m + 'm ago';
  const hr = Math.round(m / 60); if (hr < 24) return hr + 'h ago';
  return Math.round(hr / 24) + 'd ago';
}
function relShort(t) {
  const d = parseTs(t), s = Math.round((DB.NOW - d) / 1000);
  if (s < 60) return s + 's';
  const m = Math.round(s / 60); if (m < 60) return m + 'm';
  const hr = Math.round(m / 60); if (hr < 24) return hr + 'h';
  return Math.round(hr / 24) + 'd';
}
function abs(t) { const d = parseTs(t); return d.toTimeString().slice(0, 8); }
function lagClass(sec) { return sec <= 30 ? 'good' : sec <= 120 ? 'warn' : 'stale'; }
window.rel = rel; window.relShort = relShort; window.abs = abs; window.parseTs = parseTs;

/* ---------- sparkline ---------- */
function sparkline(vals, opts = {}) {
  const w = opts.w || 120, ht = opts.h || 26, pad = 1;
  const max = opts.max ?? Math.max(...vals, 1), min = opts.min ?? 0;
  const n = vals.length;
  const x = i => pad + (i / (n - 1)) * (w - pad * 2);
  const y = v => ht - pad - ((v - min) / (max - min || 1)) * (ht - pad * 2);
  const pts = vals.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const area = `${pad},${ht - pad} ${pts} ${w - pad},${ht - pad}`;
  const col = opts.color || 'var(--accent)';
  const id = 'sg' + Math.random().toString(36).slice(2, 7);
  return `<svg class="spark" viewBox="0 0 ${w} ${ht}" width="${w}" height="${ht}" preserveAspectRatio="none">
    <defs><linearGradient id="${id}" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0" stop-color="${col}" stop-opacity="0.22"/>
      <stop offset="1" stop-color="${col}" stop-opacity="0"/></linearGradient></defs>
    <polygon points="${area}" fill="url(#${id})"/>
    <polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.2" stroke-linejoin="round"/>
    <circle cx="${x(n - 1)}" cy="${y(vals[n - 1])}" r="1.6" fill="${col}"/>
  </svg>`;
}
window.sparkline = sparkline;

/* mini commit-pulse bars for project cards */
function pulseBars(vals, color) {
  const max = Math.max(...vals, 1);
  return `<span class="pulse">${vals.map(v =>
    `<i style="height:${Math.max(8, (v / max) * 100)}%;background:${v === 0 ? 'var(--border)' : (color || 'var(--accent)')}"></i>`).join('')}</span>`;
}
window.pulseBars = pulseBars;

/* level ordering for filters */
const LV_ORDER = { debug: 1, info: 2, warn: 3, error: 4, fatal: 5 };
window.LV_ORDER = LV_ORDER;

/* ============================================================
   CHROME (top tab strip)
   ============================================================ */
const TABS = [
  { id: 'chat',     label: 'Chat',     key: '1', ico: icoChat },
  { id: 'projects', label: 'Projects', key: '2', ico: icoProj },
  { id: 'logs',     label: 'Logs',     key: '3', ico: icoLogs },
  { id: 'hosts',    label: 'Hosts',    key: '4', ico: icoHosts },
];
function icon(p) { return `<svg class="ico" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`; }
function icoChat()  { return icon('<path d="M2.5 3.5h11v7h-6l-3 2.5v-2.5h-2z"/>'); }
function icoProj()  { return icon('<rect x="2.5" y="2.5" width="4.5" height="4.5"/><rect x="9" y="2.5" width="4.5" height="4.5"/><rect x="2.5" y="9" width="4.5" height="4.5"/><rect x="9" y="9" width="4.5" height="4.5"/>'); }
function icoLogs()  { return icon('<path d="M3 4h10M3 7h10M3 10h7M3 13h4"/>'); }
function icoHosts() { return icon('<rect x="2.5" y="3" width="11" height="3.2"/><rect x="2.5" y="8.5" width="11" height="3.2"/><circle cx="5" cy="4.6" r="0.4" fill="currentColor"/><circle cx="5" cy="10.1" r="0.4" fill="currentColor"/>'); }

function renderChrome() {
  const st = getState();
  const counts = {
    chat: DB.CONVERSATIONS.filter(c => c.status === 'running' || c.status === 'queued' || c.status === 'paused').length,
    projects: DB.PROJECTS.filter(p => p.status === 'hot').length,
    logs: DB.LOGS.filter(l => LV_ORDER[l.level] >= 4).length,
    hosts: DB.HOSTS.filter(x => x.hd !== 'good').length,
  };
  const tabs = TABS.map(t => h('button', {
    class: 'tab' + (st.tab === t.id ? ' on' : ''),
    onclick: () => setState({ tab: t.id, conv: null, slug: null }),
    title: `${t.label}  (press ${t.key})`,
  },
    h('span', { class: 'ico', html: t.ico() }),
    t.label,
    counts[t.id] ? h('span', { class: 'ct num' }, String(counts[t.id])) : null,
  ));

  return h('header', { class: 'chrome' },
    h('div', { class: 'brand' },
      h('span', { class: 'dot' }),
      'home-ops',
      h('span', { class: 'ver' }, 'uwh'),
    ),
    h('nav', { class: 'tabs' }, ...tabs),
    h('div', { class: 'right' },
      h('button', { class: 'chrome-btn', title: 'toggle absolute / relative time  (t)', onclick: toggleTimeMode },
        h('span', { html: icon('<circle cx="8" cy="8" r="5.5"/><path d="M8 5v3l2 1.5"/>') }),
        h('span', { id: 'timeModeLbl' }, window.__abs ? 'abs' : 'rel')),
      h('button', { class: 'chrome-btn', title: 'keyboard map' },
        h('kbd', {}, '?')),
    ),
  );
}
function toggleTimeMode() { window.__abs = !window.__abs; render(); }

/* ============================================================
   AMBIENT FOOTER
   ============================================================ */
function renderFooter() {
  const segs = DB.HOSTS.map(host => h('div', {
    class: 'seg', title: `${host.id} · ${host.role} · up ${host.up} · last event ${host.lag}s ago`,
    onclick: () => setState({ tab: 'hosts', focus: host.id }),
    style: { cursor: 'pointer' },
  },
    h('span', { class: 'hd ' + lagClass(host.lag) }),
    h('span', { class: 'hn' }, host.id),
    h('span', { class: 'lag num' }, host.lag + 's'),
  ));

  const q = DB.HEALTH;
  const vram = DB.MODELS_LOADED.map(m => m.name).join(', ');
  const totVram = DB.MODELS_LOADED.reduce((a, m) => a + m.vram, 0).toFixed(1);

  return h('footer', { class: 'foot' },
    ...segs,
    h('div', { class: 'seg', title: 'ingest health — probes /api/health', onclick: () => setState({ tab: 'logs', source: 'app:home-ops' }), style: { cursor: 'pointer' } },
      h('span', { class: 'hd ' + (q.ingest === 'ok' ? 'good' : 'stale') }),
      h('span', {}, 'ingest ' + q.ingest)),
    h('div', { class: 'seg num', title: 'gpu_jobs queue', onclick: () => setState({ tab: 'chat' }), style: { cursor: 'pointer' } },
      'queue ', h('b', { style: { color: q.q_running ? 'var(--s-running)' : 'var(--fg-muted)', fontWeight: 600 } }, q.q_running + 'r'),
      '/', h('b', { style: { color: q.q_queued ? 'var(--s-queued)' : 'var(--fg-muted)', fontWeight: 600 } }, q.q_queued + 'q')),
    h('div', { class: 'seg vram', title: 'models resident in wfh VRAM' },
      'vram ', h('b', {}, vram), h('span', { class: 'faint' }, ' ' + totVram + 'GB')),
    h('div', { class: 'spacer' }),
    h('button', { class: 'foot-add', title: 'quick-capture → inbox.md  (press c)', onclick: openCapture },
      h('span', { class: 'plus' }, '+'), h('span', { class: 'lbl', style: { color: 'inherit' } }, 'inbox')),
  );
}

/* ---------- quick-capture (one field, posts to inbox.md) ---------- */
function openCapture() {
  if ($('#capture')) return;
  const input = h('input', { class: 'cap-in foc', placeholder: 'note → inbox.md … (e.g. look into wfh OllamaWatcher silence)', autofocus: true });
  const wrap = h('div', { id: 'capture', class: 'cap-wrap' },
    h('form', { class: 'cap-form', onsubmit: (e) => { e.preventDefault(); submitCapture(input.value); } },
      h('span', { class: 'cap-pre' }, '+'),
      input,
      h('span', { class: 'cap-hint' }, h('kbd', {}, '↵'), ' send · ', h('kbd', {}, 'esc'), ' close'),
    ),
  );
  document.body.append(wrap);
  requestAnimationFrame(() => input.focus());
  const esc = (e) => { if (e.key === 'Escape') { wrap.remove(); document.removeEventListener('keydown', esc); } };
  document.addEventListener('keydown', esc);
  wrap.addEventListener('click', (e) => { if (e.target === wrap) wrap.remove(); });
}
function submitCapture(text) {
  if (!text.trim()) return;
  const w = $('#capture');
  const form = $('.cap-form', w);
  clear(form).append(h('span', { class: 'cap-ok' }, '✓ appended to inbox.md'));
  setTimeout(() => w.remove(), 850);
}

/* ============================================================
   ROUTER
   ============================================================ */
const VIEWS = {}; // tab id -> render(state, mountEl)
window.VIEWS = VIEWS;

function render() {
  const st = getState();
  const app = $('#app');
  clear(app);
  app.append(renderChrome());
  const main = h('main', { id: 'main' });
  app.append(main);
  app.append(renderFooter());
  const view = VIEWS[st.tab];
  if (view) view(st, main);
  else main.append(h('div', { class: 'empty' }, 'unknown tab: ' + st.tab));
  $('#timeModeLbl') && ($('#timeModeLbl').textContent = window.__abs ? 'abs' : 'rel');
}
window.render = render;

window.addEventListener('hashchange', render);

/* ---------- global keymap ---------- */
document.addEventListener('keydown', (e) => {
  const typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName) || document.activeElement?.isContentEditable;
  if (typing) return;
  const st = getState();
  if (e.key >= '1' && e.key <= '4' && !e.metaKey && !e.ctrlKey) {
    const t = TABS[+e.key - 1]; if (t) { setState({ tab: t.id, conv: null, slug: null }); e.preventDefault(); }
  } else if (e.key === 'c') { openCapture(); e.preventDefault(); }
  else if (e.key === 't') { toggleTimeMode(); }
  else if (e.key === 'Escape' && (st.conv || st.slug)) { setState({ conv: null, slug: null }); }
  else if (window.VIEW_KEYS && window.VIEW_KEYS[st.tab]) window.VIEW_KEYS[st.tab](e, st);
});

/* boot */
window.addEventListener('DOMContentLoaded', () => {
  if (!location.hash) history.replaceState(null, '', '#tab=chat');
  render();
});
