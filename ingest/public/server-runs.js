/* ============================================================
   server-runs.js — the Serwer tab's lower half: a timeline with
   one lane per project, and the run list (filters, ×N for crash
   loops, click a run to read its log).
   ============================================================ */

const SRV_DAY = new Intl.DateTimeFormat('pl-PL', { weekday: 'short', day: 'numeric' });
const SRV_PAGE = 150;
const SRV_KIND = { timer: 'timer', service: 'usługa', gha: 'GitHub' };

/* Local-time ticks: every 3 h for a day, midnights for a week. */
function srvTicks(from, to, rangeH) {
  const step = rangeH <= 24 ? 3 : 24;
  const d = new Date(from);
  d.setMinutes(0, 0, 0);
  d.setHours(Math.ceil(d.getHours() / step) * step);
  const out = [];
  for (; d.getTime() <= to; d.setHours(d.getHours() + step)) {
    out.push({ x: (d.getTime() - from) / (to - from), label: step === 24 ? SRV_DAY.format(d) : SRV_TIME.format(d) });
  }
  return out;
}

function srvLaneSvg(lane, ticks) {
  const grid = ticks.map((t) => `<line x1="${t.x * 1000}" x2="${t.x * 1000}" y1="0" y2="12" class="tk"/>`).join('');
  const rects = lane.items.map((i) => {
    const tip = `${ServerPure.unitShort(i.unit)}${i.repeat > 1 ? ` ×${i.repeat}` : ''} · ${i.result}`;
    return `<rect data-id="${i.id}" class="r ${i.result}" x="${(i.x0 * 1000).toFixed(1)}" y="1" width="${((i.x1 - i.x0) * 1000).toFixed(1)}" height="10"><title>${tip.replace(/</g, '&lt;')}</title></rect>`;
  }).join('');
  return `<svg viewBox="0 0 1000 12" preserveAspectRatio="none" class="srv-svg">${grid}${rects}</svg>`;
}

function srvTimeline(runs, rangeH) {
  const to = Date.now();
  const from = to - rangeH * 3_600_000;
  const lanes = ServerPure.lanes(runs, from, to);
  const ticks = srvTicks(from, to, rangeH);
  const open = (e) => {
    const id = e.target?.dataset?.id;
    const run = id && runs.find((r) => String(r.id) === id);
    if (run) { setState({ srvo: id, srvu: run.unit, srvp: null, srvf: null }, true); Server.loadLog(run.id); }
  };
  return srvSec('Oś czasu', h('span', { class: 'srv-legend' },
    h('i', { class: 'ok' }), 'ok', h('i', { class: 'failed' }), 'błąd', h('i', { class: 'running' }), 'trwa'),
  lanes.length ? h('div', { class: 'srv-tl', onclick: open },
    ...lanes.map((l) => h('div', { class: 'srv-lane' },
      h('button', { class: 'srv-lane-n', title: `${l.items.length} uruchomień${l.failed ? `, ${l.failed} z błędem` : ''}`,
        onclick: () => setState({ srvp: l.project, srvu: null }, true) }, l.project, l.failed ? h('b', {}, ` ${l.failed}`) : null),
      h('span', { class: 'srv-lane-s', html: srvLaneSvg(l, ticks) }))),
    h('div', { class: 'srv-axis' }, h('span'), h('span', { class: 'srv-axis-t' },
      ...ticks.map((t) => h('span', { style: { left: `${t.x * 100}%` } }, t.label)))))
    : h('div', { class: 'srv-empty' }, 'Brak uruchomień w tym zakresie.'));
}

function srvWhen(iso) {
  const d = new Date(iso);
  return Date.now() - d.getTime() > 20 * 3_600_000 ? `${SRV_DAY.format(d)} ${SRV_TIME.format(d)}` : SRV_TIME.format(d);
}

