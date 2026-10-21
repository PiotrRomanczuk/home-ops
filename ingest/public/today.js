/* ============================================================
   today.js — "Dziś" tab, the console's default view.
   Left: the latest day brief (cloud routine → daily-brief repo →
   brief-pull → /api/briefs). Right: the agent queue card (today-queue.js), open Now tasks per project,
   what is broken, what waits for an answer, fresh routine cards.
   ============================================================ */

const TD_SLOT = { morning: 'poranny', evening: 'wieczorny' };
const TD_DAY = new Intl.DateTimeFormat('pl-PL', { weekday: 'long', day: 'numeric', month: 'long' });
const TD_TIME = new Intl.DateTimeFormat('pl-PL', { hour: '2-digit', minute: '2-digit' });

const tdCap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

function tdSection(title, count, ...body) {
  return h('section', { class: 'td-sec' },
    h('h2', { class: 'td-h' }, title, count ? h('span', { class: 'td-ct num' }, String(count)) : null),
    ...body);
}

/* tdBrief lives in today-brief.js (folded sections). */

/* One line per task (title from the API, full text on hover), three per
   project; "+N" unfolds the rest until the next reload. */
const TD_PER_PROJECT = 3;
const TD_EXPANDED = new Set();

function tdTaskRow(t) {
  return h('li', { class: 'td-task' + (t.is_focus ? ' focus' : ''), title: t.text },
    t.is_focus ? h('span', { class: 'td-focus' }, 'fokus') : null,
    h('span', { class: 'td-task-t' }, t.title || t.text));
}

function tdTasks(groups) {
  const n = groups.reduce((a, g) => a + g.tasks.length, 0);
  if (!groups.length) return tdSection('Zadania Now', 0, h('div', { class: 'td-empty' }, 'Brak otwartych zadań w Now.'));
  return tdSection('Zadania Now', n, ...groups.map((g) => {
    const open = TD_EXPANDED.has(g.slug);
    const shown = open ? g.tasks : g.tasks.slice(0, TD_PER_PROJECT);
    const rest = g.tasks.length - shown.length;
    return h('div', { class: 'td-proj' },
      h('button', { class: 'td-proj-h', onclick: () => setState({ tab: 'projects', slug: g.slug }) },
        h('span', { class: 'td-dot ' + (g.status || '') }), g.title, h('span', { class: 'td-proj-n num' }, String(g.tasks.length))),
      h('ul', { class: 'td-list' }, ...shown.map(tdTaskRow),
        rest > 0 ? h('li', {}, h('button', { class: 'td-more', onclick: () => { TD_EXPANDED.add(g.slug); render(); } }, `+${rest} więcej`)) : null,
        open && g.tasks.length > TD_PER_PROJECT ? h('li', {}, h('button', { class: 'td-more', onclick: () => { TD_EXPANDED.delete(g.slug); render(); } }, 'zwiń')) : null));
  }));
}

/* A host is `off` when it sent logs but no metrics in 7 days (its watcher is
   down or never deployed). It counts as a problem: the server everything runs
   on must not be able to vanish from this list by going quiet. */
function tdHostRow(x) {
  const why = x.status === 'bad' ? 'milczy (brak świeżych metryk)'
    : x.status === 'warn' ? `dysk ${x.disk_pct}%`
    : `loguje, ale nie wysyła metryk${x.last_event_ts ? ` · ostatni log ${TD_TIME.format(new Date(x.last_event_ts))}` : ''}`;
  return h('li', { class: 'td-prob ' + x.status }, h('b', {}, x.host), ` — ${why}`);
}

function tdProblems(problems, hosts, muted) {
  const bad = hosts.filter((x) => x.status === 'warn' || x.status === 'bad' || x.status === 'off');
  const rows = [
    ...bad.map(tdHostRow),
    ...problems.map((p) => h('li', { class: 'td-prob bad', title: p.sample || '' },
      h('b', {}, `${p.source}@${p.host}`), ` — ${p.n_24h}× w 24 h · `,
      h('span', { class: 'td-sample' }, (p.sample || p.pattern || '').slice(0, 140)))),
  ];
  return tdSection('Problemy', rows.length,
    rows.length ? h('ul', { class: 'td-list' }, ...rows) : h('div', { class: 'td-empty ok' }, 'Wszystko spokojnie.'),
    muted ? h('div', { class: 'td-meta' }, `wyciszone wzorce: ${muted} (lista w MUTED, digest.ts)`) : null);
}

function tdCards(cards) {
  if (!cards.length) return null;
  return tdSection('Rutyny', 0, h('ul', { class: 'td-list' }, ...cards.map((c) =>
    h('li', { class: 'td-card ' + c.status }, h('b', {}, c.routine), ` — ${c.headline}`))));
}

VIEWS.today = (st, main) => {
  if (!Today.loaded && !Today.loading) Today.load();
  Today.startPolling();
  const m = Today.model;
  const head = h('div', { class: 'td-top' },
    h('span', { class: 'td-date' }, tdCap(TD_DAY.format(new Date()))),
    h('span', { class: 'spacer' }),
    Today.err ? h('span', { class: 'td-err' }, Today.err) : null,
    Today.fetchedAt ? h('span', { class: 'td-meta' }, `odświeżono ${TD_TIME.format(Today.fetchedAt)} · co 60 s`) : null,
    h('button', { class: 'td-refresh', title: 'odśwież', onclick: () => Today.load() }, '↻'));
  if (!m) { main.append(h('div', { class: 'td-view' }, head, h('div', { class: 'empty' }, Today.err ? 'nie udało się pobrać' : 'ładowanie…'))); return; }
  main.append(h('div', { class: 'td-view' }, head,
    h('div', { class: 'td-grid' },
      h('div', { class: 'td-col' }, window.tdBrief(m.brief)),
      h('div', { class: 'td-col' },
        window.tdApprovals(m.brief), window.tdQueue(m.queue), tdTasks(m.tasks || []), tdProblems(m.problems || [], m.hosts || [], m.muted_problems || 0),
        tdCards(m.cards || [])))));
};
