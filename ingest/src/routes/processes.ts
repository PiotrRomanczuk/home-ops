import type { Hono } from 'hono';
import { tokenOnly, viewerOrToken } from '../auth.ts';
import { pool } from '../db.ts';
import { parseProcessesBody } from '../process-model.ts';

// BPMN process notes (migration 029). planner-sync POSTs the full set every
// tick; rows absent from the payload are deleted, so a note removed from the
// vault disappears from the Mapa tab on the next tick. The list omits the
// diagram XML; GET /api/processes/:slug returns it.

const UPSERT_SQL = `
  INSERT INTO public.processes
    (slug, title, trigger, schedule, summary, projects, lanes, bpmn_xml, bpmn_hash, path, warnings, synced_at)
  SELECT r.slug, r.title, r.trigger, r.schedule, r.summary,
         ARRAY(SELECT jsonb_array_elements_text(r.projects)),
         ARRAY(SELECT jsonb_array_elements_text(r.lanes)),
         r.bpmn_xml, r.bpmn_hash, r.path, r.warnings, now()
  FROM jsonb_to_recordset($1::jsonb) AS r(slug text, title text, trigger text, schedule text, summary text,
       projects jsonb, lanes jsonb, bpmn_xml text, bpmn_hash text, path text, warnings jsonb)
  ON CONFLICT (slug) DO UPDATE SET
    title = EXCLUDED.title, trigger = EXCLUDED.trigger, schedule = EXCLUDED.schedule,
    summary = EXCLUDED.summary, projects = EXCLUDED.projects, lanes = EXCLUDED.lanes,
    bpmn_xml = EXCLUDED.bpmn_xml, bpmn_hash = EXCLUDED.bpmn_hash, path = EXCLUDED.path,
    warnings = EXCLUDED.warnings, synced_at = now()`;

const LIST_COLUMNS = 'slug, title, trigger, schedule, summary, projects, lanes, bpmn_hash, path, warnings, synced_at';

export function registerProcessesRoutes(app: Hono): void {
  app.use('/api/processes', viewerOrToken);
  app.use('/api/processes/*', viewerOrToken);
  app.use('/api/processes/sync', tokenOnly);

  app.post('/api/processes/sync', async (c) => {
    let raw: unknown;
    try {
      raw = await c.req.json();
    } catch {
      return c.json({ error: 'invalid json' }, 400);
    }
    const rows = parseProcessesBody(raw);
    if (typeof rows === 'string') return c.json({ error: rows }, 400);
    const client = await pool.connect();
    try {
      await client.query('BEGIN');
      if (rows.length) await client.query(UPSERT_SQL, [JSON.stringify(rows)]);
      const del = await client.query('DELETE FROM public.processes WHERE NOT (slug = ANY($1::text[]))', [
        rows.map((r) => r.slug),
      ]);
      await client.query('COMMIT');
      return c.json({ upserted: rows.length, removed: del.rowCount ?? 0 });
    } catch (e) {
      await client.query('ROLLBACK');
      throw e;
    } finally {
      client.release();
    }
  });

  app.get('/api/processes', async (c) => {
    const r = await pool.query(`SELECT ${LIST_COLUMNS} FROM public.processes ORDER BY slug`);
    return c.json({ processes: r.rows });
  });

  app.get('/api/processes/:slug', async (c) => {
    const r = await pool.query(`SELECT ${LIST_COLUMNS}, bpmn_xml FROM public.processes WHERE slug = $1`, [
      c.req.param('slug'),
    ]);
    if (!r.rows.length) return c.json({ error: 'not found' }, 404);
    return c.json({ process: r.rows[0] });
  });
}
