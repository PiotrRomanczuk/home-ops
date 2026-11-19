/* ============================================================
   status.js — glanceable Status dashboard. Designed 390px-first
   (pinned iPhone tab): "anything red?" answered in one screen.
   ============================================================ */

function stBanner(s) {
  const lv = s.levels_1h || {};
  const alarms = Status.alarmCount();
  const deadHosts = (s.hosts || []).filter((r) => Status.hostHealth(r) === 'stale');
  const bad = alarms > 0 || deadHosts.length > 0;
  const label = bad
    ? [alarms ? `${alarms} error${alarms > 1 ? 's' : ''} /1h` : null,
       deadHosts.length ? `${deadHosts.map((r) => r.host).join(', ')} silent` : null]
        .filter(Boolean).join(' · ')
    : 'all clear';
  return h('div', { class: 'st-banner ' + (bad ? 'bad' : 'ok'), onclick: () => bad && setState({ tab: 'logs', level_min: 'error' }) },
    h('span', { class: 'st-big' }, bad ? '▲ ' + label : '● ' + label),
    h('span', { class: 'st-sub num' }, `warn ${lv.warn || 0} · err ${lv.error || 0} · fatal ${lv.fatal || 0} — last hour`));
}

function stBar(label, pct, hot) {
  if (pct == null) return null;
  return h('div', { class: 'st-bar' },
    h('span', { class: 'st-bl' }, label),
    h('span', { class: 'st-track' }, h('i', { class: hot ? 'hot' : '', style: { width: Math.min(100, pct) + '%' } })),
    h('span', { class: 'st-bv num' }, Math.round(pct) + '%'));
}

function stHostRow(row) {
  const hd = Status.hostHealth(row);
  const evLag = Status.lagSec(row.last_event_ts);
  const mLag = Status.lagSec(row.last_metric_ts);
  const fmtLag = (v) => (v == null ? 'never' : v < 90 ? v + 's' : v < 5400 ? Math.round(v / 60) + 'm' : Math.round(v / 3600) + 'h');
  return h('div', { class: 'st-host', onclick: () => setState({ tab: 'hosts', focus: row.host }) },
    h('div', { class: 'st-host-hd' },
      h('span', { class: 'hd ' + hd }),
      h('span', { class: 'st-hn' }, row.host),
      row.data && row.data.is_gaming
        ? h('span', { class: 'st-gaming', title: 'a game is running — GPU jobs pause' }, '🎮 ' + (row.data.game || 'gaming'))
        : null,
      h('span', { class: 'grow' }),
      h('span', { class: 'st-lag num', title: 'last log event / last metric sample' },
        `ev ${fmtLag(evLag)} · m ${fmtLag(mLag)}`)),
    h('div', { class: 'st-bars' },
      stBar('cpu', row.cpu_pct, row.cpu_pct > 80),
      stBar('mem', row.mem_pct, row.mem_pct > 85),
      stBar('disk', row.disk_pct, row.disk_pct > 75),
      row.gpu_pct != null ? stBar('gpu', row.gpu_pct, row.gpu_pct > 85) : null));
}

function stQueue(s) {
  const q = s.jobs || {};
  const order = ['running', 'queued', 'paused', 'cancelling', 'failed', 'done'];
  const chips = order.filter((k) => q[k]).map((k) =>
    h('span', { class: 'st-chip q-' + k }, h('b', { class: 'num' }, String(q[k])), ' ' + k));
  return h('div', { class: 'st-sec' },
    h('div', { class: 'st-sec-hd' }, 'queue'),
    chips.length ? h('div', { class: 'st-chips' }, ...chips) : h('div', { class: 'st-empty' }, 'queue empty'));
}

function stErrors(s) {
  const rows = s.recent_errors || [];
  return h('div', { class: 'st-sec' },
    h('div', { class: 'st-sec-hd' }, 'recent errors ', h('span', { class: 'faint' }, '24h')),
    rows.length
      ? h('div', {}, ...rows.map((l) => h('div', { class: 'st-err', onclick: () => setState({ tab: 'logs', level_min: 'error', host: l.host }) },
          h('span', { class: 'st-et num' }, relShort(l.ts)),
          h('span', { class: 'st-eh' }, l.host),
          h('span', { class: 'st-em' }, l.message))))
      : h('div', { class: 'st-empty' }, '✓ no errors in 24h'));
}

VIEWS.status = function (st, main) {
  if (!Status.loaded && !Status.loading) Status.load();
  Status.startRefresh();
  const wrap = h('div', { class: 'status-view' });
  if (!Status.loaded) {
    wrap.append(h('div', { class: 'empty' }, Status.err ? '✕ ' + Status.err : 'loading…'));
    main.append(wrap);
    return;
  }
  const s = Status.snap;
  wrap.append(stBanner(s));
  wrap.append(h('div', { class: 'st-sec' },
    h('div', { class: 'st-sec-hd' }, 'hosts'),
    ...(s.hosts || []).map(stHostRow)));
  wrap.append(stQueue(s));
  wrap.append(stErrors(s));
  wrap.append(h('div', { class: 'st-meta num' },
    `db ${s.db_size || '—'} · refreshed ${new Date(s.now).toTimeString().slice(0, 8)} · every 15s`));
  main.append(wrap);
};
