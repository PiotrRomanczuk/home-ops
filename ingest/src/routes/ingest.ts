import type { Hono } from 'hono';
import { tokenOnly } from '../auth.ts';
import { pool } from '../db.ts';
import { LEVELS, type Level } from '../types.ts';

interface Event {
  host: string;
  source: string;
  level: Level;
  message: string;
  data?: Record<string, unknown>;
  ts?: string;
}

interface Rejected {
  index: number;
  reason: string;
}

// Returns null on success, otherwise a short reason that goes back to the
// client in the rejected[] array. Keep reasons short and stable — agents log
// them verbatim.
function validate(e: unknown): string | null {
  if (!e || typeof e !== 'object') return 'not an object';
  const x = e as Partial<Event>;
  if (typeof x.host !== 'string' || x.host.length === 0 || x.host.length >= 64) return 'invalid host';
  if (typeof x.source !== 'string' || x.source.length === 0 || x.source.length >= 128) return 'invalid source';
  if (typeof x.level !== 'string' || !(LEVELS as string[]).includes(x.level)) return 'invalid level';
  if (typeof x.message !== 'string' || x.message.length === 0) return 'invalid message';
  return null;
}

async function insertBatch(events: Event[]): Promise<number> {
  if (events.length === 0) return 0;
  const cols: unknown[] = [];
  const placeholders: string[] = [];
  events.forEach((e, i) => {
    const base = i * 6;
    placeholders.push(
      `(COALESCE($${base + 1}::timestamptz, now()), $${base + 2}, $${base + 3}, $${base + 4}, $${base + 5}, $${base + 6}::jsonb)`,
    );
    cols.push(e.ts ?? null, e.host, e.source, e.level, e.message, JSON.stringify(e.data ?? {}));
  });
  const sql = `INSERT INTO public.host_logs (ts, host, source, level, message, data) VALUES ${placeholders.join(', ')}`;
  await pool.query(sql, cols);
  return events.length;
}

export function registerIngestRoutes(app: Hono): void {
  app.use('/api/ingest', tokenOnly);
  app.use('/api/ingest/*', tokenOnly);

  app.post('/api/ingest', async (c) => {
    let body: unknown;
    try {
      body = await c.req.json();
    } catch {
      return c.json({ error: 'invalid json' }, 400);
    }
    let events: unknown[];
    if (body && typeof body === 'object' && 'events' in body && Array.isArray((body as { events: unknown }).events)) {
      events = (body as { events: unknown[] }).events;
    } else {
      events = [body];
    }
    if (events.length === 0) return c.json({ inserted: 0, rejected: [] });
    if (events.length > 500) return c.json({ error: 'batch too large (max 500)' }, 413);

    const good: Event[] = [];
    const rejected: Rejected[] = [];
    events.forEach((e, i) => {
      const reason = validate(e);
      if (reason) rejected.push({ index: i, reason });
      else good.push(e as Event);
    });

    try {
      const inserted = await insertBatch(good);
      return c.json({ inserted, rejected });
    } catch (err) {
      console.error('insert failed:', err);
      return c.json({ error: 'db write failed' }, 503);
    }
  });
}
