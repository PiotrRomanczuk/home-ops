/* ============================================================
   projects.js — vault-derived cards + per-project drill.
   Join key = slug. logs: source='app:<slug>'; jobs: payload.project.
   ============================================================ */

function projLogs(slug) {
  return (window.Logs?.rows || DB.LOGS).filter(l =>
    l.source === 'app:' + slug
    // home-ops's own warnings about this slug (vault conflicts on task toggles).
    || (l.source === 'app:home-ops' && l.data && l.data.slug === slug)
  );
}
function projJobs(slug) { return (window.Chat?.conversations || DB.CONVERSATIONS).filter(c => c.project === slug); }

/* ---------- card (grid) ---------- */
function projCard(p) {
  const now2 = p.now.filter(n => !n[1]).slice(0, 2);
  const recentLogErr = projLogs(p.slug).filter(l => LV_ORDER[l.level] >= 3).length;
  return h('button', { class: 'pcard ' + p.status, onclick: () => setState({ slug: p.slug }) },
    h('div', { class: 'pcard-top' },
      h('span', { class: 'pill ' + p.status }, h('span', { class: 'pd' }), p.status),
      h('span', { class: 'grow' }),
      h('span', { class: 'pcard-stat num' },
        h('span', {}, h('b', {}, p.commits_30d), ' commits/30d'),
        h('span', { class: 'faint' }, rel(p.last_commit))),
    ),
    h('div', {},
      h('div', { class: 'pcard-slug' }, p.slug),
      h('div', { class: 'pcard-title' }, p.title)),
    h('div', { class: 'pcard-mid' },
      h('span', { class: 'pulse', html: pulseBars(p.spark, `var(--p-${p.status})`) }),
    ),
    now2.length ? h('div', { class: 'pcard-now' },
      ...now2.map(n => h('div', { class: 'now-item' }, h('span', { class: 'box' }), h('span', {}, n[0]))),
    ) : null,
    (p.errors_today || p.jobs_q) ? h('div', { class: 'pcard-lag' },
      p.errors_today ? h('span', { class: 'lag-chip err' }, '▲ ' + p.errors_today + ' error' + (p.errors_today > 1 ? 's' : '') + ' today') : null,
      p.jobs_q ? h('span', { class: 'lag-chip job' }, '◷ ' + p.jobs_q + ' job' + (p.jobs_q > 1 ? 's' : '') + ' queued') : null,
    ) : null,
  );
}

/* ---------- compact list row ---------- */
function projListRow(p) {
  const now1 = p.now.find(n => !n[1]);
  return h('button', { class: 'plrow', onclick: () => setState({ slug: p.slug }) },
    h('span', { class: 'pill ' + p.status }, h('span', { class: 'pd' }), p.status),
    h('span', { class: 'pl-slug' }, p.slug),
    h('span', { class: 'pl-now' }, now1 ? now1[0] : h('span', { class: 'faint' }, '— now clear —')),
    h('span', { class: 'pl-lag' },
      p.errors_today ? h('span', { class: 'lag-chip err' }, '▲' + p.errors_today) : null,
      p.jobs_q ? h('span', { class: 'lag-chip job' }, '◷' + p.jobs_q) : null,
      h('span', { class: 'pulse', html: pulseBars(p.spark.slice(-14), `var(--p-${p.status})`) })),
    h('span', { class: 'pl-age num', style: { textAlign: 'left' } }, h('b', { style: { color: 'var(--fg)' } }, p.commits_30d), h('span', { class: 'faint' }, '/30d')),
    h('span', { class: 'pl-age num' }, rel(p.last_commit)),
  );
}

/* ---------- drill page ---------- */
async function toggleTask(slug, section, idx, item) {
  const desired = !item[1];
  item[1] = desired;                // optimistic flip
  item._pending = true;
  render();
  try {
    await window.api('POST', `/api/projects/${encodeURIComponent(slug)}/tasks/${section}/${idx}/toggle`, { done: desired });
    item._pending = false;
    // The worker will write back and the next vault-sync tick (≤60s)
    // refreshes the parsed Now/Next/Later. Leave the optimistic flip in
    // place for now — Projects.refreshOne could be triggered if we want
    // faster convergence.
    render();
  } catch (e) {
    item[1] = !desired;             // rollback
    item._pending = false;
    item._error = e.message || 'toggle failed';
    render();
    setTimeout(() => { delete item._error; render(); }, 3500);
  }
}

