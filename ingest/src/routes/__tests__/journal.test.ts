/* Integration test for GET /api/journal/day + POST /api/journal (032): one
 * Warsaw day of the Mac from host_metrics (mac-watcher's top_* lists),
 * "proc" host_logs and claude_*, and the stored summary. Skips when
 * DATABASE_URL is unset. Needs migrations 001, 003 (no cron), 005, 016, 027, 032.
 */
import type { Hono } from 'hono';
import type pg from 'pg';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';

const dbUrl = process.env.DATABASE_URL;
const token = process.env.INGEST_TOKEN || 'ci-token';
const skip = !dbUrl;
const tokenHdr = { 'X-Ingest-Token': token, 'Content-Type': 'application/json' };
// biome-ignore lint/suspicious/noExplicitAny: test fixtures read loosely-typed JSON bodies
type Json = Record<string, any>;

let pool: pg.Pool;
let app: Hono;

beforeAll(async () => {
  if (skip) return;
  process.env.INGEST_TOKEN = token;
  process.env.LOGS_PASSWORD = 'ci-password';
  const pgMod = await import('pg');
  pool = new pgMod.default.Pool({ connectionString: dbUrl, max: 4 });
  const r = await pool.query(`SELECT to_regclass('public.day_journal') AS t`);
  if (!r.rows[0].t) throw new Error('apply migration 032 first');
  const { Hono: HonoCls } = await import('hono');
  app = new HonoCls();
  (await import('../journal.ts')).registerJournalRoutes(app);
});

afterAll(async () => {
  if (!skip && pool) await pool.end();
});

const metric = (ts: string, cpu: number, data: Json) =>
  pool.query(
    `INSERT INTO public.host_metrics (host, ts, cpu_pct, gpu_pct, mem_pct, net_rx_kbps, net_tx_kbps, data)
     VALUES ('mac', $1, $2, 10, 40, 1024, 0, $3)`,
    [ts, cpu, JSON.stringify({ interval_s: 30, ...data })],
  );

beforeEach(async () => {
  if (skip) return;
  await pool.query(`TRUNCATE public.host_metrics, public.claude_sessions, public.claude_events, public.day_journal`);
  await pool.query(`DELETE FROM public.host_logs WHERE host = 'mac'`);
  // 10:00 and 10:00:30 Warsaw = 09:00 UTC; one sample the day before must not count.
  const top = { top_cpu: [{ name: 'ollama', pct: 200 }], top_net: [{ name: 'ollama', rx: 1048576, tx: 0 }] };
  await metric('2026-11-14T09:00:00Z', 20, { ...top, top_mem: [{ name: 'Chrome', rss_mb: 900 }] });
  await metric('2026-11-14T09:00:30Z', 30, { ...top, top_mem: [{ name: 'Chrome', rss_mb: 1200 }] });
  await metric('2026-11-13T09:00:00Z', 99, top);
  const proc = (event: string, ts: string) =>
    pool.query(
      `INSERT INTO public.host_logs (host, source, level, message, data, ts) VALUES ('mac', 'agent:mac-watcher',
       'info', $1, $2, $3)`,
      [
        `proc ${event}: ollama`,
        JSON.stringify({ event, pid: 7, started: 1_794_669_000, name: 'ollama', reason: 'claude', session_id: 's1' }),
        ts,
      ],
    );
  await proc('start', '2026-11-14T09:00:00Z');
  await proc('stop', '2026-11-14T09:10:00Z');
  await pool.query(`INSERT INTO public.claude_sessions (host, session_id, title, project_slug, started_at, last_at)
    VALUES ('mac', 's1', 'OCR gazetek', 'home-ops', '2026-11-14T08:00:00Z', '2026-11-14T09:00:00Z'),
           ('elitedesk', 'n1', 'pr-review', 'strummy', '2026-11-14T02:00:00Z', '2026-11-14T02:10:00Z')`);
  await pool.query(`INSERT INTO public.claude_events (host, session_id, uuid, ts, kind, text) VALUES
    ('mac', 's1', 'p1', '2026-11-14T08:00:00Z', 'prompt', 'x'), ('mac', 's1', 'p2', '2026-11-14T08:02:00Z', 'prompt', 'y'),
    ('mac', 's1', 'b1', '2026-11-14T08:20:00Z', 'bash', 'ls'), ('mac', 's1', 'r1', '2026-11-14T08:21:00Z', 'pr', 'https://github.com/o/r/pull/1'),
    ('elitedesk', 'n1', 'q1', '2026-11-14T02:00:00Z', 'prompt', 'review')`);
});

