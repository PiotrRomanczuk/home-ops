// home-ops viewer — polls /api/logs with the current filter state.
// Single file, no framework. Edit me directly.

const $ = (id) => document.getElementById(id);
const fmt = new Intl.DateTimeFormat([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

let latestId = 0;
let pollHandle = null;
let pending = false;
const knownHosts = new Set();
const knownSources = new Set();
const sourcesByHost = new Map(); // host -> Set(sources)

function buildParams({ append }) {
  const p = new URLSearchParams();
  if ($('host').value)   p.append('host',   $('host').value);
  if ($('source').value) p.append('source', $('source').value);
  p.set('level_min', $('level_min').value);
  p.set('since_min', $('since_min').value);
  const g = $('grep').value.trim();
  if (g) p.set('grep', g);
  if (append && latestId > 0) p.set('after', String(latestId));
  p.set('limit', append ? '500' : '300');
  return p.toString();
}

function levelCell(level) {
  return `<span class="lvl ${level}">${level}</span>`;
}

function renderRow(r) {
  const ts = fmt.format(new Date(r.ts));
  return `<tr class="row" data-id="${r.id}">` +
    `<td class="c-ts">${ts}</td>` +
    `<td class="c-host host" data-filter="host" data-value="${escapeAttr(r.host)}">${escapeHtml(r.host)}</td>` +
    `<td class="c-source source" data-filter="source" data-value="${escapeAttr(r.source)}">${escapeHtml(r.source)}</td>` +
    `<td class="c-level">${levelCell(r.level)}</td>` +
    `<td class="c-msg">${escapeHtml(r.message)}</td>` +
  `</tr>`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));
}
function escapeAttr(s) { return escapeHtml(s); }

async function load({ append }) {
  if (pending) return;
  pending = true;
  $('status').textContent = append ? '↻ tailing' : '↻ loading';
  const params = buildParams({ append });
  try {
    const r = await fetch('/api/logs?' + params);
    if (r.status === 401) { location.href = '/login'; return; }
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const json = await r.json();
    applyRows(json.rows, { append });
    $('status').textContent = `${json.rows.length} ${append ? 'new' : 'rows'}`;
  } catch (e) {
    $('status').textContent = 'err: ' + e.message;
  } finally {
    pending = false;
  }
}

function applyRows(rows, { append }) {
  if (!rows.length && !append) {
    $('rows').innerHTML = `<tr><td colspan="5" style="padding:24px;text-align:center;color:var(--fg-2)">no rows</td></tr>`;
    return;
  }
  const tbody = $('rows');
  for (const r of rows) {
    knownHosts.add(r.host);
    knownSources.add(r.source);
    if (!sourcesByHost.has(r.host)) sourcesByHost.set(r.host, new Set());
    sourcesByHost.get(r.host).add(r.source);
    if (Number(r.id) > latestId) latestId = Number(r.id);
  }
  if (append) {
    const html = rows.slice().reverse().map(renderRow).join('');
    tbody.insertAdjacentHTML('afterbegin', html);
    // cap displayed rows so DOM doesn't blow up during long tails
    const max = 1500;
    while (tbody.children.length > max) tbody.removeChild(tbody.lastChild);
  } else {
    tbody.innerHTML = rows.map(renderRow).join('');
  }
  refreshSelectors();
}

function refreshSelectors() {
  refreshHostSelect();
  refreshSourceSelect();
}

function refreshHostSelect() {
  const sel = $('host');
  const current = sel.value;
  const sorted = Array.from(knownHosts).sort();
  sel.innerHTML =
    `<option value="">all hosts</option>` +
    sorted.map(v => `<option value="${escapeAttr(v)}"${v === current ? ' selected' : ''}>${escapeHtml(v)}</option>`).join('');
  sel.classList.toggle('active', !!current);
}

function refreshSourceSelect() {
  const sel = $('source');
  const current = sel.value;
  const host = $('host').value;
  const pool = host && sourcesByHost.has(host) ? sourcesByHost.get(host) : knownSources;
  const sorted = Array.from(pool).sort();
  sel.innerHTML =
    `<option value="">all sources${host ? ` (${sorted.length})` : ''}</option>` +
    sorted.map(v => `<option value="${escapeAttr(v)}"${v === current ? ' selected' : ''}>${escapeHtml(v)}</option>`).join('');
  // If the currently-selected source isn't visible under the new host scope, clear it.
  if (current && !sorted.includes(current)) sel.value = '';
  sel.classList.toggle('active', !!sel.value);
}

