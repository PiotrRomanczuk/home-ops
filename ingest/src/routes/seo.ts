import type { Hono } from 'hono';
import { tokenOnly } from '../auth.ts';
import { pool } from '../db.ts';
import { buildUpsert, isSeoKind, SPECS } from './seo-rows.ts';

// Search-visibility snapshots from ops/elitedesk/seo-collect.py (migration 017).
// Body: { kind: 'gsc' | 'ga4' | 'places', rows: [...] }. Upsert-only, keyed per
// table, so the collector can re-send a rolling window (GSC lags 2–3 days)
// without duplicating. Invalid rows are skipped and reported, like /api/ingest.

const MAX_ROWS = 25000; // one GSC searchAnalytics page
const CHUNK = 500;

export function registerSeoRoutes(app: Hono): void {
  app.use('/api/seo/*', tokenOnly);

  app.post('/api/seo/ingest', async (c) => {
    const body = (await c.req.json().catch(() => null)) as { kind?: unknown; rows?: unknown } | null;
    if (!body || !isSeoKind(body.kind)) return c.json({ error: 'kind must be one of gsc, ga4, places' }, 400);
    if (!Array.isArray(body.rows)) return c.json({ error: 'rows must be an array' }, 400);
    if (body.rows.length > MAX_ROWS) return c.json({ error: `batch too large (max ${MAX_ROWS})` }, 413);

    const kind = body.kind;
    const good: Record<string, unknown>[] = [];
    const rejected: { index: number; reason: string }[] = [];
    body.rows.forEach((r, index) => {
      const reason =
        r && typeof r === 'object' && !Array.isArray(r)
          ? SPECS[kind].validate(r as Record<string, unknown>)
          : 'not an object';
      if (reason) rejected.push({ index, reason });
      else good.push(r as Record<string, unknown>);
    });

    try {
      for (let i = 0; i < good.length; i += CHUNK) {
        const { sql, params } = buildUpsert(kind, good.slice(i, i + CHUNK));
        await pool.query(sql, params);
      }
      return c.json({ kind, upserted: good.length, rejected });
    } catch (err) {
      console.error('seo upsert failed:', err);
      return c.json({ error: 'db write failed' }, 503);
    }
  });
}
