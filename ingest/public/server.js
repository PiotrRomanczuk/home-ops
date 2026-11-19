/* ============================================================
   server.js — "Serwer" tab: what elitedesk is doing right now
   (who burns the CPU, which runner/timer is running, what fires
   next), what keeps failing, and every run with its log
   (server-runs.js). Data: server-api.js ← activity-watcher.
   ============================================================ */

const SRV_TIME = new Intl.DateTimeFormat('pl-PL', { hour: '2-digit', minute: '2-digit' });
const SRV_RANGES = [[24, '24 h'], [168, '7 dni']];

function srvSec(title, extra, ...body) {
  return h('section', { class: 'srv-sec' }, h('h2', { class: 'srv-h' }, title, extra || null), ...body);
}

function srvIn(sec) {
  if (sec < 60) return 'za chwilę';
  const m = Math.round(sec / 60);
  return m < 60 ? `za ${m} min` : `za ${Math.floor(m / 60)} h ${m % 60} min`;
}

function srvProj(slug) {
  return slug ? h('button', { class: 'srv-proj', title: 'pokaż tylko ten projekt',
    onclick: () => setState({ srvp: slug, srvu: null }, true) }, slug) : null;
}

function srvNow(snap) {
  const s = snap?.snapshot;
  const hl = ServerPure.headline(s, Date.now());
  const age = snap ? Math.round((Date.now() - Date.parse(snap.ts)) / 1000) : null;
  const stale = age != null && age > 120;
  const owners = s?.owners || [];
  const max = Math.max(...owners.map((o) => o.pct), 1);
  return h('section', { class: 'srv-now ' + hl.tone },
    h('div', { class: 'srv-hl' },
      h('span', { class: 'srv-dot ' + hl.tone }),
      h('span', { class: 'srv-hl-lbl' }, 'Teraz'),
      hl.project ? h('span', { class: 'srv-proj static' }, hl.project) : null,
      h('span', { class: 'srv-hl-t' }, hl.text),
      hl.url ? h('a', { class: 'srv-link', href: hl.url, target: '_blank', rel: 'noopener' }, 'GitHub ↗') : null),
    s ? h('div', { class: 'srv-stats num' },
      h('span', {}, `CPU ${s.cpu_pct ?? '—'} %`),
      h('span', {}, `load ${s.load_1 ?? '—'} / ${s.ncpu} rdz.`),
      ...(s.runners || []).map((r) => h('span', { class: 'srv-runner' + (r.busy ? ' busy' : '') }, `${r.name}: ${r.busy ? 'pracuje' : 'wolny'}`)),
      h('span', { class: 'srv-age' + (stale ? ' stale' : '') }, stale ? `migawka sprzed ${Math.round(age / 60)} min — agent milczy?` : `migawka ${age} s temu`)) : null,
    owners.length ? h('ul', { class: 'srv-owners' }, ...owners.map((o) => h('li', {},
      h('span', { class: 'srv-own-n', title: o.owner }, o.owner, o.project ? h('span', { class: 'srv-own-p' }, ` · ${o.project}`) : null),
      h('span', { class: 'srv-bar' }, h('i', { style: { width: `${(o.pct / max) * 100}%` } })),
      h('span', { class: 'srv-own-v num' }, `${o.pct} %`)))) : null);
}

function srvNext(snap) {
  const timers = snap?.snapshot?.next_timers || [];
  const now = Date.now() / 1000;
  return srvSec('Następne', null, timers.length
    ? h('ul', { class: 'srv-list' }, ...timers.map((t) => h('li', { class: 'srv-next' },
      h('span', { class: 'srv-when num', title: SRV_TIME.format(new Date(t.next_at * 1000)) }, srvIn(t.next_at - now)),
      h('span', { class: 'srv-unit' }, ServerPure.unitShort(t.unit)), srvProj(t.project))))
    : h('div', { class: 'srv-empty' }, 'Brak zaplanowanych timerów w migawce.'));
}

function srvFailing(runs, rangeLbl) {
  const fails = ServerPure.failing(runs);
  return srvSec('Pada', h('span', { class: 'srv-ct' + (fails.length ? ' bad' : '') }, String(fails.length)), fails.length
    ? h('ul', { class: 'srv-list' }, ...fails.map((f) => h('li', { class: 'srv-fail' },
      h('button', { class: 'srv-unit link', title: 'pokaż tylko ten unit', onclick: () => setState({ srvu: f.unit, srvf: '1', srvp: null }, true) },
        ServerPure.unitShort(f.unit)),
      h('span', { class: 'srv-x num' }, `×${f.n}`, f.total > f.n ? h('span', { class: 'srv-of' }, ` / ${f.total}`) : null),
      srvProj(f.project),
      h('span', { class: 'srv-why' }, [f.last.detail, f.last.exit_code != null ? `exit ${f.last.exit_code}` : null].filter(Boolean).join(' · ')))))
    : h('div', { class: 'srv-empty ok' }, `Nic nie padło (${rangeLbl}).`));
}

VIEWS.server = (st, main) => {
  if (!Server.loaded && !Server.loading) Server.load();
  Server.startPolling();
  const rangeLbl = (SRV_RANGES.find(([v]) => v === Server.rangeH) || SRV_RANGES[0])[1];
  const head = h('div', { class: 'srv-top' },
    h('span', { class: 'srv-title' }, 'Serwer'), h('span', { class: 'srv-host' }, 'elitedesk'),
    h('span', { class: 'spacer' }),
    h('span', { class: 'srv-seg' }, ...SRV_RANGES.map(([v, lbl]) => h('button', {
      class: Server.rangeH === v ? 'on' : '', onclick: () => Server.setRange(v) }, lbl))),
    Server.err ? h('span', { class: 'srv-err' }, Server.err) : null,
    Server.fetchedAt ? h('span', { class: 'srv-meta' }, `odświeżono ${SRV_TIME.format(Server.fetchedAt)} · co 15 s`) : null,
    h('button', { class: 'srv-refresh', title: 'odśwież', onclick: () => Server.load() }, '↻'));
  if (!Server.loaded) {
    main.append(h('div', { class: 'srv-view' }, head, h('div', { class: 'empty' }, Server.err ? 'nie udało się pobrać' : 'ładowanie…')));
    return;
  }
  const snap = Server.snapshot();
  main.append(h('div', { class: 'srv-view' }, head,
    h('div', { class: 'srv-body' },
      srvNow(snap),
      h('div', { class: 'srv-grid' },
        h('div', { class: 'srv-col' }, srvFailing(Server.runs, rangeLbl), srvNext(snap)),
        h('div', { class: 'srv-col wide' }, window.srvTimeline(Server.runs, Server.rangeH), window.srvRuns(Server.runs, st))))));
};
