/* ============================================================
   hosts.js — host_metrics per host. Process attribution joined
   with logs is the unique angle. "is anything on fire?"
   ============================================================ */

function metricRow(label, val, unit, series, color, hot) {
  if (val == null) {
    return h('div', { class: 'metric null' },
      h('span', { class: 'ml' }, label),
      h('span', { class: 'sparkwrap' }),
      h('span', { class: 'mv' }, '—'));
  }
  return h('div', { class: 'metric' + (hot ? ' hot' : '') },
    h('span', { class: 'ml' }, label),
    h('span', { class: 'sparkwrap', html: sparkline(series, { color, w: 200, h: 26, max: 100 }) }),
    h('span', { class: 'mv num' }, val, h('span', { class: 'u' }, unit)));
}

function hostCard(host, st) {
  const m = DB.METRICS[host.id];
  const range = st.range || '1h';
  const focused = st.focus === host.id;
  const warns = DB.LOGS.filter(l => l.host === host.id && LV_ORDER[l.level] >= 3).slice(0, 6);

  const card = h('div', { class: 'hcard' + (focused ? ' focus' : ''), id: 'host-' + host.id });
  card.append(h('div', { class: 'hcard-hd' },
    h('span', { class: 'hd', style: { width: '8px', height: '8px', borderRadius: '50%', background: `var(--${lagClass(host.lag) === 'good' ? 'good' : lagClass(host.lag) === 'warn' ? 'st-warn' : 'stale'})` } }),
    h('span', { class: 'hn' }, host.id),
    h('span', { class: 'role ' + host.role }, host.role),
    h('span', { class: 'grow' }),
    h('span', { class: 'lagchip' }, h('span', { class: 'hd ' + lagClass(host.lag) }), host.lag + 's lag'),
  ));
  card.append(h('div', { class: 'hcard-up' },
    h('span', {}, h('span', { class: 'faint' }, 'up '), h('b', {}, host.up)),
    h('span', {}, h('span', { class: 'faint' }, 'net '), h('b', {}, m.net)),
    h('span', {}, h('span', { class: 'faint' }, 'disk '), h('b', {}, m.disk + '%')),
  ));

  // metrics
  const metrics = h('div', { class: 'metrics' },
    metricRow('cpu', m.cpu, '%', m.cpu_s, 'var(--accent)', m.cpu > 80),
    metricRow('mem', m.mem, '%', m.mem_s, 'var(--good)', m.mem > 85),
    metricRow('gpu', m.gpu, '%', m.gpu_s, 'var(--s-paused)', m.gpu != null && m.gpu > 85),
  );
  card.append(metrics);

  // gpu models (win10 only)
  if (m.gpu_models) {
    card.append(h('div', { class: 'gpu-strip' },
      h('span', { class: 'lbl' }, 'gpu models loaded · ' + m.gpu_temp + '°C'),
      h('div', { class: 'gpu-chips' }, ...m.gpu_models.map(([n, v]) =>
        h('div', { class: 'gpu-chip' },
          h('span', { class: 'gn' }, n),
          h('span', { class: 'vbar' }, h('i', { style: { width: (v / 16 * 100) + '%' } })),
          h('span', { class: 'gv' }, v + 'GB'))))));
  }

  // top processes
  card.append(h('div', { class: 'procs' },
    h('span', { class: 'lbl' }, h('span', {}, 'top cpu'), h('span', { class: 'faint', style: { fontWeight: 400 } }, 'data.top_cpu')),
    ...m.top_cpu.map(([name, cpu, pid]) => h('div', { class: 'proc' },
      h('span', { class: 'pn' }, name),
      h('span', { class: 'pcpu num' + (cpu > 30 ? ' high' : '') }, cpu.toFixed(1) + '%'),
      h('span', { class: 'ppid num', title: 'correlate pid in Logs', onclick: () => setState({ tab: 'logs', grep: 'pid', host: null, level_min: null, source: null }) }, 'pid:' + pid)))));

  // recent warn+
  card.append(h('div', { class: 'hwarn' },
    h('span', { class: 'lbl' }, 'recent warn+'),
    warns.length ? h('div', {}, ...warns.map(l => h('div', { class: 'hwarn-row' },
      h('span', { class: 't num' }, relShort(l.ts)),
      h('span', { class: 'lv ' + l.level }, l.level),
      h('span', { class: 'm' }, l.msg)))) : h('div', { class: 'hwarn-empty' }, '✓ no warnings — clear')));

  return card;
}

VIEWS.hosts = function (st, main) {
  const range = st.range || '1h';
  const wrap = h('div', { class: 'hosts-view' });
  wrap.append(h('div', { class: 'sec-bar' },
    h('span', { class: 'lbl' }, 'hosts ', h('span', { class: 'faint num', style: { fontWeight: 400 } }, DB.HOSTS.length)),
    h('span', { class: 'faint', style: { fontSize: '11px' } }, '· sampled every 30s'),
    h('span', { class: 'grow' }),
    h('div', { class: 'range-toggle' },
      ...['1h', '6h', '24h'].map(r => h('button', { class: range === r ? 'on' : '', onclick: () => setState({ range: r === '1h' ? null : r }) }, r))),
  ));
  const scroll = h('div', { class: 'hosts-scroll' });
  scroll.append(h('div', { class: 'host-grid' }, ...DB.HOSTS.map(host => hostCard(host, st))));
  wrap.append(scroll);
  main.append(wrap);
};
