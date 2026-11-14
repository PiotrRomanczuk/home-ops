import type { Hono } from 'hono';
import { tokenOnly, viewerOrToken } from '../auth.ts';
import { pool } from '../db.ts';
import { buildJournal, type HourRow, parseJournalPost } from '../journal-model.ts';
import {
  APPS_SQL,
  BY_PROJECT_SQL,
  HOURS_SQL,
  JOURNAL_SQL,
  PROCS_SQL,
  PRS_SQL,
  SESSIONS_SQL,
  TOTALS_SQL,
  UPSERT_JOURNAL_SQL,
} from '../journal-sql.ts';

// One day of one host (migration 032): what ran on the machine (mac-watcher's
// host_metrics + "proc" lines) and what was done with Claude (claude_*).
// day-summary reads it at 21:30, adds the local model's note and POSTs both
// back, so day_journal keeps the day after host_metrics prunes it.

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export function registerJournalRoutes(app: Hono): void {
  app.use('/api/journal', viewerOrToken);
  app.use('/api/journal/*', viewerOrToken);
  app.post('/api/journal', tokenOnly);

  app.get('/api/journal/day', async (c) => {
    const host = (c.req.query('host') || 'mac').slice(0, 63);
    const raw = c.req.query('day');
    const day =
      raw && DATE_RE.test(raw)
        ? raw
        : ((await pool.query(`SELECT to_char((now() AT TIME ZONE 'Europe/Warsaw')::date, 'YYYY-MM-DD') AS d`)).rows[0]
            .d as string);
    const [hours, apps, procs, sessions, totals, byProject, prs, journal] = await Promise.all([
      pool.query(HOURS_SQL, [host, day]),
      pool.query(APPS_SQL, [host, day]),
      pool.query(PROCS_SQL, [host, day]),
      pool.query(SESSIONS_SQL, [day]),
      pool.query(TOTALS_SQL, [host, day]),
      pool.query(BY_PROJECT_SQL, [day]),
      pool.query(PRS_SQL, [day]),
      pool.query(JOURNAL_SQL, [host, day]),
    ]);
    return c.json(
      buildJournal({
        host,
        day,
        hours: hours.rows as HourRow[],
        apps: apps.rows,
        procs: procs.rows,
        sessions: sessions.rows,
        totals: totals.rows[0],
        byProject: byProject.rows,
        prs: prs.rows,
        journal: journal.rows[0],
      }),
    );
  });

  app.post('/api/journal', async (c) => {
    let raw: unknown;
    try {
      raw = await c.req.json();
    } catch {
      return c.json({ error: 'invalid json' }, 400);
    }
    const body = parseJournalPost(raw);
    if (typeof body === 'string') return c.json({ error: body }, 400);
    await pool.query(UPSERT_JOURNAL_SQL, [
      body.host,
      body.day,
      JSON.stringify(body.rollup),
      body.summary_md,
      body.model,
    ]);
    return c.json({ status: 'ok', host: body.host, day: body.day });
  });
}
