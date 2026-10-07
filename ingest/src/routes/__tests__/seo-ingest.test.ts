/* Integration test for POST /api/seo/ingest (migration 017).
 *
 * Guards the contract seo-collect.py relies on: re-sending the same day
 * upserts instead of duplicating (GSC is re-fetched over a rolling window),
 * invalid rows are skipped and reported, and the route is token-only.
 *
 * Skips if DATABASE_URL isn't set — same pattern as projects-repo-sync.test.ts.
 */
import type { Hono } from 'hono';
import type pg from 'pg';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';

const dbUrl = process.env.DATABASE_URL;
const ingestToken = process.env.INGEST_TOKEN || 'ci-token';
const skip = !dbUrl;

let pool: pg.Pool;
let app: Hono;

beforeAll(async () => {
  if (skip) return;
  process.env.INGEST_TOKEN = ingestToken;
  process.env.LOGS_PASSWORD = 'ci-password';

  const pgMod = await import('pg');
  pool = new pgMod.default.Pool({ connectionString: dbUrl, max: 4 });
  const r = await pool.query(`SELECT to_regclass('public.seo_gsc_daily') AS t`);
  if (!r.rows[0].t) throw new Error('seo tables missing — apply migration 017');

  const honoMod = await import('hono');
  const { registerSeoRoutes } = await import('../seo.ts');
  app = new honoMod.Hono();
  registerSeoRoutes(app);
});

afterAll(async () => {
  if (!skip && pool) await pool.end();
});

beforeEach(async () => {
  if (!skip) await pool.query('TRUNCATE public.seo_gsc_daily, public.seo_ga4_daily, public.seo_places_daily');
});

function post(body: unknown, withToken = true) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (withToken) headers['X-Ingest-Token'] = ingestToken;
  return app.fetch(new Request('http://test/api/seo/ingest', { method: 'POST', headers, body: JSON.stringify(body) }));
}

const gscRow = (clicks: number) => ({
  site: 'gitarawarszawa.pl',
  day: '2026-10-05',
  query: 'nauka gry na gitarze warszawa',
  page: 'https://gitarawarszawa.pl/',
  clicks,
  impressions: 40,
  ctr: clicks / 40,
  position: 7.4,
});

describe.skipIf(skip)('POST /api/seo/ingest', () => {
  it('upserts GSC rows — re-sending the same key updates instead of duplicating', async () => {
    expect((await post({ kind: 'gsc', rows: [gscRow(1)] })).status).toBe(200);
    const res = await post({ kind: 'gsc', rows: [gscRow(3)] });
    const body = (await res.json()) as { upserted: number; rejected: unknown[] };
    expect(body).toMatchObject({ upserted: 1, rejected: [] });

    const r = await pool.query('SELECT clicks FROM public.seo_gsc_daily');
    expect(r.rows).toEqual([{ clicks: 3 }]);
  });

  it('stores GA4 events as jsonb', async () => {
    await post({
      kind: 'ga4',
      rows: [
        {
          site: 'gitarawarszawa.pl',
          day: '2026-10-05',
          source_medium: 'google / organic',
          sessions: 9,
          users: 7,
          events: { booking_success: 1 },
        },
      ],
    });
    const r = await pool.query('SELECT sessions, events FROM public.seo_ga4_daily');
    expect(r.rows[0]).toEqual({ sessions: 9, events: { booking_success: 1 } });
  });

  it('accepts places rows with a null rating (listing without reviews yet)', async () => {
    const res = await post({
      kind: 'places',
      rows: [
        {
          place_id: 'ChIJ123',
          day: '2026-10-05',
          label: 'self',
          name: 'Piotr Romańczuk',
          is_self: true,
          rating: null,
          review_count: null,
        },
      ],
    });
    expect(res.status).toBe(200);
    const r = await pool.query('SELECT is_self, rating FROM public.seo_places_daily');
    expect(r.rows[0]).toEqual({ is_self: true, rating: null });
  });

  it('skips and reports invalid rows while keeping the valid ones', async () => {
    const res = await post({ kind: 'gsc', rows: [gscRow(2), { ...gscRow(1), day: '5/10/2026' }, 'nope'] });
    const body = (await res.json()) as { upserted: number; rejected: { index: number }[] };
    expect(body.upserted).toBe(1);
    expect(body.rejected.map((x) => x.index)).toEqual([1, 2]);
  });

  it('rejects an unknown kind and a non-array rows payload', async () => {
    expect((await post({ kind: 'bing', rows: [] })).status).toBe(400);
    expect((await post({ kind: 'toString', rows: [] })).status).toBe(400);
    expect((await post({ kind: 'gsc', rows: 'nope' })).status).toBe(400);
  });

  it('requires a token', async () => {
    expect((await post({ kind: 'gsc', rows: [] }, false)).status).toBe(401);
  });
});
