import type { Hono } from 'hono';
import { tokenOnly, viewerOrToken } from '../auth.ts';
import { pool } from '../db.ts';
import { buildProgress, MOVEMENT, parseSignalsBody } from '../progress-model.ts';

// How projects move forward (migration 027). Writers POST daily counts:
// github-repo-sync replaces its 12-week window, planner-sync adds vault ticks.
// GET /api/progress folds them into weekly series per project, plus routine
// runs from unit_runs (026). Weeks and "today" are Warsaw-local.

const TZ = 'Europe/Warsaw';

// Sums duplicates inside one batch — ON CONFLICT can't touch a row twice.
const upsertSql = (replace: boolean) => `
  INSERT INTO public.project_signals (project_slug, day, signal, n)
  SELECT r.project_slug, r.day, r.signal, sum(r.n)
  FROM jsonb_to_recordset($1::jsonb) AS r(project_slug text, day date, signal text, n int)
  GROUP BY 1, 2, 3
  ON CONFLICT (project_slug, day, signal) DO UPDATE
    SET n = ${replace ? 'EXCLUDED.n' : 'project_signals.n + EXCLUDED.n'}, updated_at = now()`;

export function registerProgressRoutes(app: Hono): void {
  app.use('/api/progress', viewerOrToken);
  app.use('/api/progress/*', viewerOrToken);
  app.post('/api/progress/*', tokenOnly);

  app.post('/api/progress/signals', async (c) => {
    let raw: unknown;
    try {
      raw = await c.req.json();
    } catch {
      return c.json({ error: 'invalid json' }, 400);
    }
    const body = parseSignalsBody(raw);
    if (typeof body === 'string') return c.json({ error: body }, 400);
    const client = await pool.connect();
    try {
      await client.query('BEGIN');
      if (body.replace) {
        const { projects, signals, from, to } = body.replace;
        await client.query(
          `DELETE FROM public.project_signals
           WHERE project_slug = ANY($1) AND signal = ANY($2) AND day BETWEEN $3 AND $4`,
          [projects, signals, from, to],
        );
      }
      if (body.rows.length) await client.query(upsertSql(!!body.replace), [JSON.stringify(body.rows)]);
      await client.query('COMMIT');
    } catch (e) {
      await client.query('ROLLBACK');
      throw e;
    } finally {
      client.release();
    }
    return c.json({ written: body.rows.length, mode: body.replace ? 'replace' : 'add' });
  });

  app.get('/api/progress', async (c) => {
    const n = Number.parseInt(c.req.query('weeks') ?? '', 10);
    const weeksN = Number.isFinite(n) ? Math.min(52, Math.max(2, n)) : 12;
    const head = await pool.query(
      `SELECT to_char((now() AT TIME ZONE $2)::date, 'YYYY-MM-DD') AS today,
              array(SELECT to_char(d, 'YYYY-MM-DD') FROM generate_series(
                date_trunc('week', now() AT TIME ZONE $2) - make_interval(weeks => $1 - 1),
                date_trunc('week', now() AT TIME ZONE $2), interval '1 week') d) AS weeks`,
      [weeksN, TZ],
    );
    const { today, weeks } = head.rows[0] as { today: string; weeks: string[] };
    const from = weeks[0];
    const [projects, signals, runs, lastMoved] = await Promise.all([
      pool.query(`SELECT slug, title, status, raw_frontmatter->>'health' AS health,
          raw_frontmatter->>'verdict' AS verdict, repo_meta->'ci' AS ci,
          repo_meta->>'last_deploy_at' AS last_deploy_at FROM public.projects`),
      pool.query(
        `SELECT project_slug, to_char(date_trunc('week', day), 'YYYY-MM-DD') AS week, signal, sum(n)::int AS n
         FROM public.project_signals WHERE day >= $1 GROUP BY 1, 2, 3`,
        [from],
      ),
      pool.query(
        `SELECT project_slug, to_char(date_trunc('week', started_at AT TIME ZONE $2), 'YYYY-MM-DD') AS week,
           count(*) FILTER (WHERE result = 'ok')::int AS ok,
           coalesce(sum(repeat_count) FILTER (WHERE result = 'failed'), 0)::int AS failed
         FROM public.unit_runs WHERE project_slug IS NOT NULL AND started_at >= $1::date GROUP BY 1, 2`,
        [from, TZ],
      ),
      pool.query(
        `SELECT project_slug, to_char(max(day), 'YYYY-MM-DD') AS last_moved
         FROM public.project_signals WHERE signal = ANY($1) AND n > 0 GROUP BY 1`,
        [MOVEMENT],
      ),
    ]);
    return c.json(
      buildProgress({
        weeks,
        today,
        projects: projects.rows,
        signals: signals.rows,
        runs: runs.rows,
        lastMoved: lastMoved.rows,
      }),
    );
  });
}
