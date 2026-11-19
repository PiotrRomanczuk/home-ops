/* ============================================================
   progress-pure.js — the Postęp tab's math, no DOM: what a cell
   means per view, heatmap levels, week totals and their deltas.
   Exposed as globalThis.ProgressPure (tested in __tests__).
   ============================================================ */

(function () {
  /* What one heatmap cell counts in each view. "all" weights finished work:
     a merged PR or a ticked task says more than a single commit. */
  const VIEWS = {
    all: { label: 'Wszystko', parts: { commits: 1, pr_merged: 3, deploys: 2, tasks_done: 2 } },
    code: { label: 'Kod', parts: { commits: 1, pr_merged: 3 } },
    tasks: { label: 'Zadania', parts: { tasks_done: 1 } },
    runs: { label: 'Rutyny', parts: { runs_ok: 1, runs_failed: 1 } },
  };
  const TILES = [
    ['commits', 'commity'], ['pr_merged', 'PR zmergowane'], ['tasks_done', 'zadania odhaczone'],
    ['deploys', 'deploye'], ['runs_failed', 'porażki rutyn'],
  ];

  function cell(series, view, i) {
    const parts = (VIEWS[view] || VIEWS.all).parts;
    return Object.entries(parts).reduce((n, [k, w]) => n + w * ((series[k] || [])[i] || 0), 0);
  }

  /** 0 = nothing, 1..4 on a square-root scale of the busiest cell, so one
      record week (Strummy's PR burst) doesn't flatten everyone else to 1. */
  function level(v, max) {
    if (!v || !max) return 0;
    return Math.min(4, Math.max(1, Math.ceil(Math.sqrt(v / max) * 4)));
  }

  function gridMax(projects, view, weeks) {
    let max = 0;
    for (const p of projects) for (let i = 0; i < weeks; i++) max = Math.max(max, cell(p.series, view, i));
    return max;
  }

  /** Sum of one signal over all projects for week i. */
  function weekTotal(projects, key, i) {
    return projects.reduce((n, p) => n + ((p.series[key] || [])[i] || 0), 0);
  }

  function tiles(projects, weeks) {
    const cur = weeks - 1;
    return TILES.map(([key, label]) => {
      const now = weekTotal(projects, key, cur);
      const prev = cur > 0 ? weekTotal(projects, key, cur - 1) : 0;
      return { key, label, now, prev, delta: now - prev };
    });
  }

  /** Tooltip text for one cell: every non-zero signal that week. */
  function breakdown(series, i) {
    const names = {
      commits: 'commity', pr_opened: 'PR otwarte', pr_merged: 'PR zmergowane', deploys: 'deploye',
      ci_ok: 'CI ok', ci_failed: 'CI błąd', tasks_done: 'zadania odhaczone', tasks_added: 'zadania dodane',
      runs_ok: 'rutyny ok', runs_failed: 'rutyny błąd',
    };
    const parts = Object.keys(names).filter((k) => (series[k] || [])[i]).map((k) => `${names[k]} ${series[k][i]}`);
    return parts.length ? parts.join(' · ') : 'bez ruchu';
  }

  /** "dziś" / "wczoraj" / "5 dni" / null. */
  function stillLabel(days) {
    if (days == null) return null;
    if (days <= 0) return 'dziś';
    if (days === 1) return 'wczoraj';
    return `${days} dni`;
  }

  /** "2026-10-26" → "26.10". */
  function weekLabel(w) {
    const [, m, d] = String(w).split('-');
    return `${Number(d)}.${m}`;
  }

  const api = { VIEWS, cell, level, gridMax, weekTotal, tiles, breakdown, stillLabel, weekLabel };
  if (typeof window !== 'undefined') window.ProgressPure = api;
  globalThis.ProgressPure = api;
})();
