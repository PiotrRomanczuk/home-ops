/* Tests for the pure helpers in chat-pure.js.
 *
 * Catches the class of bug that bit us in item 6: silent loss of a
 * code hunk where the renderer didn't keep up with the result shape
 * (summarise jobs returning {summary, sections} instead of {response}).
 *
 * Run: cd ingest && npm test -- --run public/__tests__/chat-pure.test.mjs
 */
import { describe, expect, it } from 'vitest';
import '../chat-pure.js';

const { elapsedSec, jobToTurns, groupJobsToConversations } = globalThis.ChatPure;

describe('elapsedSec', () => {
  it('returns 0 when not started', () => {
    expect(elapsedSec({})).toBe(0);
    expect(elapsedSec({ started_at: null })).toBe(0);
  });

  it('counts seconds between started_at and finished_at', () => {
    expect(elapsedSec({
      started_at: '2026-06-08T12:00:00Z',
      finished_at: '2026-06-08T12:00:15Z',
    })).toBe(15);
  });

  it('uses Date.now() for running jobs', () => {
    const startedSecAgo = 5;
    const result = elapsedSec({
      started_at: new Date(Date.now() - startedSecAgo * 1000).toISOString(),
      finished_at: null,
    });
    expect(result).toBeGreaterThanOrEqual(4);
    expect(result).toBeLessThanOrEqual(6);
  });
});

describe('jobToTurns (generate shape)', () => {
  it('builds [user, assistant] from a completed generate', () => {
    const job = {
      id: 42,
      kind: 'generate',
      status: 'done',
      created_at: '2026-06-08T12:00:00Z',
      started_at: '2026-06-08T12:00:01Z',
      finished_at: '2026-06-08T12:00:10Z',
      payload: { model: 'qwen3:8b', prompt: 'why does my code panic', conversation_id: 'c1' },
      result: { response: 'because of an off-by-one', thinking: 'let me trace…', eval_count: 240 },
    };
    const [user, assistant] = jobToTurns(job);
    expect(user.text).toBe('why does my code panic');
    expect(assistant.text).toBe('because of an off-by-one');
    expect(assistant.thinking).toBe('let me trace…');
    expect(assistant.tokens).toBe(240);
    expect(assistant.status).toBe('done');
    expect(assistant._job_id).toBe(42);
    expect(assistant.sections_hint).toBeNull();
  });

  it('renders the running pulsing state when no result yet', () => {
    const [, assistant] = jobToTurns({
      id: 43,
      kind: 'generate',
      status: 'running',
      payload: { model: 'qwen3:8b', prompt: 'hi' },
      result: null,
    });
    expect(assistant.status).toBe('running');
    expect(assistant.text).toBe('');
  });

  it('surfaces last_error on failed jobs', () => {
    const [, assistant] = jobToTurns({
      id: 44,
      kind: 'generate',
      status: 'failed',
      payload: { prompt: 'hi' },
      result: null,
      last_error: 'connection refused',
    });
    expect(assistant.fail_reason).toBe('connection refused');
  });
});

describe('jobToTurns (summarise shape) — regression for item 6', () => {
  it('reads r.summary into text when r.response is absent', () => {
    const job = {
      id: 99,
      kind: 'summarise',
      status: 'done',
      payload: {
        model: 'qwen3:8b',
        chunks: ['day 1: …', 'day 2: …', 'day 3: …'],
        title: 'Weekly review · guitar-crm · 2026-W23',
        project: 'guitar-crm',
      },
      result: {
        summary: 'twilio rate limits dominated; reminder cron needs backoff',
        sections: [
          { chunk_idx: 0, partial: '…' },
          { chunk_idx: 1, partial: '…' },
          { chunk_idx: 2, partial: '…' },
        ],
      },
    };
    const [user, assistant] = jobToTurns(job);
    // The user-side falls back to title when no prompt is set (cron case).
    expect(user.text).toBe('Weekly review · guitar-crm · 2026-W23');
    // CRITICAL: summary fills the body, not blank. This is the bug we lost.
    expect(assistant.text).toBe('twilio rate limits dominated; reminder cron needs backoff');
    expect(assistant.sections_hint).toBe('3/3 sections');
  });

  it('shows N/M progress mid-stream', () => {
    const [, assistant] = jobToTurns({
      id: 100,
      kind: 'summarise',
      status: 'running',
      payload: { chunks: ['a', 'b', 'c', 'd', 'e'], title: 'partial run' },
      result: { summary: 'so far so good', sections: [{ chunk_idx: 0, partial: '…' }, { chunk_idx: 1, partial: '…' }], partial: true },
    });
    expect(assistant.text).toBe('so far so good');
    expect(assistant.sections_hint).toBe('2/5 sections');
    expect(assistant.status).toBe('running');
  });

  it('falls back to "summarise N chunks" when no title is set', () => {
    const [user] = jobToTurns({
      id: 101,
      kind: 'summarise',
      status: 'queued',
      payload: { chunks: ['x', 'y'] },
      result: null,
    });
    expect(user.text).toBe('summarise 2 chunks');
  });
});

describe('groupJobsToConversations', () => {
  it('groups by payload.conversation_id', () => {
    const jobs = [
      { id: 1, status: 'done', created_at: '2026-06-08T10:00:00Z', finished_at: '2026-06-08T10:00:05Z', payload: { conversation_id: 'A', prompt: 'first' }, result: { response: 'r1' } },
      { id: 2, status: 'done', created_at: '2026-06-08T10:01:00Z', finished_at: '2026-06-08T10:01:05Z', payload: { conversation_id: 'A', prompt: 'follow up' }, result: { response: 'r2' } },
      { id: 3, status: 'done', created_at: '2026-06-08T09:00:00Z', finished_at: '2026-06-08T09:00:05Z', payload: { conversation_id: 'B', prompt: 'unrelated' }, result: { response: 'r3' } },
    ];
    const convs = groupJobsToConversations(jobs);
    expect(convs).toHaveLength(2);
    const a = convs.find((c) => c.id === 'A');
    expect(a.turns).toHaveLength(4); // 2 jobs × [user, assistant]
    expect(a.turns[0].text).toBe('first');
    expect(a.turns[2].text).toBe('follow up');
  });

  it('falls back to job-N key when conversation_id is missing', () => {
    const convs = groupJobsToConversations([
      { id: 7, status: 'done', created_at: '2026-06-08T08:00:00Z', payload: { prompt: 'solo' }, result: { response: 'r' } },
    ]);
    expect(convs[0].id).toBe('job-7');
  });

  it('sorts conversations by updated DESC', () => {
    const convs = groupJobsToConversations([
      { id: 1, status: 'done', created_at: '2026-06-08T09:00:00Z', finished_at: '2026-06-08T09:00:05Z', payload: { conversation_id: 'old', prompt: 'p' }, result: {} },
      { id: 2, status: 'done', created_at: '2026-06-08T11:00:00Z', finished_at: '2026-06-08T11:00:05Z', payload: { conversation_id: 'new', prompt: 'p' }, result: {} },
    ]);
    expect(convs[0].id).toBe('new');
    expect(convs[1].id).toBe('old');
  });
});
