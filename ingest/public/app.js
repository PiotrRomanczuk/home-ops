// home-ops viewer — polls /api/logs with the current filter state.
// Single file, no framework. Edit me directly.

const $ = (id) => document.getElementById(id);
const fmt = new Intl.DateTimeFormat([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

let latestId = 0;
let pollHandle = null;
let pending = false;
let knownHosts = new Set();
let knownSources = new Set();

function getSelectedValues(sel) {
  return Array.from(sel.selectedOptions).map(o => o.value).filter(Boolean);
}

function buildParams({ append }) {
  const p = new URLSearchParams();
  getSelectedValues($('host')).forEach(h => p.append('host', h));
  getSelectedValues($('source')).forEach(s => p.append('source', s));
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
  const safeMsg = escapeHtml(r.message);
  return `<tr class="row" data-id="${r.id}">` +
    `<td class="c-ts">${ts}</td>` +
    `<td class="c-host host">${escapeHtml(r.host)}</td>` +
    `<td class="c-source source">${escapeHtml(r.source)}</td>` +
    `<td class="c-level">${levelCell(r.level)}</td>` +
    `<td class="c-msg">${safeMsg}</td>` +
  `</tr>`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));
}

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
  refreshSelect($('host'), knownHosts);
  refreshSelect($('source'), knownSources);
}

function refreshSelect(sel, set) {
  const have = new Set(Array.from(sel.options).map(o => o.value));
  const selected = new Set(getSelectedValues(sel));
  const sorted = Array.from(set).sort();
  if (sorted.every(v => have.has(v)) && sorted.length === sel.options.length) return;
  sel.innerHTML = sorted.map(v => `<option value="${escapeHtml(v)}" ${selected.has(v) ? 'selected' : ''}>${escapeHtml(v)}</option>`).join('');
}

async function loadSources() {
  try {
    const r = await fetch('/api/sources');
    if (!r.ok) return;
    const json = await r.json();
    for (const h of json.hosts ?? []) {
      knownHosts.add(h.host);
      for (const s of h.sources ?? []) knownSources.add(s);
    }
    refreshSelectors();
  } catch {}
}

function applyTail() {
  if (pollHandle) { clearInterval(pollHandle); pollHandle = null; }
  if ($('tail').checked) pollHandle = setInterval(() => load({ append: true }), 2000);
}

function bind() {
  ['host','source','level_min','since_min'].forEach(id => $(id).addEventListener('change', () => { latestId = 0; load({ append: false }); }));
  let grepTimer;
  $('grep').addEventListener('input', () => { clearTimeout(grepTimer); grepTimer = setTimeout(() => { latestId = 0; load({ append: false }); }, 300); });
  $('refresh').addEventListener('click', () => { latestId = 0; load({ append: false }); });
  $('tail').addEventListener('change', applyTail);
  $('logout').addEventListener('click', async () => {
    await fetch('/api/auth/logout', { method: 'POST' });
    location.href = '/login';
  });

  $('rows').addEventListener('click', e => {
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
}

bind();
loadSources().then(() => load({ append: false })).then(applyTail);
