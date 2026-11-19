/* Integration test for processes (029) + GET /api/map + GET /api/pressure:
 * sync replaces the full set (absent slugs are deleted), the list omits the
 * diagram, the detail has it, the map folds projects + processes into one
 * graph, and pressure reads vault tasks, repo_meta and host_logs. Skips when
 * DATABASE_URL is unset. Needs migrations 001, 005, 016, 029.
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
  const r = await pool.query(`SELECT to_regclass('public.processes') AS t`);
  if (!r.rows[0].t) throw new Error('apply migration 029 first');
  const { Hono: HonoCls } = await import('hono');
  app = new HonoCls();
  (await import('../processes.ts')).registerProcessesRoutes(app);
  (await import('../map.ts')).registerMapRoutes(app);
  (await import('../pressure.ts')).registerPressureRoutes(app);
});

afterAll(async () => {
  if (!skip && pool) await pool.end();
});

beforeEach(async () => {
  if (skip) return;
  await pool.query('TRUNCATE public.processes, public.projects, public.host_logs');
  await pool.query(`INSERT INTO public.projects (slug, title, status, raw_frontmatter) VALUES
    ('job-radar', 'job-radar', 'hot', '{"depends_on":["home-ops"],"feeds":["vectordigital"],"hosts":["uwh"]}'),
    ('home-ops', 'home-ops', 'hot', '{"hosts":["uwh"]}')`);
});

const req = (method: string, path: string, body?: unknown, headers: Record<string, string> = tokenHdr) =>
  app.fetch(new Request(`http://x${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined }));
const json = async (r: Response) => (await r.json()) as Json;
const proc = (slug: string, lanes: string[]) => ({
  slug,
  title: slug.toUpperCase(),
  projects: lanes,
  lanes,
  bpmn_xml: `<bpmn:definitions id="${slug}"/>`,
  bpmn_hash: 'h',
  warnings: [],
});

describe.skipIf(skip)('processes + map', () => {
  it('sync needs the ingest token', async () => {
    const r = await req('POST', '/api/processes/sync', { processes: [] }, { 'Content-Type': 'application/json' });
    expect(r.status).toBe(401);
  });

  it('sync upserts the full set and deletes absent slugs', async () => {
    let r = await req('POST', '/api/processes/sync', { processes: [proc('a', ['job-radar']), proc('b', [])] });
    expect(await json(r)).toEqual({ upserted: 2, removed: 0 });
    r = await req('POST', '/api/processes/sync', { processes: [proc('a', ['job-radar', 'home-ops'])] });
    expect(await json(r)).toEqual({ upserted: 1, removed: 1 });
    const list = await json(await req('GET', '/api/processes'));
    expect(list.processes.map((p: Json) => p.slug)).toEqual(['a']);
    expect(list.processes[0].lanes).toEqual(['job-radar', 'home-ops']);
    expect(list.processes[0]).not.toHaveProperty('bpmn_xml');
  });

  it('detail returns the diagram, 404 for unknown', async () => {
    await req('POST', '/api/processes/sync', { processes: [proc('a', [])] });
    expect((await json(await req('GET', '/api/processes/a'))).process.bpmn_xml).toBe('<bpmn:definitions id="a"/>');
    expect((await req('GET', '/api/processes/nope')).status).toBe(404);
  });

  it('rejects a malformed payload without touching the table', async () => {
    await req('POST', '/api/processes/sync', { processes: [proc('a', [])] });
    const r = await req('POST', '/api/processes/sync', { processes: [{ slug: 'bad slug' }] });
    expect(r.status).toBe(400);
    expect((await json(await req('GET', '/api/processes'))).processes).toHaveLength(1);
  });

  it('map joins projects, externals, hosts and processes', async () => {
    await req('POST', '/api/processes/sync', { processes: [proc('lead-pipeline', ['job-radar'])] });
    const map = await json(await req('GET', '/api/map'));
    const ids = map.nodes.map((n: Json) => n.id);
    expect(ids).toEqual(expect.arrayContaining(['job-radar', 'home-ops', 'vectordigital', 'host:uwh']));
    expect(map.nodes.find((n: Json) => n.id === 'home-ops').dependents).toEqual(['job-radar']);
    expect(map.processes).toEqual([
      { slug: 'lead-pipeline', title: 'LEAD-PIPELINE', lanes: ['job-radar'], warnings: [] },
    ]);
  });
});

describe.skipIf(skip)('pressure', () => {
  const log = (source: string, level: string, message: string, minutesAgo: number) =>
    pool.query(
      `INSERT INTO public.host_logs (host, source, level, message, ts)
       VALUES ('rpi', $1, $2, $3, now() - make_interval(mins => $4))`,
      [source, level, message, minutesAgo],
    );

  it('ranks by vault tasks, repo_meta and runtime, with blast radius', async () => {
    await pool.query(`UPDATE public.projects SET now_md = '- [ ] 🔴 S fix', repo_meta =
      '{"issues":{"open":2,"bugs":1},"gaps":{"count":3,"ids":["HO-1"]},"ci":{"conclusion":"failure"}}'
      WHERE slug = 'home-ops'`);
    await log('app:home-ops', 'error', 'db timeout after 30s', 10);
    await log('app:home-ops', 'error', 'db timeout after 31s', 5); // same pattern
    await log('app:home-ops', 'error', 'gpu queue stalled for 9h', 5); // muted in the digest
    await log('app:job-radar', 'error', 'deploy unreachable from rpi: https://x (503)', 30);
    await log('app:job-radar', 'info', 'deploy reachable again from rpi: https://x (was down ~5m)', 20);
    await log('app:home-ops', 'error', 'deploy unreachable from rpi: https://y (no response)', 1);
    const body = await json(await req('GET', '/api/pressure'));
    const [top, second] = body.projects;
    expect(top.slug).toBe('home-ops');
    expect(top.parts.runtime).toEqual({ errorPatterns: 1, ciFailed: true, down: true, points: 12 });
    expect(top.parts.issues.points).toBe(4);
    expect(top.dependents).toEqual(['job-radar']);
    // tasks 4 + gaps 3 + issues 4 + runtime 12 = 23, × blast 1.25
    expect(top.score).toBe(28.8);
    expect(second).toMatchObject({ slug: 'job-radar', score: 0 });
    expect(second.parts.runtime.down).toBe(false);
    expect(body.weights.red).toBe(4);
  });

  it('puts the score on map nodes', async () => {
    await pool.query(`UPDATE public.projects SET pain_md = '- slow' WHERE slug = 'job-radar'`);
    const map = await json(await req('GET', '/api/map'));
    expect(map.nodes.find((n: Json) => n.id === 'job-radar').pressure).toBe(2);
    expect(map.nodes.find((n: Json) => n.id === 'host:uwh').pressure).toBeNull();
  });
});
