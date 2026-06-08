import type { Hono } from 'hono';
import { viewerOrToken } from '../auth.ts';
import { pool } from '../db.ts';
import { LEVEL_RANK, LEVELS, type Level } from '../types.ts';

export function registerLogsRoutes(app: Hono): void {
  app.use('/api/logs', viewerOrToken);
  app.use('/api/sources', viewerOrToken);

  app.get('/api/logs', async (c) => {
    const hosts = c.req.queries('host') ?? [];
    const sources = c.req.queries('source') ?? [];
    const levelMin = (c.req.query('level_min') ?? 'debug') as Level;
    const sinceMin = Number(c.req.query('since_min') ?? '60');
    const grep = c.req.query('grep') ?? '';
    const after = Number(c.req.query('after') ?? '0');
    const limit = Math.min(Math.max(Number(c.req.query('limit') ?? '200'), 1), 1000);

    const params: unknown[] = [];
    const where: string[] = [];
    if (after > 0) {
      params.push(after);
      where.push(`id > $${params.length}`);
    }
    if (hosts.length) {
      params.push(hosts);
      where.push(`host = ANY($${params.length}::text[])`);
    }
    if (sources.length) {
      params.push(sources);
      where.push(`source = ANY($${params.length}::text[])`);
    }
    if (LEVEL_RANK[levelMin] > 0) {
      const allowed = LEVELS.filter((l) => LEVEL_RANK[l] >= LEVEL_RANK[levelMin]);
      params.push(allowed);
      where.push(`level = ANY($${params.length}::text[])`);
    }
    if (sinceMin > 0 && after === 0) {
      params.push(`${sinceMin} minutes`);
      where.push(`ts >= now() - $${params.length}::interval`);
    }
    if (grep) {
      params.push(`%${grep}%`);
      where.push(`(message ILIKE $${params.length} OR data::text ILIKE $${params.length})`);
    }

    const sql = `
      SELECT id, ts, host, source, level, message, data
      FROM public.host_logs
      ${where.length ? `WHERE ${where.join(' AND ')}` : ''}
      ORDER BY ${after > 0 ? 'id ASC' : 'id DESC'}
      LIMIT ${limit}
    `;
    const r = await pool.query(sql, params);
    return c.json({ rows: r.rows, latest_id: r.rows.length ? Number(r.rows.at(0)?.id ?? r.rows.at(-1)?.id ?? 0) : 0 });
  });

  app.get('/api/sources', async () => {
    const r = await pool.query(`
      SELECT host, ARRAY_AGG(DISTINCT source ORDER BY source) AS sources
      FROM public.host_logs
      WHERE ts > now() - INTERVAL '30 days'
      GROUP BY host
      ORDER BY host
    `);
    return Response.json({ hosts: r.rows });
  });
}