function srvRunRow(r, st) {
  const open = st.srvo === String(r.id);
  const ms = ServerPure.runMs(r, Date.now());
  const loop = r.repeat_count > 1;
  const toggle = () => {
    setState({ srvo: open ? null : String(r.id) }, true);
    if (!open) Server.loadLog(r.id);
  };
  const log = Server.logs[r.id];
  return h('li', { class: 'srv-run ' + r.result + (open ? ' open' : '') },
    h('button', { class: 'srv-run-h', onclick: toggle },
      h('span', { class: 'srv-when num' }, srvWhen(loop ? r.finished_at || r.started_at : r.started_at)),
      h('span', { class: 'srv-res ' + r.result }, r.result === 'ok' ? 'ok' : r.result === 'failed' ? 'błąd' : 'trwa'),
      h('span', { class: 'srv-unit' }, ServerPure.unitShort(r.unit)),
      loop ? h('span', { class: 'srv-x num', title: 'pętla restartów: tyle porażek z rzędu' }, `×${r.repeat_count}`) : null,
      h('span', { class: 'spacer' }),
      r.project_slug ? h('span', { class: 'srv-proj static' }, r.project_slug) : null,
      h('span', { class: 'srv-dur num' }, loop ? `od ${srvWhen(r.started_at)}` : ServerPure.fmtDur(ms)),
      r.cpu_ms ? h('span', { class: 'srv-cpu num', title: 'czas CPU' }, `cpu ${ServerPure.fmtDur(Number(r.cpu_ms))}`) : null),
    open ? h('div', { class: 'srv-run-b' },
      h('div', { class: 'srv-meta' }, [SRV_KIND[r.kind] || r.kind, r.detail, r.exit_code != null ? `exit ${r.exit_code}` : null,
        r.finished_at ? `koniec ${SRV_TIME.format(new Date(r.finished_at))}` : 'jeszcze trwa'].filter(Boolean).join(' · '),
      r.url ? h('a', { class: 'srv-link', href: r.url, target: '_blank', rel: 'noopener' }, ' · GitHub ↗') : null),
      !log || log.loading ? h('div', { class: 'srv-empty' }, 'ładowanie logu…')
        : log.err ? h('div', { class: 'srv-err' }, log.err)
          : log.lines.length ? h('pre', { class: 'srv-log' }, log.lines.join('\n'))
            : h('div', { class: 'srv-empty' }, r.kind === 'gha' ? 'Log jobu jest na GitHubie.' : 'Ten run nic nie wypisał (albo log był nie do przypisania).'))
      : null);
}

function srvRuns(runs, st) {
  const list = ServerPure.filterRuns(runs, { project: st.srvp, onlyFailed: st.srvf === '1', unit: st.srvu });
  const projects = [...new Set(runs.map((r) => r.project_slug || 'inne'))].sort();
  const limit = Number(st.srvn) || SRV_PAGE;
  const filters = h('div', { class: 'srv-filters' },
    h('select', { class: 'srv-sel', onchange: (e) => setState({ srvp: e.target.value || null, srvn: null }, true) },
      h('option', { value: '' }, 'wszystkie projekty'),
      ...projects.map((p) => h('option', { value: p, selected: st.srvp === p }, p))),
    h('label', { class: 'srv-chk' }, h('input', { type: 'checkbox', checked: st.srvf === '1',
      onchange: (e) => setState({ srvf: e.target.checked ? '1' : null, srvn: null }, true) }), 'tylko błędy'),
    st.srvu ? h('button', { class: 'srv-chip', title: 'usuń filtr', onclick: () => setState({ srvu: null, srvo: null }, true) },
      ServerPure.unitShort(st.srvu), ' ✕') : null,
    h('span', { class: 'spacer' }),
    h('span', { class: 'srv-meta num' }, `${list.length} z ${runs.length}`));
  return srvSec('Uruchomienia', null, filters,
    list.length ? h('ul', { class: 'srv-runs' }, ...list.slice(0, limit).map((r) => srvRunRow(r, st)),
      list.length > limit ? h('li', {}, h('button', { class: 'srv-more', onclick: () => setState({ srvn: String(limit + SRV_PAGE) }, true) },
        `pokaż kolejne (${list.length - limit})`)) : null)
      : h('div', { class: 'srv-empty' }, 'Nic nie pasuje do filtrów.'));
}

window.srvTimeline = srvTimeline;
window.srvRuns = srvRuns;
