import { describe, expect, it } from 'vitest';
import { dedupeRuns, parseRun, parseRunsBatch, parseSnapshot } from '../activity-model.ts';

const run = (extra: Record<string, unknown> = {}) => ({
  kind: 'timer',
  unit: 'lesson-notes-social.service',
  invocation_id: 'aa80f54676de426bb00eccfbb0335478',
  project_slug: 'lesson-notes',
  started_at: '2026-11-08T18:00:00Z',
  finished_at: '2026-11-08T18:00:01Z',
  result: 'ok',
  cpu_ms: 664,
  mem_peak_mb: 88,
  log_tail: ['{"message":"No pending posts"}'],
  ...extra,
});

describe('parseRun', () => {
  it('accepts a finished timer run and fills defaults', () => {
    const r = parseRun(run());
    expect(typeof r).toBe('object');
    if (typeof r === 'string') return;
    expect(r.repeat_count).toBe(1);
    expect(r.exit_code).toBeNull();
    expect(r.log_tail).toEqual(['{"message":"No pending posts"}']);
  });

  it.each([
    ['kind', 'cron', 'invalid kind'],
    ['unit', '', 'invalid unit'],
    ['invocation_id', 42, 'invalid invocation_id'],
    ['started_at', 'yesterday', 'invalid started_at'],
    ['result', 'done', 'invalid result'],
  ])('rejects a bad %s', (field, value, reason) => {
    expect(parseRun(run({ [field]: value }))).toBe(reason);
  });

  it('keeps only the last 40 log lines and trims long ones', () => {
    const lines = Array.from({ length: 60 }, (_, i) => `line ${i} ${'x'.repeat(i === 59 ? 900 : 0)}`);
    const r = parseRun(run({ log_tail: [...lines, 7, null] }));
    if (typeof r === 'string') throw new Error(r);
    expect(r.log_tail).toHaveLength(40);
    expect(r.log_tail[0]).toBe('line 20 ');
    expect(r.log_tail[39]?.length).toBe(500);
  });

  it('never lets repeat_count drop below 1', () => {
    const r = parseRun(run({ repeat_count: 0 }));
    if (typeof r === 'string') throw new Error(r);
    expect(r.repeat_count).toBe(1);
  });
});

describe('parseRunsBatch', () => {
  it('reports bad rows by index and keeps the good ones', () => {
    const b = parseRunsBatch({ host: 'elitedesk', runs: [run(), run({ result: '?' })] });
    if (typeof b === 'string') throw new Error(b);
    expect(b.runs).toHaveLength(1);
    expect(b.rejected).toEqual([{ index: 1, reason: 'invalid result' }]);
  });

  it('rejects a body without host or runs', () => {
    expect(parseRunsBatch({ runs: [] })).toBe('invalid host');
    expect(parseRunsBatch({ host: 'elitedesk' })).toBe('runs must be an array');
  });
});

describe('dedupeRuns', () => {
  it('keeps the last version of a run sent twice in one batch', () => {
    const a = parseRun(run({ result: 'running', finished_at: null }));
    const b = parseRun(run());
    if (typeof a === 'string' || typeof b === 'string') throw new Error('fixture');
    expect(dedupeRuns([a, b])).toEqual([b]);
  });
});

describe('parseSnapshot', () => {
  it('accepts an object snapshot and rejects oversized ones', () => {
    expect(parseSnapshot({ host: 'elitedesk', snapshot: { running: [] } })).toEqual({
      host: 'elitedesk',
      snapshot: { running: [] },
    });
    expect(parseSnapshot({ host: 'elitedesk', snapshot: { blob: 'x'.repeat(70_000) } })).toBe('snapshot too large');
    expect(parseSnapshot({ host: 'elitedesk', snapshot: [] })).toBe('snapshot must be an object');
  });
});
