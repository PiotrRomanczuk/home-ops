/* Integration test for daily briefs (022), GET /api/today and the tolerant
 * projects sync, against a real Postgres. Skips when DATABASE_URL is unset.
 * Needs migrations 001, 005, 013, 020, 021, 022.
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
  const r = await pool.query(`SELECT to_regclass('public.daily_briefs') AS b, to_regclass('public.board_tasks') AS t`);
  if (!r.rows[0].b || !r.rows[0].t) throw new Error('apply migrations 005, 013, 022 first');
  const { Hono: HonoCls } = await import('hono');
  app = new HonoCls();
  (await import('../briefs.ts')).registerBriefsRoutes(app);
  (await import('../today.ts')).registerTodayRoutes(app);
  (await import('../projects.ts')).registerProjectsRoutes(app);
});

afterAll(async () => {
  if (!skip && pool) await pool.end();
});

beforeEach(async () => {
  if (skip) return;
  await pool.query('DELETE FROM public.daily_briefs');
  await pool.query('DELETE FROM public.board_tasks');
  await pool.query('DELETE FROM public.projects');
  await pool.query(`DELETE FROM public.host_logs WHERE source = 'app:projects-sync'`);
});

const req = (method: string, path: string, body?: unknown, headers: Record<string, string> = tokenHdr) =>
  app.fetch(new Request(`http://x${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined }));
const json = async (r: Response) => (await r.json()) as Json;
const brief = (extra: Json = {}) => ({
  date: '2026-10-16',
  slot: 'morning',
  title: 'Plan dnia',
  body_md: '## Top 3\n- **one**',
  sources: ['calendar', 'planner'],
  generated_at: '2026-10-16T06:02:00Z',
  ...extra,
});

describe.skipIf(skip)('POST/GET /api/briefs', () => {
  it('requires the token and validates the contract', async () => {
    expect((await req('POST', '/api/briefs', brief(), { 'Content-Type': 'application/json' })).status).toBe(401);
    expect((await req('POST', '/api/briefs', brief({ slot: 'noon' }))).status).toBe(400);
    expect((await req('POST', '/api/briefs', brief({ date: '2026-02-30' }))).status).toBe(400);
    expect((await req('POST', '/api/briefs', brief({ body_md: 'x'.repeat(20_001) }))).status).toBe(400);
    expect((await req('POST', '/api/briefs', brief({ sources: [1] }))).status).toBe(400);
  });

  it('upserts on (date, slot): second post replaces, 201 then 200', async () => {
    const a = await req('POST', '/api/briefs', brief());
    expect(a.status).toBe(201);
    const b = await req('POST', '/api/briefs', brief({ title: 'Plan v2' }));
    expect(b.status).toBe(200);
    const list = await json(await req('GET', '/api/briefs?date=2026-10-16'));
    expect(list.briefs).toHaveLength(1);
    expect(list.briefs[0]).toMatchObject({ brief_date: '2026-10-16', slot: 'morning', title: 'Plan v2' });
    expect(list.briefs[0].sources).toEqual(['calendar', 'planner']);
  });

  it('latest prefers the evening brief of the newest day', async () => {
    await req('POST', '/api/briefs', brief({ date: '2026-10-15', slot: 'evening' }));
    await req('POST', '/api/briefs', brief({ slot: 'evening', title: 'Wieczór' }));
    await req('POST', '/api/briefs', brief());
    const latest = await json(await req('GET', '/api/briefs/latest'));
    expect(latest.brief).toMatchObject({ brief_date: '2026-10-16', slot: 'evening', title: 'Wieczór' });
    expect((await req('GET', '/api/briefs?slot=lunch')).status).toBe(400);
  });
});

describe.skipIf(skip)('GET /api/today', () => {
  it('returns the brief, Now tasks deduped across board + vault, and the attention lists', async () => {
    await req('POST', '/api/briefs', brief());
    await pool.query(
      `INSERT INTO public.projects (slug, title, status, now_md) VALUES
         ('home-ops', 'home-ops', 'hot', E'- [ ] Ship **today** tab\\n- [x] done thing\\n- [ ] Fix sync'),
         ('stano', 'Stano', 'dormant', E'- [ ] hidden')`,
    );
    await pool.query(`INSERT INTO public.board_tasks (slug, column_key, text, is_focus) VALUES
         ('home-ops', 'now', 'Ship today tab', true), ('home-ops', 'now', 'Old', false)`);
    await pool.query(`UPDATE public.board_tasks SET done = true WHERE text = 'Old'`);
    const r = await req('GET', '/api/today');
    expect(r.status).toBe(200);
    const t = await json(r);
    expect(t.brief).toMatchObject({ slot: 'morning', title: 'Plan dnia' });
    expect(t.tasks).toHaveLength(1);
    expect(t.tasks[0].slug).toBe('home-ops');
    expect(t.tasks[0].tasks.map((x: Json) => [x.text, x.source, x.is_focus])).toEqual([
      ['Ship today tab', 'board', true],
      ['Fix sync', 'vault', false],
    ]);
    for (const k of ['problems', 'hosts', 'decisions', 'cards']) expect(Array.isArray(t[k])).toBe(true);
    expect(JSON.stringify(t.decisions)).not.toContain('links');
  });

  it('answers with brief=null when nothing has been pulled yet', async () => {
    const t = await json(await req('GET', '/api/today'));
    expect(t.brief).toBeNull();
    expect(t.tasks).toEqual([]);
  });
});

describe.skipIf(skip)('POST /api/projects/sync tolerates bad dates', () => {
  it('stores the leading date or NULL instead of failing the transaction', async () => {
    const r = await req('POST', '/api/projects/sync', {
      projects: [
        { slug: 'd4-build-agent', status: 'warm', last_commit: '2026-09-27 (080f85a)' },
        { slug: 'lesson-notes', status: 'hot', last_commit: 'efaf7a9' },
        { slug: 'home-ops', status: 'hot', last_commit: '2026-10-17' },
      ],
    });
    expect(r.status).toBe(200);
    const body = await json(r);
    expect(body.upserted).toBe(3);
    expect(body.warnings).toHaveLength(2);
    const rows = await pool.query(`SELECT slug, last_commit::text AS lc FROM public.projects ORDER BY slug`);
    expect(rows.rows).toEqual([
      { slug: 'd4-build-agent', lc: '2026-09-27' },
      { slug: 'home-ops', lc: '2026-10-17' },
      { slug: 'lesson-notes', lc: null },
    ]);
    // Re-sync: the warning is logged to host_logs once per day, not every tick.
    await req('POST', '/api/projects/sync', { projects: [{ slug: 'lesson-notes', last_commit: 'efaf7a9' }] });
    const logs = await pool.query(`SELECT level FROM public.host_logs WHERE source = 'app:projects-sync'`);
    expect(logs.rows.map((x) => x.level)).toEqual(['warn', 'warn']);
  });
});
