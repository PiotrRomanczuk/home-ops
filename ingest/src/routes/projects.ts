import type { Hono } from 'hono';
import { tokenOnly, viewerOrToken } from '../auth.ts';
import { pool } from '../db.ts';

interface ProjectRecord {
  slug: string;
  title?: string | null;
  status?: 'hot' | 'warm' | 'dormant' | 'stalled' | null;
  path?: string | null;
  last_commit?: string | null;
  commits_30d?: number | null;
  updated_at?: string | null;
  now_md?: string | null;
  next_md?: string | null;
  later_md?: string | null;
  pain_md?: string | null;
  notes_md?: string | null;
  raw_frontmatter?: Record<string, unknown> | null;
}

const STATUSES = new Set(['hot', 'warm', 'dormant', 'stalled']);

function validProject(p: unknown): p is ProjectRecord {
  if (!p || typeof p !== 'object') return false;
  const x = p as ProjectRecord;
  if (typeof x.slug !== 'string' || !x.slug || x.slug.length > 128) return false;
  if (x.status != null && !STATUSES.has(x.status as string)) return false;
  return true;
}

export function registerProjectsRoutes(app: Hono): void {
  app.use('/api/projects', viewerOrToken);
  app.use('/api/projects/*', viewerOrToken);

  // Sync ingest: the vault worker POSTs the full set of projects every tick.
  // We upsert each row and delete any slugs absent from the payload, so a
  // project file deleted from the vault stops showing in the UI on the next
  // tick. Wrapped in a transaction so a half-applied sync can't leave the
  // table in a torn state.
  app.use('/api/projects/sync', tokenOnly);
  app.post('/api/projects/sync', async (c) => {
    let body: unknown;
    try {
      body = await c.req.json();
    } catch {
      return c.json({ error: 'invalid json' }, 400);
    }
    const raw =
      body && typeof body === 'object' && 'projects' in body ? (body as { projects: unknown }).projects : null;
    if (!Array.isArray(raw)) return c.json({ error: 'projects array required' }, 400);
    if (raw.length > 200) return c.json({ error: 'too many projects (max 200)' }, 413);
    const rows: ProjectRecord[] = [];
    const rejected: Array<{ index: number; reason: string }> = [];
    raw.forEach((p, i) => {
      if (validProject(p)) rows.push(p);
      else rejected.push({ index: i, reason: 'invalid project' });
    });

    const client = await pool.connect();
    try {
      await client.query('BEGIN');
      for (const p of rows) {
        await client.query(
          `INSERT INTO public.projects
             (slug, title, status, path, last_commit, commits_30d,
              updated_at, synced_at, now_md, next_md, later_md, pain_md, notes_md, raw_frontmatter)
           VALUES ($1, $2, COALESCE($3, 'dormant'), $4, $5, COALESCE($6, 0),
                   COALESCE($7::timestamptz, now()), now(),
                   $8, $9, $10, $11, $12, COALESCE($13::jsonb, '{}'::jsonb))
           ON CONFLICT (slug) DO UPDATE SET
             title = EXCLUDED.title,
             status = EXCLUDED.status,
             path = EXCLUDED.path,
             last_commit = EXCLUDED.last_commit,
             commits_30d = EXCLUDED.commits_30d,
             updated_at = EXCLUDED.updated_at,
             synced_at = now(),
             now_md = EXCLUDED.now_md,
             next_md = EXCLUDED.next_md,
             later_md = EXCLUDED.later_md,
             pain_md = EXCLUDED.pain_md,
             notes_md = EXCLUDED.notes_md,
             raw_frontmatter = EXCLUDED.raw_frontmatter`,
          [
            p.slug,
            p.title ?? null,
            p.status ?? null,
            p.path ?? null,
            p.last_commit ?? null,
            p.commits_30d ?? null,
            p.updated_at ?? null,
            p.now_md ?? null,
            p.next_md ?? null,
            p.later_md ?? null,
            p.pain_md ?? null,
            p.notes_md ?? null,
            p.raw_frontmatter ? JSON.stringify(p.raw_frontmatter) : null,
          ],
        );
      }
      const keepSlugs = rows.map((r) => r.slug);
      const del = await client.query(`DELETE FROM public.projects WHERE slug <> ALL($1::text[]) RETURNING slug`, [
        keepSlugs,
      ]);
      await client.query('COMMIT');
      return c.json({ upserted: rows.length, removed: del.rowCount ?? 0, rejected });
    } catch (err) {
      await client.query('ROLLBACK');
      console.error('projects sync failed:', err);
      return c.json({ error: 'db write failed' }, 503);
    } finally {
      client.release();
    }
  });

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
