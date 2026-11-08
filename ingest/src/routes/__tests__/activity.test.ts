/* Integration test for unit_runs / activity_now (026): the upsert contract of
 * POST /api/activity/runs (a later post never erases what an earlier one
 * knew), the snapshot overwrite, and the GET filters + 24 h summary.
 * Skips when DATABASE_URL is unset. Needs migration 026 (without its
 * trailing cron.schedule on stock postgres).
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
  const r = await pool.query(`SELECT to_regclass('public.unit_runs') AS t`);
  if (!r.rows[0].t) throw new Error('apply migration 026 first');
  const { Hono: HonoCls } = await import('hono');
  app = new HonoCls();
  (await import('../activity.ts')).registerActivityRoutes(app);
});

afterAll(async () => {
  if (!skip && pool) await pool.end();
});

beforeEach(async () => {
  if (skip) return;
  await pool.query('TRUNCATE public.unit_runs, public.activity_now');
});

const req = (method: string, path: string, body?: unknown, headers: Record<string, string> = tokenHdr) =>
  app.fetch(new Request(`http://x${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined }));
const json = async (r: Response) => (await r.json()) as Json;
const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();
const run = (extra: Json = {}) => ({
  kind: 'timer',
  unit: 'seo-collect.service',
  invocation_id: 'inv-1',
  project_slug: 'gitara-lekcje',
  started_at: ago(10),
  result: 'running',
  ...extra,
});
const postRuns = (runs: Json[]) => req('POST', '/api/activity/runs', { host: 'elitedesk', runs });

describe.skipIf(skip)('activity routes', () => {
  it('requires the ingest token to write', async () => {
    const r = await req('POST', '/api/activity/runs', { host: 'elitedesk', runs: [run()] }, {});
    expect(r.status).toBe(401);
  });

  it('finishing a run keeps what the first post knew', async () => {
    await postRuns([run({ log_tail: ['starting'] })]);
    const r = await postRuns([run({ result: 'ok', finished_at: ago(9), cpu_ms: 1200, project_slug: null })]);
    expect(await json(r)).toMatchObject({ upserted: 1, rejected: [] });

    const list = await json(await req('GET', '/api/activity/runs'));
    expect(list.runs).toHaveLength(1);
    expect(list.runs[0]).toMatchObject({ result: 'ok', cpu_ms: '1200', project_slug: 'gitara-lekcje' });
    expect(list.runs[0].log_tail).toBeUndefined();

    const one = await json(await req('GET', `/api/activity/runs/${list.runs[0].id}`));
    expect(one.run.log_tail).toEqual(['starting']);
  });

  it('a restart loop grows repeat_count and never shrinks it', async () => {
    await postRuns([run({ unit: 'stano-backfill.service', result: 'failed', repeat_count: 5 })]);
    await postRuns([run({ unit: 'stano-backfill.service', result: 'failed', repeat_count: 3 })]);
    const now = await json(await req('GET', '/api/activity/now'));
    expect(now.summary_24h).toMatchObject({ runs: 1, failed: 5, failing_units: ['stano-backfill.service'] });
  });

  it('filters by project and result, and hides runs older than since_h', async () => {
    await postRuns([
      run({ invocation_id: 'a', result: 'ok', finished_at: ago(9) }),
      run({ invocation_id: 'b', project_slug: 'strummy', kind: 'gha', unit: 'Nightly E2E / Desktop Chrome' }),
      run({ invocation_id: 'c', result: 'failed', started_at: ago(60 * 30) }),
    ]);
    const byProject = await json(await req('GET', '/api/activity/runs?project=strummy'));
    expect(byProject.runs.map((r: Json) => r.invocation_id)).toEqual(['b']);
    const failed = await json(await req('GET', '/api/activity/runs?result=failed&since_h=48'));
    expect(failed.runs.map((r: Json) => r.invocation_id)).toEqual(['c']);
    const day = await json(await req('GET', '/api/activity/runs'));
    expect(day.runs).toHaveLength(2);
  });

  it('a crash loop that began before the window but still fails is in it', async () => {
    await postRuns([
      run({
        invocation_id: 'loop',
        unit: 'stano-backfill.service',
        result: 'failed',
        started_at: ago(60 * 24 * 6),
        finished_at: ago(1),
        repeat_count: 9000,
      }),
    ]);
    const day = await json(await req('GET', '/api/activity/runs?result=failed'));
    expect(day.runs.map((r: Json) => r.invocation_id)).toEqual(['loop']);
    const now = await json(await req('GET', '/api/activity/now'));
    expect(now.summary_24h).toMatchObject({ failed: 9000, failing_units: ['stano-backfill.service'] });
  });

  it('the snapshot is one row per host, overwritten', async () => {
    await req('POST', '/api/activity/now', { host: 'elitedesk', snapshot: { running: ['a'] } });
    await req('POST', '/api/activity/now', { host: 'elitedesk', snapshot: { running: [] } });
    const now = await json(await req('GET', '/api/activity/now'));
    expect(now.hosts).toHaveLength(1);
    expect(now.hosts[0].snapshot).toEqual({ running: [] });
  });

  it('rejects a malformed snapshot', async () => {
    const r = await req('POST', '/api/activity/now', { host: 'elitedesk', snapshot: 'busy' });
    expect(r.status).toBe(400);
  });
});
