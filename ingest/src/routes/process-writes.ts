import type { Hono } from 'hono';
import { tokenOnly } from '../auth.ts';
import { pool } from '../db.ts';
import { MAX_BPMN_CHARS } from '../process-model.ts';

// BPMN saves from the Mapa tab (migration 030). A viewer posts the edited
// diagram with the hash it was opened at; planner-sync drains the queue into
// the vault and marks each write applied / conflict / failed. The viewer side
// sits under /api/processes/* (viewerOrToken, registered in processes.ts);
// the drain side is token-only.

const WRITE_COLUMNS = 'id, slug, base_hash, status, error, created_at, applied_at';
const DEFINITIONS_RE = /<(?:\w+:)?definitions[\s>]/;

export function registerProcessWritesRoutes(app: Hono): void {
  app.post('/api/processes/:slug/writes', async (c) => {
    const body = (await c.req.json().catch(() => null)) as { bpmn_xml?: unknown; base_hash?: unknown } | null;
    const xml = body?.bpmn_xml;
    const baseHash = body?.base_hash;
    if (typeof xml !== 'string' || !DEFINITIONS_RE.test(xml))
      return c.json({ error: 'bpmn_xml must be BPMN XML' }, 400);
    if (xml.length > MAX_BPMN_CHARS) return c.json({ error: 'diagram too large' }, 413);
    if (typeof baseHash !== 'string' || !/^[0-9a-f]{64}$/.test(baseHash))
      return c.json({ error: 'base_hash (sha256 hex) required' }, 400);
    const slug = c.req.param('slug');
    const r = await pool.query(
      `INSERT INTO public.process_writes (slug, base_hash, bpmn_xml)
       SELECT slug, $2, $3 FROM public.processes WHERE slug = $1
       RETURNING ${WRITE_COLUMNS}`,
      [slug, baseHash, xml],
    );
    if (!r.rowCount) return c.json({ error: 'unknown process' }, 404);
    return c.json({ write: r.rows[0] }, 202);
  });

  app.get('/api/processes/:slug/writes/:id', async (c) => {
    const r = await pool.query(`SELECT ${WRITE_COLUMNS} FROM public.process_writes WHERE id = $1 AND slug = $2`, [
      Number(c.req.param('id')) || 0,
      c.req.param('slug'),
    ]);
    if (!r.rowCount) return c.json({ error: 'not found' }, 404);
    return c.json({ write: r.rows[0] });
  });

  app.use('/api/process_writes', tokenOnly);
  app.use('/api/process_writes/*', tokenOnly);

  app.get('/api/process_writes', async (c) => {
    const limit = Math.min(Math.max(Number(c.req.query('limit') ?? '10') || 10, 1), 50);
    const r = await pool.query(
      `SELECT ${WRITE_COLUMNS}, bpmn_xml FROM public.process_writes
        WHERE status = 'queued' ORDER BY created_at LIMIT $1`,
      [limit],
    );
    return c.json({ writes: r.rows });
  });

  app.post('/api/process_writes/:id/mark', async (c) => {
    const body = (await c.req.json().catch(() => ({}))) as { status?: string; error?: string };
    if (body.status !== 'applied' && body.status !== 'conflict' && body.status !== 'failed')
      return c.json({ error: 'invalid status' }, 400);
    const r = await pool.query(
      `UPDATE public.process_writes
          SET status = $2, error = $3, applied_at = CASE WHEN $2 = 'applied' THEN now() ELSE applied_at END
        WHERE id = $1 AND status = 'queued'
        RETURNING ${WRITE_COLUMNS}`,
      [Number(c.req.param('id')) || 0, body.status, (body.error ?? '').slice(0, 2000) || null],
    );
    if (!r.rowCount) return c.json({ error: 'not queued' }, 409);
    return c.json({ write: r.rows[0] });
  });
}
