import { describe, expect, it } from 'vitest';
import { coerceDate, coerceTimestamp } from '../project-dates.ts';

describe('coerceDate (projects.last_commit)', () => {
  it('passes a clean date through without a warning', () => {
    expect(coerceDate('2026-10-17', 'last_commit', 'x')).toEqual({ value: '2026-10-17', warning: null });
  });

  it('keeps the leading date of "2026-09-27 (080f85a)" and warns', () => {
    const r = coerceDate('2026-09-27 (080f85a)', 'last_commit', 'd4-build-agent');
    expect(r.value).toBe('2026-09-27');
    expect(r.warning).toContain('d4-build-agent');
    expect(r.warning).toContain('trimmed');
  });

  it('stores NULL for a bare commit hash and warns', () => {
    const r = coerceDate('efaf7a9', 'last_commit', 'lesson-notes');
    expect(r.value).toBeNull();
    expect(r.warning).toContain('not a date');
  });

  it('rejects impossible calendar dates and digit runs', () => {
    expect(coerceDate('2026-02-30', 'last_commit', 'x').value).toBeNull();
    expect(coerceDate('2026-10-171', 'last_commit', 'x').value).toBeNull();
  });

  it('accepts a full timestamp silently and treats empty as absent', () => {
    expect(coerceDate('2026-10-17T08:00:00Z', 'last_commit', 'x')).toEqual({ value: '2026-10-17', warning: null });
    expect(coerceDate(null, 'last_commit', 'x')).toEqual({ value: null, warning: null });
    expect(coerceDate('', 'last_commit', 'x')).toEqual({ value: null, warning: null });
  });

  it('coerces non-string YAML values (numbers) instead of throwing', () => {
    expect(coerceDate(20261017, 'last_commit', 'x').value).toBeNull();
  });
});

describe('coerceTimestamp (projects.updated_at)', () => {
  it('passes ISO timestamps and drops junk', () => {
    expect(coerceTimestamp('2026-10-17T08:00:00+02:00', 'updated_at', 'x').value).toBe('2026-10-17T08:00:00+02:00');
    const bad = coerceTimestamp('yesterday', 'updated_at', 'x');
    expect(bad.value).toBeNull();
    expect(bad.warning).toContain('not a timestamp');
  });
});