const req = (method: string, path: string, body?: unknown) =>
  app.fetch(
    new Request(`http://x${path}`, { method, headers: tokenHdr, body: body ? JSON.stringify(body) : undefined }),
  );
const json = async (r: Response) => (await r.json()) as Json;

describe.skipIf(skip)('journal routes', () => {
  it('composes the Warsaw day: hours, apps, processes, Claude', async () => {
    const j = await json(await req('GET', '/api/journal/day?host=mac&day=2026-11-14'));
    expect(j.awake_min).toBe(1);
    expect(j.hours[10]).toMatchObject({ samples: 2, cpu: 25, rx_mb: 60 });
    expect(j.apps.cpu).toEqual([{ name: 'ollama', cpu_s: 120 }]);
    expect(j.apps.net).toEqual([{ name: 'ollama', mb: 2 }]);
    expect(j.apps.mem).toEqual([{ name: 'Chrome', rss_mb: 1200 }]);
    expect(j.procs).toHaveLength(1);
    expect(j.procs[0]).toMatchObject({ name: 'ollama', session_id: 's1', ended: '2026-11-14T09:10:00.000Z' });
    // Totals are the Mac's own time; sessions and projects span every host.
    expect(j.claude.totals).toEqual({ sessions: 1, prompts: 2, errors: 0, active_min: 10 });
    expect(j.claude.sessions.map((s: Json) => [s.host, s.title, s.prompts_day])).toEqual([
      ['elitedesk', 'pr-review', 1],
      ['mac', 'OCR gazetek', 2],
    ]);
    expect(j.claude.by_project.map((p: Json) => p.project_slug).sort()).toEqual(['home-ops', 'strummy']);
    expect(j.claude.prs).toEqual(['https://github.com/o/r/pull/1']);
    expect(j.journal).toBeNull();
  });

  it('stores the summary and returns it with the day', async () => {
    const post = await req('POST', '/api/journal', {
      host: 'mac',
      day: '2026-11-14',
      rollup: { a: 1 },
      summary_md: '## Dzień',
      model: 'qwen3.5:9b',
    });
    expect(post.status).toBe(200);
    await req('POST', '/api/journal', {
      host: 'mac',
      day: '2026-11-14',
      rollup: { a: 2 },
      summary_md: '## Dzień 2',
      model: 'm',
    });
    const j = await json(await req('GET', '/api/journal/day?host=mac&day=2026-11-14'));
    expect(j.journal.summary_md).toBe('## Dzień 2');
    const rows = (await pool.query(`SELECT rollup FROM public.day_journal`)).rows;
    expect(rows).toEqual([{ rollup: { a: 2 } }]);
  });

  it('rejects a bad body', async () => {
    expect((await req('POST', '/api/journal', { host: 'mac', day: 'x', rollup: {} })).status).toBe(400);
  });

  it('a host that may sleep is asleep when silent, not down (Dziś, digest)', async () => {
    const { hostStatus } = await import('../digest.ts');
    const row = {
      host: 'mac',
      last_metric_ts: '2026-11-14T00:00:00Z',
      last_event_ts: null,
      cpu_pct: 1,
      mem_pct: 1,
      disk_pct: 1,
    };
    const now = Date.parse('2026-11-14T12:00:00Z');
    expect(hostStatus({ ...row, sleeps: true }, now)).toBe('sleep');
    expect(hostStatus(row, now)).toBe('bad');
    const sleeps = await pool.query(`SELECT sleeps FROM public.host_profiles WHERE host = 'mac'`);
    expect(sleeps.rows).toEqual([{ sleeps: true }]);
  });
});
