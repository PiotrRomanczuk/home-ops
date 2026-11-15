/* Integration test for project_signals (027) + GET /api/progress: replace
 * mode wipes the window before writing (a project with zero commits now
 * really reads zero), add mode accumulates, and the GET folds signals and
 * unit_runs (026) into weekly series. Skips when DATABASE_URL is unset.
 * Needs migrations 005, 016, 026 (no cron), 027.
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
  const r = await pool.query(`SELECT to_regclass('public.project_signals') AS t`);
  if (!r.rows[0].t) throw new Error('apply migration 027 first');
  const { Hono: HonoCls } = await import('hono');
  app = new HonoCls();
  (await import('../progress.ts')).registerProgressRoutes(app);
});

afterAll(async () => {
  if (!skip && pool) await pool.end();
});

beforeEach(async () => {
  if (skip) return;
  await pool.query('TRUNCATE public.project_signals, public.unit_runs, public.projects');
  await pool.query(`INSERT INTO public.projects (slug, title, status, raw_frontmatter)
    VALUES ('strummy', 'Strummy', 'hot', '{"health":"🟠"}'), ('home-ops', 'home-ops', 'hot', '{}')`);
});

const req = (method: string, path: string, body?: unknown, headers: Record<string, string> = tokenHdr) =>
  app.fetch(new Request(`http://x${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined }));
const json = async (r: Response) => (await r.json()) as Json;
const day = (back: number) => new Date(Date.now() - back * 86_400_000).toISOString().slice(0, 10);
const sig = (slug: string, signal: string, n: number, back = 0) => ({ project_slug: slug, day: day(back), signal, n });

describe.skipIf(skip)('progress routes', () => {
  it('requires the ingest token to write', async () => {
    expect((await req('POST', '/api/progress/signals', { rows: [] }, {})).status).toBe(401);
  });

  it('add mode accumulates, replace mode wipes the window first', async () => {
    await req('POST', '/api/progress/signals', { rows: [sig('home-ops', 'tasks_done', 2)] });
    await req('POST', '/api/progress/signals', {
      rows: [sig('home-ops', 'tasks_done', 1), sig('home-ops', 'tasks_done', 1)],
    });
    const replace = { from: day(84), to: day(0), projects: ['strummy', 'home-ops'], signals: ['commits'] };
    await req('POST', '/api/progress/signals', {
      rows: [sig('strummy', 'commits', 5), sig('home-ops', 'commits', 3)],
      replace,
    });
    const r = await req('POST', '/api/progress/signals', { rows: [sig('strummy', 'commits', 7)], replace });
    expect(await json(r)).toEqual({ written: 1, mode: 'replace' });

    const all = await pool.query(`SELECT project_slug, signal, n FROM public.project_signals ORDER BY 1, 2`);
    expect(all.rows).toEqual([
      { project_slug: 'home-ops', signal: 'tasks_done', n: 4 },
      { project_slug: 'strummy', signal: 'commits', n: 7 },
    ]);
  });

  it('GET folds signals and routine runs into weekly series', async () => {
    await req('POST', '/api/progress/signals', {
      rows: [sig('strummy', 'commits', 12), sig('strummy', 'pr_merged', 2)],
    });
    await pool.query(`INSERT INTO public.unit_runs (host, kind, unit, invocation_id, project_slug, started_at, result, repeat_count)
      VALUES ('elitedesk', 'gha', 'Nightly E2E / Desktop Chrome', 'gha:1', 'strummy', now(), 'ok', 1),
             ('elitedesk', 'timer', 'x.service', 'i2', 'strummy', now(), 'failed', 3)`);
    const p = await json(await req('GET', '/api/progress?weeks=4'));
    expect(p.weeks).toHaveLength(4);
    const s = p.projects.find((x: Json) => x.slug === 'strummy');
    expect(s.series.commits.at(-1)).toBe(12);
    expect(s.series.pr_merged.at(-1)).toBe(2);
    expect(s.series.runs_ok.at(-1)).toBe(1);
    expect(s.series.runs_failed.at(-1)).toBe(3);
    expect(s).toMatchObject({ health: '🟠', days_still: 0, stalled: false });
    expect(p.projects.find((x: Json) => x.slug === 'home-ops')).toMatchObject({ last_moved: null, stalled: true });
  });

  it('rejects a malformed batch without writing anything', async () => {
    const r = await req('POST', '/api/progress/signals', {
      rows: [sig('strummy', 'commits', 1), sig('strummy', 'stars', 1)],
    });
    expect(r.status).toBe(400);
    expect((await pool.query('SELECT count(*)::int AS n FROM public.project_signals')).rows[0].n).toBe(0);
  });
});
