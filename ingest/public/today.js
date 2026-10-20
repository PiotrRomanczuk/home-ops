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

function tdBrief(b) {
  if (!b) return tdSection('Brief', 0, h('div', { class: 'td-empty' }, 'Brak briefu — brief-pull jeszcze nic nie pobrał.'));
  const meta = [
    `${TD_SLOT[b.slot] || b.slot}`,
    b.is_today ? null : `z ${TD_DAY.format(new Date(b.brief_date + 'T12:00:00'))}`,
    b.generated_at ? `wygenerowany ${TD_TIME.format(new Date(b.generated_at))}` : null,
    (b.sources || []).length ? `źródła: ${b.sources.join(', ')}` : null,
  ].filter(Boolean).join(' · ');
  return h('section', { class: 'td-sec td-brief' + (b.is_today ? '' : ' stale') },
    h('h2', { class: 'td-h' }, b.title || 'Brief'),
    h('div', { class: 'td-meta' }, meta),
    h('div', { class: 'td-md', html: window.MdLite.render(b.body_md) }));
}

function tdTasks(groups) {
  const n = groups.reduce((a, g) => a + g.tasks.length, 0);
  if (!groups.length) return tdSection('Zadania Now', 0, h('div', { class: 'td-empty' }, 'Brak otwartych zadań w Now.'));
  return tdSection('Zadania Now', n, ...groups.map((g) => h('div', { class: 'td-proj' },
    h('button', { class: 'td-proj-h', onclick: () => setState({ tab: 'projects', slug: g.slug }) },
      h('span', { class: 'td-dot ' + (g.status || '') }), g.title),
    h('ul', { class: 'td-list' }, ...g.tasks.map((t) => h('li', { class: t.is_focus ? 'focus' : '' },
      t.is_focus ? h('span', { class: 'td-focus' }, 'fokus') : null,
      t.text,
      t.source === 'board' ? h('span', { class: 'td-src' }, 'board') : null))))));
}

function tdProblems(problems, hosts) {
  const bad = hosts.filter((x) => x.status === 'warn' || x.status === 'bad');
  const rows = [
    ...bad.map((x) => h('li', { class: 'td-prob ' + x.status },
      h('b', {}, x.host), x.status === 'bad' ? ' — milczy (brak świeżych metryk)' : ` — dysk ${x.disk_pct}%`)),
    ...problems.map((p) => h('li', { class: 'td-prob bad', title: p.sample || '' },
      h('b', {}, `${p.source}@${p.host}`), ` — ${p.n_24h}× w 24 h · `,
      h('span', { class: 'td-sample' }, (p.sample || p.pattern || '').slice(0, 140)))),
  ];
  return tdSection('Problemy', rows.length,
    rows.length ? h('ul', { class: 'td-list' }, ...rows) : h('div', { class: 'td-empty ok' }, 'Wszystko spokojnie.'));
}

function tdDecisions(decisions) {
  if (!decisions.length) return tdSection('Decyzje', 0, h('div', { class: 'td-empty' }, 'Nic nie czeka na odpowiedź.'));
  return tdSection('Decyzje', decisions.length, h('ul', { class: 'td-list' }, ...decisions.map((d) =>
    h('li', { class: 'td-dec' },
      h('button', { class: 'td-link', onclick: () => setState({ tab: 'decisions' }) }, d.question),
      h('span', { class: 'td-src' }, d.routine)))));
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
      h('div', { class: 'td-col' }, tdBrief(m.brief)),
      h('div', { class: 'td-col' },
        window.tdQueue(m.queue), tdTasks(m.tasks || []), tdProblems(m.problems || [], m.hosts || []),
        tdDecisions(m.decisions || []), tdCards(m.cards || [])))));
};
