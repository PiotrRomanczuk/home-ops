import type { Hono } from 'hono';
import type pg from 'pg';
import { tokenOnly, viewerOrToken } from '../auth.ts';
import { EVENT_KINDS, parseEventsBody, parseSessionsBody, warsawDays } from '../claude-model.ts';
import {
  INSERT_EVENTS_SQL,
  LIVE_CLEAR_SQL,
  LIVE_SET_SQL,
  RESOLVE_PROJECT_SQL,
  SESSION_COLS,
  SESSION_DAYS_SQL,
  SIGNALS_DELETE_SQL,
  SIGNALS_INSERT_SQL,
  UPSERT_SESSIONS_SQL,
} from '../claude-sql.ts';
import { pool } from '../db.ts';

// What was done with Claude Code (migration 032). claude-collector (Mac and
// elitedesk) upserts one row per session and appends its events; both writes
// recompute the Postęp signals of the days they touch. Reads feed the journal
// and the console.

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

async function readJson(c: { req: { json: () => Promise<unknown> } }): Promise<unknown> {
  try {
    return await c.req.json();
  } catch {
    return undefined;
  }
}

async function tx<T>(fn: (client: pg.PoolClient) => Promise<T>): Promise<T> {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    const out = await fn(client);
    await client.query('COMMIT');
    return out;
  } catch (e) {
    await client.query('ROLLBACK');
    throw e;
  } finally {
    client.release();
  }
}

async function recomputeSignals(client: pg.PoolClient, days: string[]): Promise<void> {
  if (!days.length) return;
  await client.query(SIGNALS_DELETE_SQL, [days]);
  await client.query(SIGNALS_INSERT_SQL, [days]);
}

export function registerClaudeRoutes(app: Hono): void {
  app.use('/api/claude/*', viewerOrToken);
  app.post('/api/claude/*', tokenOnly);

  app.post('/api/claude/sessions', async (c) => {
    const body = parseSessionsBody(await readJson(c));
    if (typeof body === 'string') return c.json({ error: body }, 400);
    const ids = body.items.map((s) => s.session_id);
    await tx(async (client) => {
      if (ids.length) {
        await client.query(UPSERT_SESSIONS_SQL, [body.host, JSON.stringify(body.items)]);
        await client.query(RESOLVE_PROJECT_SQL, [body.host, ids]);
        const days = await client.query(SESSION_DAYS_SQL, [body.host, ids]);
        await recomputeSignals(
          client,
          days.rows.map((r) => r.day as string),
        );
      }
      if (body.live) {
        await client.query(LIVE_SET_SQL, [body.host, JSON.stringify(body.live)]);
        await client.query(LIVE_CLEAR_SQL, [body.host, body.live.map((l) => l.session_id)]);
      }
    });
    return c.json({ upserted: ids.length, rejected: body.rejected });
  });

  app.post('/api/claude/events', async (c) => {
    const body = parseEventsBody(await readJson(c));
    if (typeof body === 'string') return c.json({ error: body }, 400);
    const inserted = await tx(async (client) => {
      if (!body.items.length) return 0;
      const r = await client.query(INSERT_EVENTS_SQL, [body.host, JSON.stringify(body.items)]);
      const prompts = body.items.filter((e) => e.kind === 'prompt').map((e) => e.ts);
      await recomputeSignals(client, warsawDays(prompts));
      return r.rowCount ?? 0;
    });
    return c.json({ inserted, rejected: body.rejected });
  });

  // Sessions with any event on a Warsaw day (default today), newest first.
  app.get('/api/claude/sessions', async (c) => {
    const q = c.req.query();
    const day = q.day && DATE_RE.test(q.day) ? q.day : null;
    const r = await pool.query(
      `SELECT ${SESSION_COLS},
              (SELECT count(*)::int FROM public.claude_events e WHERE e.host = s.host
                  AND e.session_id = s.session_id AND e.kind = 'prompt'
                  AND (e.ts AT TIME ZONE 'Europe/Warsaw')::date = d.day) AS prompts_day
         FROM public.claude_sessions s,
              (SELECT coalesce($1::date, (now() AT TIME ZONE 'Europe/Warsaw')::date) AS day) d
        WHERE ($2::text IS NULL OR s.host = $2) AND ($3::text IS NULL OR s.project_slug = $3)
          AND EXISTS (SELECT 1 FROM public.claude_events e WHERE e.host = s.host AND e.session_id = s.session_id
                         AND (e.ts AT TIME ZONE 'Europe/Warsaw')::date = d.day)
        ORDER BY s.last_at DESC LIMIT 200`,
      [day, q.host || null, q.project || null],
    );
    return c.json({ sessions: r.rows });
  });

  app.get('/api/claude/events', async (c) => {
    const q = c.req.query();
    if (!q.session) return c.json({ error: 'session required' }, 400);
    const kind = (EVENT_KINDS as readonly string[]).includes(q.kind ?? '') ? q.kind : null;
    const n = Number.parseInt(q.limit ?? '', 10);
    const r = await pool.query(
      `SELECT host, session_id, uuid, ts, kind, text, detail FROM public.claude_events
        WHERE session_id = $1 AND ($2::text IS NULL OR host = $2) AND ($3::text IS NULL OR kind = $3)
        ORDER BY ts LIMIT $4`,
      [q.session, q.host || null, kind, Number.isFinite(n) ? Math.min(5000, Math.max(1, n)) : 1000],
    );
    return c.json({ events: r.rows });
  });
}