function taskList(items, slug, section) {
  return h('div', { class: 'tasklist' }, ...items.map((it, i) =>
    h('button', {
      class: 'task' + (it[1] ? ' done' : '') + (it._pending ? ' pending' : '') + (it._error ? ' err' : ''),
      title: it._error || (it._pending ? 'writing to vault…' : ''),
      onclick: () => toggleTask(slug, section, i, it),
    },
      h('span', { class: 'cb' }, it[1] ? '✓' : it._pending ? '◴' : ''),
      h('span', { class: 'tx' }, it[0]),
    )));
}

function collapsibleBlock(title, count, bodyEl, collapsed) {
  const block = h('div', { class: 'block' + (collapsed ? ' collapsed' : '') });
  const hd = h('div', { class: 'block-hd collapse-hd', onclick: () => block.classList.toggle('collapsed') },
    h('span', { class: 'caret' }, '▼'),
    h('span', { class: 'lbl' }, title),
    count != null ? h('span', { class: 'faint num', style: { fontSize: '11px' } }, count) : null,
  );
  block.append(hd, bodyEl);
  return block;
}

function drillPage(p, main) {
  const logs = projLogs(p.slug).slice(0, 20);
  const jobs = projJobs(p.slug);
  const wrap = h('div', { class: 'drill' });

  // header
  const hd = h('div', { class: 'drill-hd' },
    h('button', { class: 'drill-back', onclick: () => setState({ slug: null }) }, '← all projects'),
    h('div', { class: 'drill-title' },
      h('span', { class: 'pill ' + p.status }, h('span', { class: 'pd' }), p.status),
      h('span', { class: 'slug' }, p.slug),
      h('span', { class: 'mut', style: { fontSize: '13px' } }, p.title),
      h('span', { class: 'grow' }),
      h('a', { class: 'vault-link', href: 'obsidian://open?path=' + encodeURIComponent(p.path), title: 'open in Obsidian' }, '◆ open vault file'),
    ),
    h('div', { class: 'drill-meta' },
      h('span', {}, h('span', { class: 'k' }, 'path '), p.path),
      h('span', { class: 'num' }, h('span', { class: 'k' }, 'last commit '), rel(p.last_commit)),
      h('span', { class: 'num' }, h('span', { class: 'k' }, 'commits/30d '), h('b', {}, p.commits_30d)),
      h('span', { class: 'num' }, h('span', { class: 'k' }, 'updated '), rel(p.updated_at)),
      h('span', { class: 'pulse', html: pulseBars(p.spark, `var(--p-${p.status})`) }),
    ),
  );
  wrap.append(hd);

  // two-column body
  const left = h('div', { class: 'drill-col' });
  // Now / Next collapsible group, Later
  left.append(collapsibleBlock('Now', p.now.length, taskList(p.now, p.slug, 'now'), false));
  left.append(collapsibleBlock('Next', p.next.length, taskList(p.next, p.slug, 'next'), false));
  if (p.later.length) left.append(collapsibleBlock('Later', p.later.length, taskList(p.later, p.slug, 'later'), true));
  // pain
  left.append(h('div', { class: 'block' },
    h('div', { class: 'pain' },
      h('div', { class: 'ph' }, '▲ pain points'),
      p.pain)));
  // quick actions
  left.append(h('div', { class: 'block' },
    h('div', { class: 'block-hd' }, h('span', { class: 'lbl' }, 'quick actions')),
    h('div', { class: 'qactions' },
      h('button', { class: 'qaction', onclick: () => { DRAFT.project = p.slug; DRAFT.model = 'qwen3:8b'; setState({ tab: 'chat', conv: null, slug: null }); setTimeout(() => { const ta = $('.comp-ta'); if (ta) { ta.value = `/summarise today's app:${p.slug} logs`; ta.dispatchEvent(new Event('input')); ta.focus(); } }, 60); } }, '⌁ summarise today\'s logs'),
      h('button', { class: 'qaction', onclick: () => { DRAFT.project = p.slug; setState({ tab: 'chat', conv: null, slug: null }); setTimeout(() => { const ta = $('.comp-ta'); if (ta) { ta.value = `/embed Now items`; ta.dispatchEvent(new Event('input')); ta.focus(); } }, 60); } }, '⧉ embed Now items'),
      h('button', { class: 'qaction', onclick: () => openCapture() }, '✎ open in editor'),
    )));

  const right = h('div', { class: 'drill-col' });
  // recent events
  const logBody = logs.length ? h('div', { class: 'mini' }, ...logs.slice(0, 8).map(l =>
    h('div', { class: 'mini-row mini-log' },
      h('span', { class: 't num' }, window.__abs ? abs(l.ts) : relShort(l.ts)),
      h('span', { class: 'lv ' + l.level }, l.level),
      h('span', { class: 'msg' }, l.msg)))) : h('div', { class: 'empty', style: { height: 'auto', padding: '18px' } }, 'no app:' + p.slug + ' events in 30d');
  right.append(h('div', { class: 'block' },
    h('div', { class: 'block-hd' }, h('span', { class: 'lbl' }, 'recent events'), h('span', { class: 'grow' }),
      h('button', { class: 'block-link', onclick: () => setState({ tab: 'logs', source: 'app:' + p.slug, slug: null }) }, 'open in Logs →')),
    logBody));
  // recent jobs
  const jobBody = jobs.length ? h('div', { class: 'mini' }, ...jobs.map(j =>
    h('button', { class: 'mini-row mini-job', style: { width: '100%', textAlign: 'left' }, onclick: () => setState({ tab: 'chat', conv: j.id, slug: null }) },
      h('span', { class: 'jt' }, j.title),
      h('span', { class: 'pill ' + statusOf(j) }, h('span', { class: 'pd' }), statusOf(j)),
      h('span', { class: 't num', style: { textAlign: 'right' } }, relShort(j.updated))))) : h('div', { class: 'empty', style: { height: 'auto', padding: '18px' } }, 'no jobs tagged ' + p.slug);
  right.append(h('div', { class: 'block' },
    h('div', { class: 'block-hd' }, h('span', { class: 'lbl' }, 'recent jobs'), h('span', { class: 'grow' }),
      h('button', { class: 'block-link', onclick: () => setState({ tab: 'chat', slug: null }) }, 'open in Chat →')),
    jobBody));

  const body = h('div', { class: 'drill-body' }, left, right);
  wrap.append(body);
  main.append(wrap);
}

