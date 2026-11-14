import { describe, expect, it } from 'vitest';
import { buildJournal, mergeProcs, parseJournalPost } from '../journal-model.ts';

const START = 1_794_669_000; // epoch seconds, as mac-watcher sends create_time

describe('mergeProcs', () => {
  it('joins start and stop of one run, keeps a still-running one open', () => {
    const runs = mergeProcs([
      {
        ts: new Date('2026-11-14T15:20:00Z'),
        data: {
          event: 'start',
          pid: 7,
          started: START,
          name: 'ollama',
          reason: 'claude',
          session_id: 's1',
          net_bytes: 0,
        },
      },
      {
        ts: '2026-11-14T15:40:00Z',
        data: {
          event: 'stop',
          pid: 7,
          started: START,
          name: 'ollama',
          duration_s: 1200,
          cpu_s: 33.6,
          net_bytes: 20 * 1048576,
        },
      },
      {
        ts: '2026-11-14T16:00:00Z',
        data: { event: 'start', pid: 9, started: START + 10, name: 'pytest', reason: 'cpu' },
      },
    ]);
    expect(runs).toHaveLength(2);
    expect(runs[0]).toMatchObject({
      name: 'ollama',
      session_id: 's1',
      ended: '2026-11-14T15:40:00Z',
      duration_s: 1200,
      cpu_s: 34,
      net_mb: 20,
    });
    expect(runs[0]?.started).toBe(new Date(START * 1000).toISOString());
    expect(runs[1]).toMatchObject({ name: 'pytest', ended: null });
  });
});

describe('buildJournal', () => {
  it('pads hours, counts awake minutes, ranks apps, defaults Claude totals', () => {
    const j = buildJournal({
      host: 'mac',
      day: '2026-11-14',
      hours: [{ hour: 9, samples: 120, seconds: 3600, cpu: 12, gpu: 3, mem_max: 40, rx_mb: 5, tx_mb: 1 }],
      apps: [
        { kind: 'cpu', name: 'iTerm2', value: 100 },
        { kind: 'cpu', name: 'ollama', value: 900 },
        { kind: 'net', name: 'ollama', value: 0 },
        { kind: 'mem', name: 'Chrome', value: 2048 },
      ],
      procs: [],
      sessions: [],
      totals: undefined,
      byProject: [],
      prs: [{ url: 'https://github.com/o/r/pull/1' }],
      journal: undefined,
    });
    expect(j.hours).toHaveLength(24);
    expect(j.hours[9]?.samples).toBe(120);
    expect(j.awake_min).toBe(60);
    expect(j.apps.cpu.map((a) => a.name)).toEqual(['ollama', 'iTerm2']);
    expect(j.apps.net).toEqual([]);
    expect(j.claude.totals).toEqual({ sessions: 0, prompts: 0, errors: 0, active_min: 0 });
    expect(j.claude.prs).toEqual(['https://github.com/o/r/pull/1']);
    expect(j.journal).toBeNull();
  });
});

describe('parseJournalPost', () => {
  it('validates host, day and rollup', () => {
    expect(
      parseJournalPost({ host: 'mac', day: '2026-11-14', rollup: {}, summary_md: '## Dzień', model: 'm' }),
    ).toEqual({
      host: 'mac',
      day: '2026-11-14',
      rollup: {},
      summary_md: '## Dzień',
      model: 'm',
    });
    expect(parseJournalPost({ host: 'mac', day: '14.11', rollup: {} })).toBe('invalid day');
    expect(parseJournalPost({ host: 'mac', day: '2026-11-14', rollup: [] })).toBe('rollup must be an object');
  });
});
