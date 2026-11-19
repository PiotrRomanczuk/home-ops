/* Tests for progress-pure.js — the Postęp tab's math.
 *
 * Run: cd ingest && npm test -- --run public/__tests__/progress-pure.test.mjs
 */
import { describe, expect, it } from 'vitest';
import '../progress-pure.js';

const { cell, level, gridMax, tiles, breakdown, stillLabel, weekLabel } = globalThis.ProgressPure;

const series = (extra = {}) => ({
  commits: [0, 4, 10], pr_merged: [0, 1, 2], deploys: [0, 0, 1], tasks_done: [1, 0, 3],
  runs_ok: [96, 96, 90], runs_failed: [0, 2, 0], ...extra,
});

describe('cell', () => {
  it('weights finished work in "all", counts raw signals in the other views', () => {
    const s = series();
    expect(cell(s, 'all', 2)).toBe(10 + 3 * 2 + 2 * 1 + 2 * 3);
    expect(cell(s, 'code', 1)).toBe(4 + 3);
    expect(cell(s, 'tasks', 0)).toBe(1);
    expect(cell(s, 'runs', 1)).toBe(98);
    expect(cell({}, 'all', 0)).toBe(0);
  });
});

describe('level + gridMax', () => {
  it('square-root steps of the busiest cell; zero stays empty', () => {
    expect([0, 1, 6, 7, 25, 57, 100].map((v) => level(v, 100))).toEqual([0, 1, 1, 2, 2, 4, 4]);
    expect(level(5, 0)).toBe(0);
    expect(gridMax([{ series: series() }, { series: series({ commits: [50, 0, 0] }) }], 'code', 3)).toBe(50);
  });
});

describe('tiles', () => {
  it('this week vs last week across projects', () => {
    const t = tiles([{ series: series() }, { series: series({ commits: [0, 1, 1] }) }], 3);
    expect(t.find((x) => x.key === 'commits')).toEqual({ key: 'commits', label: 'commity', now: 11, prev: 5, delta: 6 });
    expect(t.find((x) => x.key === 'runs_failed')).toMatchObject({ now: 0, prev: 4, delta: -4 });
  });
});

describe('labels', () => {
  it('breakdown lists non-zero signals', () => {
    expect(breakdown(series(), 1)).toBe('commity 4 · PR zmergowane 1 · rutyny ok 96 · rutyny błąd 2');
    expect(breakdown({}, 0)).toBe('bez ruchu');
  });
  it('still + week labels', () => {
    expect([null, 0, 1, 19].map(stillLabel)).toEqual([null, 'dziś', 'wczoraj', '19 dni']);
    expect(weekLabel('2026-08-03')).toBe('3.08');
  });
});
