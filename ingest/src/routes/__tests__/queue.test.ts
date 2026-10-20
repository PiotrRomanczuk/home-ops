/* Integration test for queue_state (023): POST /api/queue/sync upsert +
 * hash short-circuit, GET /api/queue, and the `queue` field of GET /api/today.
 * Skips when DATABASE_URL is unset. Needs migrations 001, 003, 005, 013,
 * 020, 021, 022, 023.
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
  const r = await pool.query(`SELECT to_regclass('public.queue_state') AS q`);
  if (!r.rows[0].q) throw new Error('apply migration 023 first');
  const { Hono: HonoCls } = await import('hono');
  app = new HonoCls();
  (await import('../queue.ts')).registerQueueRoutes(app);
  (await import('../today.ts')).registerTodayRoutes(app);
});

afterAll(async () => {
  if (!skip && pool) await pool.end();
});

beforeEach(async () => {
  if (skip) return;
  await pool.query('DELETE FROM public.queue_state');
});

const req = (method: string, path: string, body?: unknown, headers: Record<string, string> = tokenHdr) =>
  app.fetch(new Request(`http://x${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined }));
const json = async (r: Response) => (await r.json()) as Json;
const queue = (extra: Json = {}) => ({
  window_from: '2026-10-19',
  window_to: '2026-10-25',
  capacity_hours: 6,
  focus: 'Strummy',
  rules: '1 bilet w toku',
  sections: {
    in_progress: [{ text: 'STR-10', cls: 'risk', size: 'S', flags: ['unblocks'], id: 'STR-10', project: 'Strummy' }],
    queue: [{ text: 'STR-2', cls: 'risk', size: 'L' }],
    done: [{ text: 'STR-9', done: true, hours: 0.5 }],
  },
  summary: { in_progress: 1, queue: 1, done: 1, done_hours: 0.5 },
  source_hash: 'h1',
  ...extra,
});

describe.skipIf(skip)('POST /api/queue/sync + GET /api/queue', () => {
  it('requires the token and validates', async () => {
    expect((await req('POST', '/api/queue/sync', queue(), { 'Content-Type': 'application/json' })).status).toBe(401);
    expect((await req('POST', '/api/queue/sync', queue({ capacity_hours: 'x' }))).status).toBe(400);
  });

  it('creates, then updates, then short-circuits on the same hash', async () => {
    expect((await req('POST', '/api/queue/sync', queue())).status).toBe(201);
    const b = await req('POST', '/api/queue/sync', queue({ source_hash: 'h2', capacity_hours: 8 }));
    expect(b.status).toBe(200);
    expect((await json(b)).status).toBe('updated');
    expect((await json(await req('POST', '/api/queue/sync', queue({ source_hash: 'h2' })))).status).toBe('unchanged');
    const g = await json(await req('GET', '/api/queue'));
    expect(g.queue.capacity_hours).toBe(8);
    expect(g.queue.window_from).toBe('2026-10-19');
    expect(g.queue.sections.in_progress[0].id).toBe('STR-10');
    expect(g.queue.summary.done_hours).toBe(0.5);
  });

  it('GET /api/today carries the queue (null before the first sync)', async () => {
    expect((await json(await req('GET', '/api/today'))).queue).toBeNull();
    await req('POST', '/api/queue/sync', queue());
    const t = await json(await req('GET', '/api/today'));
    expect(t.queue.sections.queue).toHaveLength(1);
    expect(t.queue.focus).toBe('Strummy');
  });
});
