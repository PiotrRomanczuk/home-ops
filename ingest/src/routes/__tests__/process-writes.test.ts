/* Integration test for process_writes (030): a viewer queues a BPMN save for
 * a known process, planner-sync (token) drains and marks it, the browser
 * polls the status. Skips when DATABASE_URL is unset. Needs 029, 030.
 */
import type { Hono } from 'hono';
import type pg from 'pg';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';

const dbUrl = process.env.DATABASE_URL;
const token = process.env.INGEST_TOKEN || 'ci-token';
const skip = !dbUrl;
const tokenHdr = { 'X-Ingest-Token': token, 'Content-Type': 'application/json' };
const anon = { 'Content-Type': 'application/json' };
// biome-ignore lint/suspicious/noExplicitAny: test fixtures read loosely-typed JSON bodies
type Json = Record<string, any>;

let pool: pg.Pool;
let app: Hono;
const HASH = 'a'.repeat(64);
const XML = '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="D"/>';

beforeAll(async () => {
  if (skip) return;
  process.env.INGEST_TOKEN = token;
  process.env.LOGS_PASSWORD = 'ci-password';
  const pgMod = await import('pg');
  pool = new pgMod.default.Pool({ connectionString: dbUrl, max: 4 });
  const r = await pool.query(`SELECT to_regclass('public.process_writes') AS t`);
  if (!r.rows[0].t) throw new Error('apply migration 030 first');
  const { Hono: HonoCls } = await import('hono');
  app = new HonoCls();
  (await import('../processes.ts')).registerProcessesRoutes(app);
  (await import('../process-writes.ts')).registerProcessWritesRoutes(app);
});

afterAll(async () => {
  if (!skip && pool) await pool.end();
});

beforeEach(async () => {
  if (skip) return;
  await pool.query('TRUNCATE public.process_writes, public.processes');
  await pool.query(`INSERT INTO public.processes (slug, title, bpmn_hash) VALUES ('pr-flow', 'PR', $1)`, [HASH]);
});

const req = (method: string, path: string, body?: unknown, headers: Record<string, string> = tokenHdr) =>
  app.fetch(new Request(`http://x${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined }));
const json = async (r: Response) => (await r.json()) as Json;
const save = (body: unknown, headers: Record<string, string> = tokenHdr) =>
  req('POST', '/api/processes/pr-flow/writes', body, headers);

describe.skipIf(skip)('process writes', () => {
  it('needs a viewer or the token to save', async () => {
    expect((await save({ bpmn_xml: XML, base_hash: HASH }, anon)).status).toBe(401);
  });

  it('validates the payload and the process', async () => {
    expect((await save({ bpmn_xml: '<html/>', base_hash: HASH })).status).toBe(400);
    expect((await save({ bpmn_xml: XML, base_hash: 'nope' })).status).toBe(400);
    const r = await req('POST', '/api/processes/missing/writes', { bpmn_xml: XML, base_hash: HASH });
    expect(r.status).toBe(404);
  });

  it('queues, drains, marks once, and the browser sees the outcome', async () => {
    const queued = await save({ bpmn_xml: XML, base_hash: HASH });
    expect(queued.status).toBe(202);
    const { write } = await json(queued);
    expect(write).toMatchObject({ slug: 'pr-flow', status: 'queued', base_hash: HASH });
    expect(write).not.toHaveProperty('bpmn_xml');

    expect((await req('GET', '/api/process_writes', undefined, anon)).status).toBe(401);
    const drain = await json(await req('GET', '/api/process_writes'));
    expect(drain.writes.map((w: Json) => [w.id, w.bpmn_xml])).toEqual([[write.id, XML]]);

    expect((await req('POST', `/api/process_writes/${write.id}/mark`, { status: 'done' })).status).toBe(400);
    const marked = await req('POST', `/api/process_writes/${write.id}/mark`, { status: 'conflict', error: 'changed' });
    expect((await json(marked)).write).toMatchObject({ status: 'conflict', error: 'changed' });
    expect((await req('POST', `/api/process_writes/${write.id}/mark`, { status: 'applied' })).status).toBe(409);

    const polled = await json(await req('GET', `/api/processes/pr-flow/writes/${write.id}`));
    expect(polled.write.status).toBe('conflict');
    expect((await json(await req('GET', '/api/process_writes'))).writes).toEqual([]);
  });
});
