import type { Hono } from 'hono';
import { viewerOrToken } from '../auth.ts';
import { pool } from '../db.ts';

// Scores tab — read-only scoreboard for the strummy_eval_* harness (the
// local-LLM reconstruction runs on the 7700 XT, driven by eval-tick on a 6h
// timer). Distinct data source from the Evals board: that board manages
// eval_tasks lifecycle; this reads strummy_eval_scores results only.
//
// The strummy_eval_* tables live in the running DB but ship on a separate
// migration branch, so every query is guarded: if the tables are absent the
// endpoint returns available:false instead of 500ing the viewer.

const MATRIX_SQL = `
  SELECT model, task,
         count(*)::int                                             AS n,
         count(*) FILTER (WHERE passed)::int                       AS n_passed,
         round(100.0 * count(*) FILTER (WHERE passed) / count(*))::int AS pass_rate,
         round(avg(iterations), 1)                                 AS avg_iterations,
         round(avg(tok_per_s) FILTER (WHERE tok_per_s > 0), 1)     AS avg_tok_per_s,
         max(scored_at)                                            AS last_scored_at,
         (array_agg(passed ORDER BY scored_at DESC))[1]            AS last_passed
    FROM public.strummy_eval_scores
   GROUP BY model, task
   ORDER BY model, task`;

const RECENT_SQL = `
  SELECT id, run_id, model, task, passed, iterations, tok_per_s, latency_ms, scored_at
    FROM public.strummy_eval_scores
   ORDER BY scored_at DESC
   LIMIT 24`;

const OVERALL_SQL = `
  SELECT count(*)::int                            AS n,
         count(*) FILTER (WHERE passed)::int       AS n_passed,
         count(DISTINCT model)::int                AS n_models,
         count(DISTINCT task)::int                 AS n_tasks,
         max(scored_at)                            AS last_scored_at
    FROM public.strummy_eval_scores`;

const CONFIG_SQL = `
  SELECT paused, models, enabled_tasks, task_timeout, updated_at
    FROM public.strummy_eval_config
   LIMIT 1`;

// Postgres "undefined_table" — the harness migration isn't applied here.
const UNDEFINED_TABLE = '42P01';

export function registerEvalScoresRoutes(app: Hono): void {
  app.use('/api/eval_scores', viewerOrToken);

  app.get('/api/eval_scores', async (c) => {
    try {
      const [matrix, recent, overall, config] = await Promise.all([
        pool.query(MATRIX_SQL),
        pool.query(RECENT_SQL),
        pool.query(OVERALL_SQL),
        pool.query(CONFIG_SQL),
      ]);
      return c.json({
        available: true,
        matrix: matrix.rows,
        recent: recent.rows,
        overall: overall.rows[0] ?? null,
        config: config.rows[0] ?? null,
      });
    } catch (err) {
      if ((err as { code?: string }).code === UNDEFINED_TABLE) {
        return c.json({ available: false, matrix: [], recent: [], overall: null, config: null });
      }
      throw err;
    }
  });
}
