import { describe, expect, it } from 'vitest';
import { parseEvent, parseEventsBody, parseSession, parseSessionsBody, warsawDays } from '../claude-model.ts';

const session = (extra: Record<string, unknown> = {}) => ({
  session_id: '1dfde554-1f0f-4607-a7e7-b605816af30f',
  surface: 'cli',
  cwd: '/Users/x/code',
  started_at: '2026-11-14T15:11:57Z',
  last_at: '2026-11-14T15:21:18Z',
  prompts_n: 3,
  tools: { Bash: 12, Edit: '2' },
  files_edited: ['/a.py', 7],
  ...extra,
});

describe('parseSession', () => {
  it('accepts a session, fills defaults, drops junk in counters and lists', () => {
    const r = parseSession(session());
    expect(typeof r).toBe('object');
    if (typeof r === 'string') return;
    expect(r.tools).toEqual({ Bash: 12, Edit: 0 });
    expect(r.files_edited).toEqual(['/a.py']);
    expect(r.cost_usd).toBeNull();
    expect(r.prs).toEqual([]);
  });

  it('unknown surface becomes unknown, missing times are rejected', () => {
    const r = parseSession(session({ surface: 'telepathy' }));
    expect(typeof r !== 'string' && r.surface).toBe('unknown');
    expect(parseSession(session({ last_at: 'nope' }))).toBe('invalid started_at/last_at');
    expect(parseSession(session({ session_id: '' }))).toBe('invalid session_id');
  });
});

describe('parseSessionsBody', () => {
  it('dedupes by session id (last wins) and reads live status', () => {
    const b = parseSessionsBody({
      host: 'mac',
      sessions: [session({ prompts_n: 1 }), session({ prompts_n: 9 }), { bad: true }],
      live: [{ session_id: 'x', status: 'busy' }, { status: 'idle' }],
    });
    if (typeof b === 'string') throw new Error(b);
    expect(b.items.map((s) => s.prompts_n)).toEqual([9]);
    expect(b.rejected).toEqual([{ index: 2, reason: 'invalid session_id' }]);
    expect(b.live).toEqual([{ session_id: 'x', status: 'busy' }]);
  });

  it('live is null when absent; host and arrays are required', () => {
    const b = parseSessionsBody({ host: 'mac', sessions: [] });
    expect(typeof b !== 'string' && b.live).toBeNull();
    expect(parseSessionsBody({ sessions: [] })).toBe('invalid host');
    expect(parseSessionsBody({ host: 'mac' })).toBe('sessions must be an array');
  });
});

describe('parseEvent', () => {
  it('accepts known kinds, caps text', () => {
    const e = parseEvent({
      session_id: 's',
      uuid: 'u',
      ts: '2026-11-14T10:00:00Z',
      kind: 'bash',
      text: 'x'.repeat(5000),
    });
    expect(typeof e !== 'string' && e.text.length).toBe(4000);
    expect(parseEvent({ session_id: 's', uuid: 'u', ts: '2026-11-14T10:00:00Z', kind: 'tweet' })).toBe('invalid kind');
  });

  it('batch caps at 500', () => {
    const many = Array.from({ length: 501 }, () => ({}));
    expect(parseEventsBody({ host: 'mac', events: many })).toBe('at most 500 events per request');
  });
});

describe('warsawDays', () => {
  it('maps UTC instants to Warsaw calendar days', () => {
    expect(warsawDays(['2026-11-14T23:30:00Z', '2026-11-14T10:00:00Z', 'bad'])).toEqual(['2026-11-14', '2026-11-15']);
  });
});
