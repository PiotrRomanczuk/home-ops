import type { Hono } from 'hono';
import { viewerOrToken } from '../auth.ts';
import { pool } from '../db.ts';
import { buildMap } from '../map-model.ts';
import { type Runtime, rankPressure, WEIGHTS } from '../pressure-model.ts';
import { MUTED } from './digest.ts';

// GET /api/pressure — projects ranked by how much attention they need (see
// pressure-model.ts). Runtime signals: distinct error patterns per
// `app:<slug>` in 24 h (digest mutes respected; rpi-sentinel outage rows are
// counted as "down" instead), and the latest rpi-sentinel verdict per deploy.

export const PRESSURE_COLUMNS = 'slug, title, status, raw_frontmatter, now_md, next_md, pain_md, repo_meta';

const ERRORS_SQL = `
  SELECT lower(substr(source, 5)) AS slug, left(regexp_replace(message, '[0-9]+', 'N', 'g'), 120) AS pattern
    FROM public.host_logs
   WHERE source LIKE 'app:%' AND level IN ('error', 'fatal') AND ts > now() - interval '24 hours'
     AND message NOT LIKE 'deploy unreachable from rpi%'
   GROUP BY 1, 2`;

const DOWN_SQL = `
  SELECT DISTINCT ON (source) lower(substr(source, 5)) AS slug, message LIKE 'deploy unreachable%' AS is_down
    FROM public.host_logs
   WHERE source LIKE 'app:%' AND ts > now() - interval '7 days'
     AND (message LIKE 'deploy unreachable from rpi%' OR message LIKE 'deploy reachable again from rpi%')
   ORDER BY source, ts DESC`;

export async function loadRuntime(): Promise<Runtime> {
  const [errors, down] = await Promise.all([pool.query(ERRORS_SQL), pool.query(DOWN_SQL)]);
  const errorPatterns = new Map<string, number>();
  for (const r of errors.rows as Array<{ slug: string; pattern: string }>) {
    if (MUTED.some((re) => re.test(r.pattern))) continue;
    errorPatterns.set(r.slug, (errorPatterns.get(r.slug) ?? 0) + 1);
  }
  const downSet = new Set(
    (down.rows as Array<{ slug: string; is_down: boolean }>).filter((r) => r.is_down).map((r) => r.slug),
  );
  return { errorPatterns, down: downSet };
}

export function registerPressureRoutes(app: Hono): void {
  app.use('/api/pressure', viewerOrToken);

  app.get('/api/pressure', async (c) => {
    const [projects, rt] = await Promise.all([
      pool.query(`SELECT ${PRESSURE_COLUMNS} FROM public.projects`),
      loadRuntime(),
    ]);
    const map = buildMap(projects.rows);
    const dependents = new Map(map.nodes.map((n) => [n.id, n.dependents]));
    return c.json({ projects: rankPressure(projects.rows, dependents, rt), weights: WEIGHTS });
  });
}
