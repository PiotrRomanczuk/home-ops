/* Integration test for processes (029) + GET /api/map: sync replaces the full
 * set (absent slugs are deleted), the list omits the diagram, the detail has
 * it, and the map folds projects + processes into one graph. Skips when
 * DATABASE_URL is unset. Needs migrations 005, 029.
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
});

afterAll(async () => {
  if (!skip && pool) await pool.end();
});

beforeEach(async () => {
  if (skip) return;
  await pool.query('TRUNCATE public.processes, public.projects');
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
