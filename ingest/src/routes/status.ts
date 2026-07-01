import type { Hono } from 'hono';
import { viewerOrToken } from '../auth.ts';
import { pool } from '../db.ts';

// GET /api/status — everything the glanceable dashboard needs in ONE round
// trip (the phone-on-LAN view polls this). Five cheap queries, one response.
export function registerStatusRoutes(app: Hono): void {
  app.use('/api/status', viewerOrToken);

  app.get('/api/status', async (c) => {
    const [hosts, levels, errors, jobs, db] = await Promise.all([
      // Per-host: last event, last metric + latest resource snapshot.
      pool.query(`
        SELECT
          COALESCE(m.host, e.host) AS host,
          e.last_event_ts, m.last_metric_ts,
          m.cpu_pct, m.mem_pct, m.disk_pct, m.gpu_pct, m.gpu_temp_c,
          m.data
        FROM (
          SELECT DISTINCT ON (host)
            host, ts AS last_metric_ts,
            cpu_pct, mem_pct, disk_pct, gpu_pct, gpu_temp_c, data
          FROM public.host_metrics
          WHERE ts > now() - INTERVAL '7 days'
          ORDER BY host, ts DESC
        ) m
        FULL OUTER JOIN (
          SELECT host, max(ts) AS last_event_ts
          FROM public.host_logs
          WHERE ts > now() - INTERVAL '7 days'
          GROUP BY host
        ) e ON e.host = m.host
        ORDER BY 1
      `),
      pool.query(`
        SELECT level, count(*)::int AS n
        FROM public.host_logs
        WHERE ts > now() - INTERVAL '60 minutes' AND level IN ('warn','error','fatal')
        GROUP BY level
      `),
      pool.query(`
        SELECT ts, host, source, level, message
        FROM public.host_logs
        WHERE ts > now() - INTERVAL '24 hours' AND level IN ('error','fatal')
        ORDER BY ts DESC LIMIT 5
      `),
      pool.query(`
        SELECT status::text, count(*)::int AS n
        FROM public.gpu_jobs
        GROUP BY status
      `),
      pool.query(`SELECT pg_size_pretty(pg_database_size(current_database())) AS db_size`),
    ]);

    const levelCounts: Record<string, number> = { warn: 0, error: 0, fatal: 0 };
    for (const r of levels.rows) levelCounts[r.level] = r.n;
    const jobCounts: Record<string, number> = {};
    for (const r of jobs.rows) jobCounts[r.status] = r.n;

    return c.json({
      now: new Date().toISOString(),
      hosts: hosts.rows,
      levels_1h: levelCounts,
      recent_errors: errors.rows,
      jobs: jobCounts,
      db_size: db.rows[0]?.db_size ?? null,
    });
  });
}
