/* ============================================================
   today-server.js — "Serwer teraz" card on Dziś: one line on what
   elitedesk is doing, and which units failed in the last 24 h.
   Loads its own data (GET /api/activity/now) on the Dziś poll.
   ============================================================ */

let tdSrvLoadedAt = 0;

/* A crash loop's repeat_count spans the whole loop, not just 24 h, so the
   card counts failing units, never summed failures. */
function tdSrvFailing(n) {
  if (!n) return 'nic nie pada';
  const few = n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14);
  return n === 1 ? '1 unit pada' : `${n} ${few ? 'unity padają' : 'unitów pada'}`;
}

function tdServer() {
  if (Date.now() - tdSrvLoadedAt > 55_000) {
    tdSrvLoadedAt = Date.now();
    Server.loadNow().then(() => { if (getState().tab === 'today') render(); });
  }
  const snap = Server.snapshot();
  const sum = Server.now?.summary_24h;
  const hl = ServerPure.headline(snap?.snapshot, Date.now());
  const failing = sum?.failing_units || [];
  return tdSection('Serwer teraz', failing.length,
    h('button', { class: 'td-srv-hl td-more', onclick: () => setState({ tab: 'server' }) },
      h('span', { class: 'srv-dot ' + hl.tone }),
      hl.project ? h('span', { class: 'srv-proj static' }, hl.project) : null,
      h('span', { class: 'srv-hl-t' }, hl.text)),
    sum ? h('div', { class: 'td-meta' }, `24 h: ${sum.runs} uruchomień · ${tdSrvFailing(failing.length)}`) : null,
    failing.length ? h('ul', { class: 'td-list' }, ...failing.slice(0, 4).map((u) => h('li', { class: 'td-prob bad' },
      h('button', { class: 'srv-unit link', onclick: () => setState({ tab: 'server', srvu: u, srvf: '1' }) }, ServerPure.unitShort(u)),
      ' — pada')))
      : sum ? h('div', { class: 'td-empty ok' }, 'Żaden timer nie padł w 24 h.') : null);
}
window.tdServer = tdServer;
