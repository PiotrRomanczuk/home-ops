import type { Hono } from 'hono';
import { viewerOrToken } from '../auth.ts';
import { pool } from '../db.ts';

export function registerProjectsRoutes(app: Hono): void {
  app.use('/api/projects', viewerOrToken);
  app.use('/api/projects/*', viewerOrToken);

  app.get('/api/projects', async (c) => {
    const status = c.req.query('status');
    const params: unknown[] = [];
    let where = '';
    if (status) {
      params.push(status);
      where = 'WHERE status = $1';
    }
    const sql = `
      SELECT slug, title, status, path, last_commit, commits_30d,
             updated_at, synced_at,
             now_md, next_md, later_md, pain_md,
             raw_frontmatter
      FROM public.projects
      ${where}
      ORDER BY
        CASE status
          WHEN 'hot' THEN 0
          WHEN 'warm' THEN 1
          WHEN 'dormant' THEN 2
          WHEN 'stalled' THEN 3
        END,
        updated_at DESC
    `;
    const r = await pool.query(sql, params);
    return c.json({ projects: r.rows });
  });

  app.get('/api/projects/:slug', async (c) => {
    const slug = c.req.param('slug');
    const r = await pool.query(`SELECT * FROM public.projects WHERE slug = $1`, [slug]);
    if (r.rowCount === 0) return c.json({ error: 'not found' }, 404);
    return c.json({ project: r.rows[0] });
  });
}
