/* ============================================================
   logs.js — dense host_logs viewer. Restyled, not redesigned.
   Filter contract in URL: #host=…&level_min=…&grep=…&source=…&tail=1
   ============================================================ */

let LIVE = null; // live array reference for current render
let CURSOR = 0;

function jsonHL(obj) {
  const j = JSON.stringify(obj, null, 2);
  return j
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/"([^"]+)":/g, '<span class="json-k">"$1"</span>:')
    .replace(/: "([^"]*)"/g, ': <span class="json-s">"$1"</span>')
    .replace(/: (\d+\.?\d*)/g, ': <span class="json-n">$1</span>');
}

// Server-side filtering does the heavy lifting now; this is only used by the
// in-memory tail to drop rows that no longer match the current filter window.
function matchLog(l, st) {
  if (st.host && st.host !== 'all' && l.host !== st.host) return false;
  if (st.level_min && LV_ORDER[l.level] < LV_ORDER[st.level_min]) return false;
  if (st.source && l.source !== st.source) return false;
  if (st.grep) {
    const q = st.grep.toLowerCase();
    const hay = (l.msg + ' ' + l.source + ' ' + JSON.stringify(l.data)).toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

/* render a single <tr> (+ its expand row, returned as fragment) */
function logRowEls(l, idx, st, fresh) {
  const open = st.expand === String(idx);
  const tr = h('tr', { class: 'logrow' + (open ? ' open' : '') + (idx === CURSOR ? ' cursor' : '') + (fresh ? ' fresh' : ''), dataset: { idx },
    onclick: () => setState({ expand: open ? null : idx }) });

  const srcParts = l.source.split(':');
  const isApp = srcParts[0] === 'app';
  const srcEl = isApp
    ? h('span', { class: 'src-chip app', onclick: (e) => { e.stopPropagation(); setState({ tab: 'projects', slug: srcParts[1], host: null, level_min: null, grep: null, source: null, expand: null }); } }, l.source)
    : h('span', { class: 'src-chip' }, l.source);

  // message with pid correlation
  const msgTd = h('td', { class: 'c-msg' });
  msgTd.append(h('span', { class: 'caret' }, open ? '▶' : '▸'), l.msg);
  if (l.data && l.data.pid) {
    msgTd.append(h('span', { class: 'data-peek' },
      'pid:', h('span', { class: 'pid', onmouseenter: (e) => pidPop(e, l.data.pid), onmouseleave: hidePidPop, onclick: (e) => { e.stopPropagation(); setState({ grep: 'pid', tail: null }); } }, String(l.data.pid)),
      ...peekData(l.data)));
  } else if (l.data && Object.keys(l.data).length) {
    msgTd.append(h('span', { class: 'data-peek' }, ...peekData(l.data)));
  }

  tr.append(
    h('td', { class: 'c-ts num' }, window.__abs ? l.ts : relShort(l.ts)),
    h('td', { class: 'c-host' }, h('span', { class: 'host-tag' }, l.host)),
    h('td', { class: 'c-lvl' }, h('span', { class: 'lv ' + l.level }, l.level)),
    h('td', { class: 'c-src' }, srcEl),
    msgTd,
  );

  if (!open) return [tr];

  const meta = h('div', { class: 'json-meta' },
    h('span', {}, h('b', {}, 'ts '), window.__abs ? l.ts : (l.ts + ' · ' + relShort(l.ts))),
    h('span', {}, h('b', {}, 'host '), l.host),
    h('span', {}, h('b', {}, 'source '), l.source),
    h('span', {}, h('b', {}, 'level '), h('span', { class: 'lv ' + l.level }, l.level)),
  );
  const box = h('div', { class: 'json-box' }, meta,
    h('pre', { html: jsonHL({ msg: l.msg, ...l.data }) }),
    h('div', { class: 'json-actions' },
      h('button', { class: 'ja', onclick: (e) => { e.stopPropagation(); navigator.clipboard?.writeText(JSON.stringify(l)); } }, '⧉ copy json'),
      l.data.pid ? h('button', { class: 'ja', onclick: (e) => { e.stopPropagation(); setState({ grep: 'pid', expand: null }); } }, '▷ correlate pid=' + l.data.pid) : null,
      isApp ? h('button', { class: 'ja', onclick: (e) => { e.stopPropagation(); setState({ source: l.source, expand: null }); } }, '⊹ filter ' + l.source) : null,
    ));
  const jtr = h('tr', { class: 'json-row' }, h('td', { colspan: 5 }, box));
  return [tr, jtr];
}

function peekData(data) {
  const out = [];
  const keys = Object.keys(data).filter(k => k !== 'pid').slice(0, 3);
  keys.forEach((k, i) => { out.push((i ? ' ' : ' ') + k + '=' + JSON.stringify(data[k]).replace(/"/g, '')); });
  return out;
}

/* pid correlation popover — count within the loaded window. A full
   cross-window count would need a server endpoint; defer. */
let PID_POP = null;
function pidPop(e, pid) {
  hidePidPop();
  const count = (Logs.rows || []).filter(l => l.data && l.data.pid === pid).length;
  const r = e.target.getBoundingClientRect();
  PID_POP = h('div', { class: 'pid-pop', style: { left: r.left + 'px', top: (r.bottom + 5) + 'px' } },
    '▷ ', h('span', { class: 'corr', onclick: (ev) => { ev.stopPropagation(); setState({ grep: 'pid:' + pid, expand: null }); hidePidPop(); } }, count + ' loaded'), ' with pid=' + pid);
  document.body.append(PID_POP);
}
function hidePidPop() { if (PID_POP) { PID_POP.remove(); PID_POP = null; } }

/* ---------- saved deep-link chips ---------- */
const SAVED = [
  { id: 'warn1h', label: 'warn+ 1h', patch: { level_min: 'warn', host: null, grep: null, source: null }, color: 'var(--lv-warn)' },
  { id: 'win10err', label: 'win10 errors', patch: { level_min: 'error', host: 'win10', grep: null, source: null }, color: 'var(--lv-error)' },
  { id: 'twilio', label: 'twilio 429', patch: { grep: 'twilio', level_min: 'error', host: null, source: null }, color: 'var(--lv-error)' },
  { id: 'gpu', label: 'gpu sampler', patch: { grep: 'gpu', level_min: 'debug', host: 'win10', source: null }, color: 'var(--accent)' },
  { id: 'ssh', label: 'ssh auth', patch: { grep: 'ssh', level_min: 'info', host: null, source: null }, color: 'var(--good)' },
];

/* ---------- view ---------- */
VIEWS.logs = function (st, main) {
  Logs.stopTail();
  if (!Logs.hosts.length) Logs.loadSourcesOnce();
  const filterKey = Logs.filterKey(st);
  if (!Logs.loaded || Logs._key !== filterKey) Logs.loadFor(st);
  const levelMin = st.level_min || 'debug';
  const host = st.host || 'all';
  const tail = st.tail === '1';

  const wrap = h('div', { class: 'logs-view' });

  // filter bar
  const searchInput = h('input', { id: 'logSearch', placeholder: 'grep message, source, data…', value: st.grep || '',
    oninput: (e) => { clearTimeout(searchInput._t); searchInput._t = setTimeout(() => setState({ grep: e.target.value || null, expand: null }, true), 160); } });
  const lvStrip = h('div', { class: 'lv-strip' }, ...DB.LEVELS.map((lv, i) =>
    h('button', { class: (levelMin === lv ? 'on ' + lv : ''), title: 'level_min = ' + lv + '  (' + (i + 1) + ')', onclick: () => setState({ level_min: lv === 'debug' ? null : lv, expand: null }) }, lv)));
  const hostIds = Logs.hosts.length ? Logs.hosts.map(h => h.host) : DB.HOSTS.map(h => h.id);
  const hostSel = h('div', { class: 'host-sel' },
    h('button', { class: host === 'all' ? 'on' : '', onclick: () => setState({ host: null, expand: null }) }, 'all'),
    ...hostIds.map(id => h('button', { class: host === id ? 'on' : '', onclick: () => setState({ host: id, expand: null }) }, id)));
  const tailBtn = h('button', { class: 'tail-btn' + (tail ? ' on' : ''), title: 'live tail  (f)', onclick: () => setState({ tail: tail ? null : '1' }) },
    h('span', { class: 'tld' }), tail ? 'tailing' : 'paused');

  const filterBar = h('div', { class: 'filter-bar' },
    h('div', { class: 'search' }, h('span', { class: 'sk' }, '/'), searchInput, st.grep ? h('button', { class: 'sk', onclick: () => setState({ grep: null }), title: 'clear' }, '✕') : null),
    lvStrip, hostSel, tailBtn,
    st.source ? h('button', { class: 'saved-chip on', onclick: () => setState({ source: null }) }, h('span', { class: 'sd', style: { background: 'var(--accent)' } }), st.source, ' ✕') : null,
    h('span', { class: 'grow', style: { flex: 1 } }),
    h('span', { class: 'filter-stat', id: 'logCount' }),
  );
  wrap.append(filterBar);

  // saved deep-link chips
  wrap.append(h('div', { class: 'saved-row' },
    h('span', { class: 'lbl', style: { fontSize: '9.5px' } }, 'saved'),
    ...SAVED.map(s => h('button', { class: 'saved-chip', onclick: () => setState({ ...s.patch, expand: null }) },
      h('span', { class: 'sd', style: { background: s.color } }), s.label)),
    h('button', { class: 'saved-chip', style: { color: 'var(--fg-faint)' }, onclick: () => openCapture(), title: 'save current filter' }, '+ save'),
  ));

  // table
  const scroll = h('div', { class: 'log-scroll' });
  const table = h('table', { class: 'log-table' },
    h('thead', {}, h('tr', {},
      h('th', { class: 'c-ts' }, window.__abs ? 'time' : 'age'),
      h('th', { class: 'c-host' }, 'host'),
      h('th', { class: 'c-lvl' }, 'lvl'),
      h('th', { class: 'c-src' }, 'source'),
      h('th', { class: 'c-msg' }, 'message'))));
  const tbody = h('tbody', { id: 'logBody' });
  table.append(tbody);
  scroll.append(table);
  wrap.append(scroll);
  main.append(wrap);

  // populate — Logs.rows is already server-filtered for this state.
  LIVE = Logs.rows;
  if (CURSOR >= LIVE.length) CURSOR = 0;
  paintLogs(tbody, st);

  if (tail) Logs.startTail(st);
  updateCount();
};

function paintLogs(tbody, st) {
  clear(tbody);
  if (!LIVE.length) {
    const msg = Logs.loading ? 'loading…' : Logs.err ? '✕ ' + Logs.err : 'no rows match';
    const hint = Logs.loading ? '' : Logs.err ? 'check ingest API health' : 'adjust level / host / grep';
    tbody.append(h('tr', {}, h('td', { colspan: 5 }, h('div', { class: 'empty', style: { height: '160px' } }, h('div', { class: 'big' }, msg), hint))));
    return;
  }
  const frag = document.createDocumentFragment();
  LIVE.slice(0, 200).forEach((l, i) => logRowEls(l, i, st).forEach(n => frag.append(n)));
  tbody.append(frag);
}
function updateCount() {
  const el = $('#logCount'); if (!el) return;
  el.innerHTML = `<b>${LIVE.length}</b> loaded${Logs.loading ? ' · …' : ''}`;
}

/* logs keymap: / focus search, f tail, 1-5 level, j/k cursor, Enter expand */
window.VIEW_KEYS = window.VIEW_KEYS || {};
window.VIEW_KEYS.logs = (e, st) => {
  if (e.key === '/') { e.preventDefault(); $('#logSearch')?.focus(); }
  else if (e.key === 'f') { setState({ tail: st.tail === '1' ? null : '1' }); }
  else if (e.key === 'j' || e.key === 'k') {
    e.preventDefault();
    CURSOR = Math.max(0, Math.min((LIVE?.length || 1) - 1, CURSOR + (e.key === 'j' ? 1 : -1)));
    $$('.logrow').forEach(r => r.classList.toggle('cursor', +r.dataset.idx === CURSOR));
    const cur = $$('.logrow').find(r => +r.dataset.idx === CURSOR);
    const sc = $('.log-scroll');
    if (cur && sc) {
      const ct = cur.offsetTop, ch = cur.offsetHeight;
      if (ct < sc.scrollTop + 40) sc.scrollTop = ct - 40;
      else if (ct + ch > sc.scrollTop + sc.clientHeight - 20) sc.scrollTop = ct + ch - sc.clientHeight + 20;
    }
  } else if (e.key === 'Enter') { setState({ expand: st.expand === String(CURSOR) ? null : CURSOR }); }
};
