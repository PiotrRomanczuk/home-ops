/* Integration test for storage_places (029): POST /api/storage/sync full-set
 * upsert + delete, rejections, and GET /api/storage filters + summary.
 * Skips when DATABASE_URL is unset. Needs migration 029.
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
  const r = await pool.query(`SELECT to_regclass('public.storage_places') AS t`);
  if (!r.rows[0].t) throw new Error('apply migration 029 first');
  const { Hono: HonoCls } = await import('hono');
  app = new HonoCls();
  (await import('../storage.ts')).registerStorageRoutes(app);
});

afterAll(async () => {
  if (!skip && pool) await pool.end();
});

beforeEach(async () => {
  if (skip) return;
  await pool.query('DELETE FROM public.storage_places');
});

const req = (method: string, path: string, body?: unknown, headers: Record<string, string> = tokenHdr) =>
  app.fetch(new Request(`http://x${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined }));
const json = async (r: Response) => (await r.json()) as Json;
const place = (id: number, extra: Json = {}) => ({
  id,
  nazwa: `miejsce ${id}`,
  gdzie: 'uwh',
  porzadek: 'ok',
  backup: 'ok',
  sprawdzone: '2026-11-12',
  note_path: `2-Obszary/mapy/miejsca/${id}-x.md`,
  raw_frontmatter: { id },
  ...extra,
});

describe.skipIf(skip)('POST /api/storage/sync + GET /api/storage', () => {
  it('requires the token and a non-empty valid set', async () => {
    const noToken = { 'Content-Type': 'application/json' };
    expect((await req('POST', '/api/storage/sync', { places: [place(1)] }, noToken)).status).toBe(401);
    expect((await req('POST', '/api/storage/sync', { places: [] })).status).toBe(400);
    expect((await req('POST', '/api/storage/sync', { places: [place(1, { porzadek: '🟢' })] })).status).toBe(400);
  });

  it('upserts the set, then deletes ids that left the vault', async () => {
    const first = await json(
      await req('POST', '/api/storage/sync', { places: [place(1), place(2, { backup: 'problem' }), place(0)] }),
    );
    expect(first).toMatchObject({ upserted: 2, removed: 0 });
    expect(first.rejected).toEqual([{ index: 2, reason: 'bad id' }]);

    const second = await json(
      await req('POST', '/api/storage/sync', { places: [place(2, { backup: 'ok', test_odtworzenia: '2026-11-13' })] }),
    );
    expect(second).toMatchObject({ upserted: 1, removed: 1 });

    const g = await json(await req('GET', '/api/storage'));
    expect(g.places).toHaveLength(1);
    expect(g.places[0]).toMatchObject({
      id: 2,
      backup: 'ok',
      test_odtworzenia: '2026-11-13',
      sprawdzone: '2026-11-12',
    });
  });

  it('filters by status and counts the summary', async () => {
    await req('POST', '/api/storage/sync', {
      places: [place(1), place(2, { backup: 'problem' }), place(3, { backup: 'problem', porzadek: 'niesprawdzone' })],
    });
    const g = await json(await req('GET', '/api/storage?backup=problem'));
    expect(g.places.map((p: Json) => p.id)).toEqual([2, 3]);
    expect(g.summary).toEqual({ total: 2, porzadek: { ok: 1, niesprawdzone: 1 }, backup: { problem: 2 } });
  });
});