/* ---------- view ---------- */
function syncedLabel() {
  if (!Projects.syncedAt) return Projects.loading ? '· loading…' : '· awaiting first sync';
  return '· vault sync ' + relShort(Projects.syncedAt) + ' ago';
}

VIEWS.projects = function (st, main) {
  if (!Projects.loaded && !Projects.loading) Projects.loadAll();

  if (st.slug) {
    const p = Projects.bySlug(st.slug);
    if (p) return drillPage(p, main);
    // Fall through to grid if the slug isn't loaded yet — once loadAll
    // resolves, the hashchange re-render will find it.
  }
  const layout = st.players === 'list' ? 'list' : 'grid';
  const order = [...Projects.items].sort((a, b) => {
    const rank = { hot: 0, warm: 1, stalled: 2, dormant: 3 };
    return rank[a.status] - rank[b.status];
  });

  const wrap = h('div', { class: 'proj-view' });
  wrap.append(h('div', { class: 'sec-bar' },
    h('span', { class: 'lbl' }, 'projects ', h('span', { class: 'faint num', style: { fontWeight: 400 } }, Projects.items.length)),
    h('span', { class: 'faint', style: { fontSize: '11px' } }, syncedLabel()),
    Projects.err ? h('span', { class: 'lv error', style: { fontSize: '11px' } }, '✕ ' + Projects.err) : null,
    h('span', { class: 'grow' }),
    h('button', { class: 'toolbtn', onclick: () => Projects.loadAll(), title: 'refresh from server' }, '↻'),
    h('div', { class: 'seg-toggle' },
      h('button', { class: layout === 'grid' ? 'on' : '', onclick: () => setState({ players: null }) }, '▦ grid'),
      h('button', { class: layout === 'list' ? 'on' : '', onclick: () => setState({ players: 'list' }) }, '☰ list')),
  ));
  const scroll = h('div', { class: 'proj-scroll' });
  if (!order.length) {
    scroll.append(h('div', { class: 'empty', style: { padding: '60px 0' } },
      h('div', { class: 'big' }, Projects.loading ? 'loading…' : 'no projects yet'),
      Projects.loading ? '' : 'check that planner-sync is running on elitedesk'));
  } else if (layout === 'grid') {
    scroll.append(h('div', { class: 'proj-grid' }, ...order.map(projCard)));
  } else {
    const list = h('div', { class: 'proj-list' },
      h('div', { class: 'plrow head' }, h('span', {}, 'status'), h('span', {}, 'slug'), h('span', {}, 'now'), h('span', {}, 'signal'), h('span', {}, 'commits'), h('span', {}, 'last')),
      ...order.map(projListRow));
    scroll.append(list);
  }
  wrap.append(scroll);
  main.append(wrap);
};
