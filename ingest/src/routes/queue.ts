import type { Hono } from 'hono';
import { tokenOnly, viewerOrToken } from '../auth.ts';
import { pool } from '../db.ts';
import { parseQueue } from '../queue-model.ts';

// queue_state (migration 023) — the vault's QUEUE.md as one row. planner-sync
// parses the file each tick and POSTs it here; the write is skipped when the
// source hash matches, so an unchanged file costs one SELECT. The console's
// "Dziś" tab reads it through GET /api/today; GET /api/queue is the same row
// for anything else (digest, MCP). Contract: docs/adr/2026-10-20-queue-state.md.

// ::text on dates — node-pg would turn a `date` into a local-midnight Date.
export const QUEUE_COLS = `window_from::text AS window_from, window_to::text AS window_to,
  capacity_hours::float AS capacity_hours, focus, rules, sections, summary, source_hash, synced_at`;

export const QUEUE_SQL = `SELECT ${QUEUE_COLS} FROM public.queue_state WHERE id = 1`;

export function registerQueueRoutes(app: Hono): void {
  app.use('/api/queue', viewerOrToken);
  app.use('/api/queue/*', viewerOrToken);
  app.post('/api/queue/sync', tokenOnly);

  app.get('/api/queue', async (c) => {
    const r = await pool.query(QUEUE_SQL);
    return c.json({ queue: r.rows[0] ?? null });
  });

  app.post('/api/queue/sync', async (c) => {
    let body: unknown;
    try {
      body = await c.req.json();
    } catch {
      return c.json({ error: 'invalid json' }, 400);
    }
    const q = parseQueue(body);
    if (typeof q === 'string') return c.json({ error: q }, 400);

    if (q.source_hash) {
      const cur = await pool.query(`SELECT source_hash FROM public.queue_state WHERE id = 1`);
      if (cur.rows[0]?.source_hash === q.source_hash) return c.json({ status: 'unchanged' });
    }
    const r = await pool.query(
      `INSERT INTO public.queue_state
         (id, window_from, window_to, capacity_hours, focus, rules, sections, summary, source_hash, synced_at)
       VALUES (1, $1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, now())
       ON CONFLICT (id) DO UPDATE SET
         window_from = EXCLUDED.window_from, window_to = EXCLUDED.window_to,
         capacity_hours = EXCLUDED.capacity_hours, focus = EXCLUDED.focus, rules = EXCLUDED.rules,
         sections = EXCLUDED.sections, summary = EXCLUDED.summary,
         source_hash = EXCLUDED.source_hash, synced_at = now()
       RETURNING (xmax = 0) AS inserted`,
      [
        q.window_from,
        q.window_to,
        q.capacity_hours,
        q.focus,
        q.rules,
        JSON.stringify(q.sections),
        JSON.stringify(q.summary),
        q.source_hash,
      ],
    );
    return c.json({ status: r.rows[0]?.inserted ? 'created' : 'updated' }, r.rows[0]?.inserted ? 201 : 200);
  });
}
