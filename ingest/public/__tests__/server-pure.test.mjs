/* Tests for server-pure.js — the Serwer tab's math.
 *
 * Run: cd ingest && npm test -- --run public/__tests__/server-pure.test.mjs
 */
import { describe, expect, it } from 'vitest';
import '../server-pure.js';

const { fmtDur, headline, lanes, failing, filterRuns, unitShort } = globalThis.ServerPure;

const NOW = Date.parse('2026-11-08T18:27:00Z');
const run = (extra = {}) => ({
  id: 1, unit: 'lesson-notes-social.service', project_slug: 'lesson-notes', result: 'ok', repeat_count: 1,
  started_at: '2026-11-08T18:00:00Z', finished_at: '2026-11-08T18:00:01Z', ...extra,
});

describe('fmtDur', () => {
  it.each([
    [512, '0,5 s'], [42_000, '42 s'], [420_000, '7 min'], [4_320_000, '1 h 12 min'], [7_200_000, '2 h'],
    [null, '—'], [-5, '—'],
  ])('%s ms → %s', (ms, want) => expect(fmtDur(ms)).toBe(want));
});

describe('headline', () => {
  it('a GitHub job wins: it is what makes the noise', () => {
    const h = headline({
      gha_running: [{ unit: 'Nightly E2E / Desktop Chrome', project_slug: 'strummy', started_at: '2026-11-08T18:20:00Z', url: 'u' }],
      running: [run({ result: 'running', finished_at: null })],
    }, NOW);
    expect(h).toEqual({ tone: 'busy', project: 'strummy', text: 'Nightly E2E / Desktop Chrome · 7 min', url: 'u' });
  });

  it('falls back to a busy runner, then running timers, then calm', () => {
    expect(headline({ runners: [{ name: 'uwh-e2e', repo: 'o/strummy', busy: true }] }, NOW).text).toBe('runner uwh-e2e pracuje');
    const two = headline({ running: [run({ started_at: '2026-11-08T18:26:30Z', finished_at: null }), run()] }, NOW);
    expect(two.text).toBe('lesson-notes-social · 30 s (+1)');
    expect(headline({ running: [], runners: [] }, NOW)).toEqual({ tone: 'idle', text: 'Spokój — nic nie biegnie.' });
    expect(headline(null, NOW).tone).toBe('idle');
  });
});

describe('lanes', () => {
  const from = Date.parse('2026-11-08T00:00:00Z');
  const to = Date.parse('2026-11-09T00:00:00Z');

  it('groups by project, busiest first, with clamped fractions', () => {
    const ls = lanes([
      run({ id: 1 }),
      run({ id: 2, started_at: '2026-11-08T12:00:00Z', finished_at: '2026-11-08T12:00:00.5Z' }),
      run({ id: 3, project_slug: 'strummy', result: 'failed', started_at: '2026-11-07T23:00:00Z', finished_at: '2026-11-08T06:00:00Z' }),
      run({ id: 4, project_slug: null, started_at: '2026-11-08T23:30:00Z', finished_at: null }),
      run({ id: 5, started_at: '2026-11-06T00:00:00Z', finished_at: '2026-11-06T00:01:00Z' }),
    ], from, to);
    expect(ls.map((l) => l.project)).toEqual(['lesson-notes', 'inne', 'strummy']);
    const strummy = ls.find((l) => l.project === 'strummy');
    expect(strummy.items[0].x0).toBe(0);
    expect(strummy.items[0].x1).toBeCloseTo(0.25);
    expect(strummy.failed).toBe(1);
    const tiny = ls[0].items[1];
    expect(tiny.x1 - tiny.x0).toBeCloseTo(0.002);
    expect(ls.find((l) => l.project === 'inne').items[0].x1).toBe(1);
  });
});

describe('failing + filterRuns', () => {
  const runs = [
    run({ id: 1, unit: 'stano-backfill.service', project_slug: 'stano', result: 'failed', repeat_count: 3794 }),
    run({ id: 2, unit: 'szczerze-mowiac-replies.service', result: 'failed', started_at: '2026-11-08T18:00:00Z' }),
    run({ id: 3, unit: 'szczerze-mowiac-replies.service', result: 'failed', started_at: '2026-11-08T18:15:00Z' }),
    run({ id: 4, unit: 'szczerze-mowiac-replies.service', result: 'ok' }),
    run({ id: 5 }),
  ];

  it('ranks failing units by failures and keeps the latest run', () => {
    const f = failing(runs);
    expect(f.map((x) => [unitShort(x.unit), x.n, x.total])).toEqual([
      ['stano-backfill', 3794, 3794], ['szczerze-mowiac-replies', 2, 3],
    ]);
    expect(f[1].last.id).toBe(3);
  });

  it('filters by project, unit and failures', () => {
    expect(filterRuns(runs, { onlyFailed: true }).map((r) => r.id)).toEqual([1, 2, 3]);
    expect(filterRuns(runs, { project: 'stano' }).map((r) => r.id)).toEqual([1]);
    expect(filterRuns(runs, { unit: 'szczerze-mowiac-replies.service' }).map((r) => r.id)).toEqual([2, 3, 4]);
  });
});
