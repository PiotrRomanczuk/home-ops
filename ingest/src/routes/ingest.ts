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

function validate(e: unknown): e is Event {
  if (!e || typeof e !== 'object') return false;
  const x = e as Partial<Event>;
  return (
    typeof x.host === 'string' &&
    x.host.length > 0 &&
    x.host.length < 64 &&
    typeof x.source === 'string' &&
    x.source.length > 0 &&
    x.source.length < 128 &&
    typeof x.level === 'string' &&
    (LEVELS as string[]).includes(x.level) &&
    typeof x.message === 'string' &&
    x.message.length > 0
  );
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
    let events: Event[];
    if (body && typeof body === 'object' && 'events' in body && Array.isArray((body as { events: unknown }).events)) {
      events = (body as { events: unknown[] }).events as Event[];
    } else {
      events = [body as Event];
    }
    if (events.length === 0) return c.json({ inserted: 0 });
    if (events.length > 500) return c.json({ error: 'batch too large (max 500)' }, 413);
    const bad = events.findIndex((e) => !validate(e));
    if (bad >= 0) return c.json({ error: 'invalid event', index: bad }, 400);
    try {
      const inserted = await insertBatch(events);
      return c.json({ inserted });
    } catch (err) {
      console.error('insert failed:', err);
      return c.json({ error: 'db write failed' }, 503);
    }
  });
}
