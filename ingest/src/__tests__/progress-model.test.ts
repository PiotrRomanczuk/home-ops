import { describe, expect, it } from 'vitest';
import { buildProgress, parseSignalsBody } from '../progress-model.ts';

const row = (extra: Record<string, unknown> = {}) => ({
  project_slug: 'strummy',
  day: '2026-11-03',
  signal: 'commits',
  n: 4,
  ...extra,
});

describe('parseSignalsBody', () => {
  it('accepts additive rows (no replace)', () => {
    expect(parseSignalsBody({ rows: [row()] })).toEqual({ rows: [row()], replace: null });
  });

  it.each([
    [{ project_slug: '' }, 'row 0: invalid project_slug'],
    [{ day: '3.11.2026' }, 'row 0: invalid day'],
    [{ signal: 'stars' }, 'row 0: invalid signal'],
    [{ n: -1 }, 'row 0: invalid n'],
    [{ n: 1.5 }, 'row 0: invalid n'],
  ])('rejects a bad row %o', (extra, reason) => {
    expect(parseSignalsBody({ rows: [row(extra)] })).toBe(reason);
  });

  it('validates a replace window and keeps rows inside it', () => {
    const replace = { from: '2026-08-17', to: '2026-11-08', projects: ['strummy', 'home-ops'], signals: ['commits'] };
    const ok = parseSignalsBody({ rows: [row()], replace });
    expect(ok).toMatchObject({ replace: { projects: ['strummy', 'home-ops'], signals: ['commits'] } });
    expect(parseSignalsBody({ rows: [row({ day: '2026-12-01' })], replace })).toMatch(/outside/);
    expect(parseSignalsBody({ rows: [row({ signal: 'deploys' })], replace })).toMatch(/outside/);
    expect(parseSignalsBody({ rows: [], replace: { ...replace, from: '2026-12-01' } })).toBe('replace: invalid window');
    expect(parseSignalsBody({ rows: [], replace: { ...replace, signals: [] } })).toBe('replace: invalid signals');
  });
});

describe('buildProgress', () => {
  const weeks = ['2026-10-19', '2026-10-26', '2026-11-02'];
  const base = {
    weeks,
    today: '2026-11-08',
    projects: [
      {
        slug: 'strummy',
        title: 'Strummy',
        status: 'hot',
        health: '🟠',
        verdict: 'aktywny',
        ci: { conclusion: 'success' },
        last_deploy_at: '2026-11-07T06:49:28Z',
      },
      {
        slug: 'zadluzenie',
        title: 'zadłużenie',
        status: 'hot',
        health: null,
        verdict: 'prywatny',
        ci: null,
        last_deploy_at: null,
      },
      {
        slug: 'home-ops',
        title: 'home-ops',
        status: 'hot',
        health: '🟢',
        verdict: 'aktywny',
        ci: null,
        last_deploy_at: null,
      },
      {
        slug: 'blogposts',
        title: 'blogposts',
        status: 'dormant',
        health: null,
        verdict: 'archiwum',
        ci: null,
        last_deploy_at: null,
      },
      {
        slug: 'stano',
        title: 'stano',
        status: 'dormant',
        health: null,
        verdict: 'archiwum',
        ci: null,
        last_deploy_at: null,
      },
    ],
    signals: [
      { project_slug: 'strummy', week: '2026-11-02', signal: 'commits', n: 12 },
      { project_slug: 'strummy', week: '2026-10-26', signal: 'pr_merged', n: 3 },
      { project_slug: 'strummy', week: '2026-10-05', signal: 'commits', n: 99 },
      { project_slug: 'home-ops', week: '2026-11-02', signal: 'tasks_done', n: 2 },
    ],
    runs: [{ project_slug: 'stano', week: '2026-11-02', ok: 0, failed: 26_000 }],
    lastMoved: [
      { project_slug: 'strummy', last_moved: '2026-11-07' },
      { project_slug: 'home-ops', last_moved: '2026-10-20' },
    ],
  };

  it('builds weekly series, ignoring weeks outside the window', () => {
    const p = buildProgress(base).projects.find((x) => x.slug === 'strummy');
    expect(p?.series.commits).toEqual([0, 0, 12]);
    expect(p?.series.pr_merged).toEqual([0, 3, 0]);
    expect(p).toMatchObject({ last_moved: '2026-11-07', days_still: 1, stalled: false });
  });

  it('flags hot projects that have not moved for 14 days (or ever)', () => {
    const ps = buildProgress(base).projects;
    expect(ps.find((x) => x.slug === 'home-ops')).toMatchObject({ days_still: 19, stalled: true });
    expect(ps.find((x) => x.slug === 'zadluzenie')).toMatchObject({ days_still: null, stalled: true });
  });

  it('keeps hot/warm plus anything with activity; dormant with only runs still shows', () => {
    const slugs = buildProgress(base).projects.map((x) => x.slug);
    expect(slugs).not.toContain('blogposts');
    expect(slugs).toContain('stano');
    expect(slugs.slice(0, 3)).toEqual(['strummy', 'home-ops', 'zadluzenie']);
    expect(buildProgress(base).projects.find((x) => x.slug === 'stano')?.series.runs_failed).toEqual([0, 0, 26_000]);
  });
});