async function loadSources() {
  try {
    const r = await fetch('/api/sources');
    if (!r.ok) return;
    const json = await r.json();
    for (const h of json.hosts ?? []) {
      knownHosts.add(h.host);
      if (!sourcesByHost.has(h.host)) sourcesByHost.set(h.host, new Set());
      for (const s of h.sources ?? []) {
        knownSources.add(s);
        sourcesByHost.get(h.host).add(s);
      }
    }
    refreshSelectors();
  } catch {}
}

function applyTail() {
  if (pollHandle) { clearInterval(pollHandle); pollHandle = null; }
  if ($('tail').checked) pollHandle = setInterval(() => load({ append: true }), 2000);
}

// ── URL hash persistence ───────────────────────────────────────────────
// Filter state lives in `location.hash` so refresh preserves it and
// the user can share a deep-link.

function applyStateFromHash() {
  const params = new URLSearchParams(location.hash.slice(1));
  if (params.has('host'))      $('host').value = params.get('host');
  if (params.has('level_min')) $('level_min').value = params.get('level_min');
  if (params.has('since_min')) $('since_min').value = params.get('since_min');
  if (params.has('grep'))      $('grep').value = params.get('grep');
  if (params.has('tail'))      $('tail').checked = params.get('tail') !== '0';
  refreshSourceSelect();
  if (params.has('source'))    $('source').value = params.get('source');
  refreshHostSelect();
  refreshSourceSelect();
}

function syncStateToHash() {
  const p = new URLSearchParams();
  if ($('host').value)               p.set('host', $('host').value);
  if ($('source').value)             p.set('source', $('source').value);
  if ($('level_min').value !== 'info') p.set('level_min', $('level_min').value);
  if ($('since_min').value !== '60') p.set('since_min', $('since_min').value);
  const g = $('grep').value.trim();
  if (g) p.set('grep', g);
  if (!$('tail').checked) p.set('tail', '0');
  const s = p.toString();
  const cur = location.hash.slice(1);
  if (s !== cur) history.replaceState(null, '', s ? '#' + s : location.pathname);
}

function bind() {
  $('host').addEventListener('change', () => {
    refreshSourceSelect();
    latestId = 0;
    syncStateToHash();
    load({ append: false });
  });
  ['source','level_min','since_min'].forEach(id => $(id).addEventListener('change', () => {
    latestId = 0;
    syncStateToHash();
    refreshSelectors();
    load({ append: false });
  }));
  let grepTimer;
  $('grep').addEventListener('input', () => {
    clearTimeout(grepTimer);
    grepTimer = setTimeout(() => { latestId = 0; syncStateToHash(); load({ append: false }); }, 300);
  });
  $('refresh').addEventListener('click', () => { latestId = 0; load({ append: false }); });
  $('tail').addEventListener('change', () => { syncStateToHash(); applyTail(); });
  $('logout').addEventListener('click', async () => {
    await fetch('/api/auth/logout', { method: 'POST' });
    location.href = '/login';
  });

  // Click on a host or source cell → set as filter.
  $('rows').addEventListener('click', e => {
    const cell = e.target.closest('td[data-filter]');
    if (cell) {
      e.stopPropagation();
      const which = cell.dataset.filter;
      const value = cell.dataset.value;
      $(which).value = value;
      if (which === 'host') refreshSourceSelect();
      latestId = 0;
      syncStateToHash();
      load({ append: false });
      return;
    }
    const row = e.target.closest('tr.row');
    if (!row) return;
    const id = row.dataset.id;
    const next = row.nextElementSibling;
    if (next && next.classList.contains('detail') && next.dataset.parent === id) {
      next.remove(); row.classList.remove('expanded'); return;
    }
    fetch('/api/logs?after=0&limit=1&host=' + encodeURIComponent(row.cells[1].textContent) + '&source=' + encodeURIComponent(row.cells[2].textContent))
      .then(r => r.json()).then(j => {
        const found = j.rows.find(r => String(r.id) === id) ?? j.rows[0];
        const detail = document.createElement('tr');
        detail.className = 'detail';
        detail.dataset.parent = id;
        detail.innerHTML = `<td colspan="5"><pre>${escapeHtml(JSON.stringify(found?.data ?? {}, null, 2))}</pre></td>`;
        row.insertAdjacentElement('afterend', detail);
        row.classList.add('expanded');
      }).catch(() => {});
  });

  window.addEventListener('hashchange', () => { applyStateFromHash(); latestId = 0; load({ append: false }); applyTail(); });
}

bind();
loadSources().then(() => { applyStateFromHash(); load({ append: false }); }).then(applyTail);
