/* ============================================================
   server-pure.js — the Serwer tab's math, no DOM: durations,
   the "right now" headline, timeline lanes, failing units.
   Exposed as globalThis.ServerPure (tested in __tests__).
   ============================================================ */

(function () {
  const unitShort = (u) => String(u || '').replace(/\.service$/, '');

  /** 512 ms → "0,5 s", 420 s → "7 min", 4300 s → "1 h 12 min". */
  function fmtDur(ms) {
    if (ms == null || !Number.isFinite(ms) || ms < 0) return '—';
    const s = ms / 1000;
    if (s < 10) return s.toFixed(1).replace('.', ',') + ' s';
    if (s < 90) return Math.round(s) + ' s';
    const m = Math.round(s / 60);
    if (m < 60) return m + ' min';
    const hr = Math.floor(m / 60), rest = m % 60;
    return rest ? `${hr} h ${rest} min` : `${hr} h`;
  }

  function runMs(r, now) {
    const a = Date.parse(r.started_at);
    const b = r.finished_at ? Date.parse(r.finished_at) : now;
    return Number.isFinite(a) && Number.isFinite(b) ? Math.max(0, b - a) : null;
  }

  /** One sentence for the top of the tab: GitHub jobs first (they are the
      loud ones), then running timers, else calm. */
  function headline(snap, now) {
    if (!snap) return { tone: 'idle', text: 'Brak migawki — activity-watcher jeszcze nic nie wysłał.' };
    const gha = (snap.gha_running || [])[0];
    if (gha) {
      return { tone: 'busy', project: gha.project_slug, text: `${gha.unit} · ${fmtDur(runMs(gha, now))}`, url: gha.url };
    }
    const busy = (snap.runners || []).find((r) => r.busy);
    if (busy) return { tone: 'busy', project: busy.repo.split('/').pop(), text: `runner ${busy.name} pracuje` };
    const run = (snap.running || [])[0];
    if (run) {
      const more = snap.running.length > 1 ? ` (+${snap.running.length - 1})` : '';
      return { tone: 'busy', project: run.project_slug, text: `${unitShort(run.unit)} · ${fmtDur(runMs(run, now))}${more}` };
    }
    return { tone: 'idle', text: 'Spokój — nic nie biegnie.' };
  }

  /** Runs → lanes per project for an SVG timeline over [from, to]. Lanes are
      ordered by how much happened; x0/x1 are 0..1 fractions of the window. */
  function lanes(runs, from, to, minW = 0.002) {
    const span = Math.max(1, to - from);
    const byProject = new Map();
    for (const r of runs) {
      const a = Date.parse(r.started_at);
      if (!Number.isFinite(a)) continue;
      const b = r.finished_at ? Date.parse(r.finished_at) : to;
      if (b < from || a > to) continue;
      const x0 = Math.max(0, (a - from) / span);
      const x1 = Math.max(x0 + minW, Math.min(1, (b - from) / span));
      const key = r.project_slug || 'inne';
      if (!byProject.has(key)) byProject.set(key, []);
      byProject.get(key).push({ id: r.id, x0, x1, result: r.result, unit: r.unit, repeat: r.repeat_count || 1 });
    }
    return [...byProject.entries()]
      .map(([project, items]) => ({ project, items, failed: items.filter((i) => i.result === 'failed').length }))
      .sort((p, q) => q.items.length - p.items.length || p.project.localeCompare(q.project));
  }

  /** Units that failed in the list, worst first: [{unit, project, n, last}]. */
  function failing(runs) {
    const m = new Map();
    for (const r of runs) {
      if (r.result !== 'failed') continue;
      const cur = m.get(r.unit) || { unit: r.unit, project: r.project_slug, n: 0, last: r, total: 0 };
      cur.n += r.repeat_count || 1;
      if (Date.parse(r.started_at) > Date.parse(cur.last.started_at)) cur.last = r;
      m.set(r.unit, cur);
    }
    for (const r of runs) if (m.has(r.unit)) m.get(r.unit).total += r.repeat_count || 1;
    return [...m.values()].sort((a, b) => b.n - a.n);
  }

  function filterRuns(runs, { project, onlyFailed, unit } = {}) {
    return runs.filter((r) => (!project || (r.project_slug || 'inne') === project)
      && (!onlyFailed || r.result === 'failed') && (!unit || r.unit === unit));
  }

  const api = { unitShort, fmtDur, runMs, headline, lanes, failing, filterRuns };
  if (typeof window !== 'undefined') window.ServerPure = api;
  globalThis.ServerPure = api;
})();
