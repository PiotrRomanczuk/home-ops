import type { Hono } from 'hono';
import { viewerOrToken } from '../auth.ts';
import { pool } from '../db.ts';

// Eval task board (Evals tab). One row per task card in eval_tasks; the
// board is authoritative — eval-tick only runs stages testing/active.
// Result stats are joined from eval_scores via rationale = name.

const STAGES = new Set(['idea', 'building', 'testing', 'active', 'paused', 'retired']);
const KINDS = new Set(['python', 'strummy']);
const NAME_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;

const LIST_SQL = `
  SELECT t.id, t.name, t.kind, t.stage, t.notes, t.timeout_s,
         t.has_files, t.files_seen_at, t.created_at, t.updated_at,
         stats.n_runs, stats.n_passed, stats.avg_iterations, stats.last_scored_at,
         last.passed AS last_passed, last.model AS last_model
    FROM public.eval_tasks t
    LEFT JOIN LATERAL (
      SELECT count(*)::int AS n_runs,
             count(*) FILTER (WHERE passed)::int AS n_passed,
             round(avg(iterations), 1) AS avg_iterations,
             max(scored_at) AS last_scored_at
        FROM public.eval_scores s
       WHERE s.task_kind = 'coding' AND s.rationale = t.name
    ) stats ON true
    LEFT JOIN LATERAL (
      SELECT passed, model
        FROM public.eval_scores s
       WHERE s.task_kind = 'coding' AND s.rationale = t.name
       ORDER BY scored_at DESC LIMIT 1
    ) last ON true
   ORDER BY array_position(ARRAY['idea','building','testing','active','paused','retired'], t.stage),
            t.name`;

export function registerEvalsRoutes(app: Hono): void {
  app.use('/api/eval_tasks', viewerOrToken);
  app.use('/api/eval_tasks/*', viewerOrToken);

  app.get('/api/eval_tasks', async (c) => {
    const r = await pool.query(LIST_SQL);
    return c.json({ tasks: r.rows });
  });

  // Create a card — always starts at 'idea' (files come later, by hand or
  // Claude-assisted; the server never writes task dirs).
  app.post('/api/eval_tasks', async (c) => {
    const body = (await c.req.json().catch(() => ({}))) as {
      name?: string;
      kind?: string;
      notes?: string;
    };
    const name = (body.name ?? '').trim();
    if (!NAME_RE.test(name)) return c.json({ error: 'name must match ^[a-z0-9][a-z0-9_-]{0,63}$' }, 400);
    const kind = body.kind ?? 'python';
    if (!KINDS.has(kind)) return c.json({ error: 'invalid kind' }, 400);
    const notes = typeof body.notes === 'string' ? body.notes.slice(0, 4000) : null;
    const r = await pool.query(
      `INSERT INTO public.eval_tasks (name, kind, notes)
       VALUES ($1, $2, $3)
       ON CONFLICT (name) DO NOTHING
       RETURNING *`,
      [name, kind, notes],
    );
    if (r.rowCount === 0) return c.json({ error: 'name already exists' }, 409);
    return c.json({ task: r.rows[0] }, 201);
  });

  app.post('/api/eval_tasks/:id/stage', async (c) => {
    const id = Number(c.req.param('id'));
    if (!Number.isInteger(id)) return c.json({ error: 'invalid id' }, 400);
    const body = (await c.req.json().catch(() => ({}))) as { stage?: string };
    if (!body.stage || !STAGES.has(body.stage)) return c.json({ error: 'invalid stage' }, 400);
    const r = await pool.query(
      `UPDATE public.eval_tasks SET stage = $2, updated_at = now() WHERE id = $1 RETURNING *`,
      [id, body.stage],
    );
    if (r.rowCount === 0) return c.json({ error: 'not found' }, 404);
    return c.json({ task: r.rows[0] });
  });

  app.post('/api/eval_tasks/:id/update', async (c) => {
    const id = Number(c.req.param('id'));
    if (!Number.isInteger(id)) return c.json({ error: 'invalid id' }, 400);
    const body = (await c.req.json().catch(() => ({}))) as {
      notes?: string | null;
      timeout_s?: number | null;
    };
    const hasNotes = 'notes' in body;
    const hasTimeout = 'timeout_s' in body;
    if (!hasNotes && !hasTimeout) return c.json({ error: 'nothing to update' }, 400);
    if (hasTimeout && body.timeout_s != null) {
      const t = body.timeout_s;
      if (!Number.isInteger(t) || t <= 0 || t > 3600) return c.json({ error: 'timeout_s must be 1..3600' }, 400);
    }
    const r = await pool.query(
      `UPDATE public.eval_tasks
          SET notes = CASE WHEN $2 THEN $3 ELSE notes END,
              timeout_s = CASE WHEN $4 THEN $5 ELSE timeout_s END,
              updated_at = now()
        WHERE id = $1
        RETURNING *`,
      [id, hasNotes, hasNotes ? (body.notes ?? '').slice(0, 4000) || null : null, hasTimeout, body.timeout_s ?? null],
    );
    if (r.rowCount === 0) return c.json({ error: 'not found' }, 404);
    return c.json({ task: r.rows[0] });
  });

  // Recent per-task results for the drill panel.
  app.get('/api/eval_tasks/:id/scores', async (c) => {
    const id = Number(c.req.param('id'));
    if (!Number.isInteger(id)) return c.json({ error: 'invalid id' }, 400);
    const t = await pool.query(`SELECT name FROM public.eval_tasks WHERE id = $1`, [id]);
    if (t.rowCount === 0) return c.json({ error: 'not found' }, 404);
    const r = await pool.query(
      `SELECT id, run_id, model, passed, iterations, tok_per_s, latency_ms, scored_at
         FROM public.eval_scores
        WHERE task_kind = 'coding' AND rationale = $1
        ORDER BY scored_at DESC
        LIMIT 30`,
      [t.rows[0].name],
    );
    return c.json({ scores: r.rows });
  });
}
