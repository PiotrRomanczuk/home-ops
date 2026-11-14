import { describe, expect, it } from 'vitest';
import {
  clockOn,
  fmtMin,
  fmtSec,
  type JournalSession,
  lanes,
  minuteOfDay,
  shiftDay,
  summarySections,
  today,
} from './journal';

const session = (over: Partial<JournalSession>): JournalSession => ({
  host: 'mac',
  session_id: 's',
  title: null,
  project_slug: null,
  surface: 'cli',
  cwd: null,
  git_branch: null,
  cost_usd: null,
  prs: [],
  live_status: null,
  first_ts: '2026-11-14T08:00:00Z',
  last_ts: '2026-11-14T09:00:00Z',
  prompts_day: 1,
  errors_day: 0,
  actions_day: 0,
  active_min: 10,
  ...over,
});

describe('day arithmetic in Warsaw time', () => {
  it('minute of day follows Warsaw, not UTC (CET in November)', () => {
    expect(minuteOfDay('2026-11-14T08:30:00Z')).toBe(9 * 60 + 30);
    expect(minuteOfDay('2026-11-14T23:30:00Z')).toBe(30); // already the 15th in Warsaw
  });

  it('today and shiftDay', () => {
    expect(today(new Date('2026-11-14T23:30:00Z'))).toBe('2026-11-15');
    expect(shiftDay('2026-11-01', -1)).toBe('2026-10-31');
    expect(shiftDay('2026-12-31', 1)).toBe('2027-01-01');
  });

  it('fmtMin / fmtSec', () => {
    expect(fmtMin(5)).toBe('5 min');
    expect(fmtMin(125)).toBe('2 h 05 min');
    expect(fmtSec(42)).toBe('42 s');
    expect(fmtSec(600)).toBe('10 min');
  });

  it('clockOn dates instants from another day', () => {
    expect(clockOn('2026-11-14T08:30:00Z', '2026-11-14')).toBe('09:30');
    expect(clockOn('2026-11-13T21:15:00Z', '2026-11-14')).toBe('13.11 22:15');
    expect(clockOn(null, '2026-11-14')).toBe('—');
  });
});

describe('lanes', () => {
  it('one lane per project, busiest first, unknown project named, tiny sessions stay visible', () => {
    const out = lanes([
      session({ session_id: 'a', project_slug: 'home-ops', active_min: 20 }),
      session({ session_id: 'b', project_slug: null, active_min: 5 }),
      session({
        session_id: 'c',
        project_slug: 'home-ops',
        active_min: 15,
        first_ts: '2026-11-14T12:00:00Z',
        last_ts: '2026-11-14T12:00:00Z',
      }),
    ]);
    expect(out.map((l) => [l.project, l.activeMin, l.segments.length])).toEqual([
      ['home-ops', 35, 2],
      ['(bez projektu)', 5, 1],
    ]);
    const tiny = out[0]?.segments[1];
    expect(tiny && tiny.to - tiny.from).toBe(5);
  });
});

describe('summarySections', () => {
  it('splits the model note into titled sections of plain lines', () => {
    const md = '## Dzień\nDużo pracy nad **home-ops**.\n\n## Co dalej\n- home-ops: wdrożyć 032\n* strummy: karnety';
    expect(summarySections(md)).toEqual([
      { title: 'Dzień', lines: ['Dużo pracy nad home-ops.'] },
      { title: 'Co dalej', lines: ['home-ops: wdrożyć 032', 'strummy: karnety'] },
    ]);
    expect(summarySections(null)).toEqual([]);
    expect(summarySections('bez nagłówka')).toEqual([{ title: 'Podsumowanie', lines: ['bez nagłówka'] }]);
  });
});
