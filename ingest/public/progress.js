/* ============================================================
   progress.js — "Postęp" tab: how every project moved over the
   last 12 weeks. Tiles for this week vs last, the hot projects
   that stand still, and a heatmap (row = project, column = week;
   one hue, darker = more). A row opens the project in Projects.
   Data: progress-api.js ← GET /api/progress.
   ============================================================ */

const PG_TIME = new Intl.DateTimeFormat('pl-PL', { hour: '2-digit', minute: '2-digit' });
const PG_GROUPS = [['hot', 'Gorące'], ['warm', 'Ciepłe'], ['other', 'Pozostałe z ruchem']];

function pgDaysAgo(iso) {
  if (!iso) return null;
  const days = Math.floor((Date.now() - Date.parse(iso)) / 86_400_000);
  return ProgressPure.stillLabel(days);
}

function pgTiles(projects, weeks) {
  return h('div', { class: 'pg-tiles' }, ...ProgressPure.tiles(projects, weeks).map((t) => {
    const bad = t.key === 'runs_failed';
    const dir = t.delta === 0 ? '=' : t.delta > 0 ? '↑' : '↓';
    return h('div', { class: 'pg-tile' + (bad && t.now ? ' bad' : '') },
      h('span', { class: 'pg-tile-v num' }, String(t.now)),
      h('span', { class: 'pg-tile-l' }, t.label),
      h('span', { class: 'pg-tile-d num' }, `${dir} ${Math.abs(t.delta)} vs poprz. tydz.`));
  }));
}

function pgStalled(projects) {
  const still = projects.filter((p) => p.stalled);
  if (!still.length) return null;
  return h('section', { class: 'pg-sec pg-still' },
    h('h2', { class: 'pg-h' }, 'Gorące, ale stoją', h('span', { class: 'pg-ct' }, String(still.length))),
    h('div', { class: 'pg-meta' }, 'Status w vaulcie „hot”, a od 14 dni brak commita, PR-a, deployu i odhaczonego zadania. Zmienić status albo ruszyć.'),
    h('ul', { class: 'pg-still-l' }, ...still.map((p) => h('li', {},
      h('button', { class: 'pg-link', onclick: () => setState({ tab: 'projects', slug: p.slug }) }, p.title),
      h('span', { class: 'pg-still-d' }, p.days_still == null ? 'brak ruchu w 12 tygodniach' : `${p.days_still} dni bez ruchu`)))));
}

function pgCi(ci) {
  if (!ci || !ci.conclusion) return h('span', { class: 'pg-ci none' }, '—');
  const ok = ci.conclusion === 'success';
  return h('a', { class: 'pg-ci ' + (ok ? 'ok' : 'bad'), href: ci.url || '#', target: '_blank', rel: 'noopener',
    title: `${ci.workflow || 'CI'} · ${ci.conclusion}` }, ok ? '✓ ok' : `✗ ${ci.conclusion}`);
}

function pgRow(p, view, weeks, max) {
  const cells = Array.from({ length: weeks }, (_, i) => {
    const v = ProgressPure.cell(p.series, view, i);
    return h('td', { class: `pg-c l${ProgressPure.level(v, max)}`, title: `${p.title} · tydz. od ${ProgressPure.weekLabel(Progress.model.weeks[i])}: ${ProgressPure.breakdown(p.series, i)}` });
  });
  const still = ProgressPure.stillLabel(p.days_still);
  return h('tr', { class: 'pg-row', onclick: () => setState({ tab: 'projects', slug: p.slug }) },
    h('th', { class: 'pg-name', scope: 'row', title: p.slug },
      h('span', { class: 'pg-dot ' + (p.status || '') }), p.title, p.health ? h('span', { class: 'pg-health' }, ` ${p.health}`) : null),
    ...cells,
    h('td', { class: 'pg-x' }, pgCi(p.ci)),
    h('td', { class: 'pg-x num', title: p.last_deploy_at || '' }, pgDaysAgo(p.last_deploy_at) || '—'),
    h('td', { class: 'pg-x num' + (p.stalled ? ' bad' : '') }, still ? (still === 'dziś' ? 'dziś' : `${still} temu`) : '—'));
}

function pgHeatmap(model, view) {
  const weeks = model.weeks.length;
  const max = ProgressPure.gridMax(model.projects, view, weeks);
  const groupOf = (p) => (p.status === 'hot' || p.status === 'warm' ? p.status : 'other');
  const head = h('tr', {}, h('th', { class: 'pg-name' }, 'Projekt'),
    ...model.weeks.map((w, i) => h('th', { class: 'pg-wk' + (i % 2 ? ' odd' : '') }, ProgressPure.weekLabel(w))),
    h('th', { class: 'pg-x' }, 'CI'), h('th', { class: 'pg-x' }, 'Deploy'), h('th', { class: 'pg-x' }, 'Ruch'));
  const body = PG_GROUPS.flatMap(([key, label]) => {
    const rows = model.projects.filter((p) => groupOf(p) === key);
    return rows.length ? [h('tr', { class: 'pg-grp' }, h('th', { colspan: weeks + 4 }, label)), ...rows.map((p) => pgRow(p, view, weeks, max))] : [];
  });
  return h('section', { class: 'pg-sec' },
    h('h2', { class: 'pg-h' }, 'Tydzień po tygodniu', h('span', { class: 'pg-legend' }, 'mniej',
      ...[1, 2, 3, 4].map((l) => h('i', { class: `pg-c l${l}` })), 'więcej')),
    h('div', { class: 'pg-scroll' }, h('table', { class: 'pg-table' }, h('thead', {}, head), h('tbody', {}, ...body))));
}

VIEWS.progress = (st, main) => {
  if (!Progress.loaded && !Progress.loading) Progress.load();
  Progress.startPolling();
  const view = ProgressPure.VIEWS[st.pgv] ? st.pgv : 'all';
  const head = h('div', { class: 'pg-top' },
    h('span', { class: 'pg-title' }, 'Postęp'), h('span', { class: 'pg-sub' }, '12 tygodni'),
    h('span', { class: 'spacer' }),
    h('span', { class: 'srv-seg' }, ...Object.entries(ProgressPure.VIEWS).map(([k, v]) => h('button', {
      class: view === k ? 'on' : '', onclick: () => setState({ pgv: k === 'all' ? null : k }, true) }, v.label))),
    Progress.err ? h('span', { class: 'srv-err' }, Progress.err) : null,
    Progress.fetchedAt ? h('span', { class: 'srv-meta' }, `odświeżono ${PG_TIME.format(Progress.fetchedAt)}`) : null,
    h('button', { class: 'srv-refresh', title: 'odśwież', onclick: () => Progress.load() }, '↻'));
  const m = Progress.model;
  if (!m) {
    main.append(h('div', { class: 'pg-view' }, head, h('div', { class: 'empty' }, Progress.err ? 'nie udało się pobrać' : 'ładowanie…')));
    return;
  }
  main.append(h('div', { class: 'pg-view' }, head,
    h('div', { class: 'pg-body' }, pgTiles(m.projects, m.weeks.length), pgStalled(m.projects), pgHeatmap(m, view))));
};
