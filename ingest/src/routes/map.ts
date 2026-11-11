import type { Hono } from 'hono';
import { viewerOrToken } from '../auth.ts';
import { pool } from '../db.ts';
import { buildMap, type MapProcessRow } from '../map-model.ts';

// GET /api/map — project ecosystem graph for the Mapa tab (see map-model.ts).
// Processes come from migration 029; until it is applied the map still
// renders, just without process overlays.

const UNDEFINED_TABLE = '42P01';

async function processRows(): Promise<MapProcessRow[]> {
  try {
    const r = await pool.query('SELECT slug, title, lanes, warnings FROM public.processes ORDER BY slug');
    return r.rows;
  } catch (e) {
    if ((e as { code?: string }).code === UNDEFINED_TABLE) return [];
    throw e;
  }
}

export function registerMapRoutes(app: Hono): void {
  app.use('/api/map', viewerOrToken);

  app.get('/api/map', async (c) => {
    const [projects, processes] = await Promise.all([
      pool.query('SELECT slug, title, status, raw_frontmatter FROM public.projects ORDER BY slug'),
      processRows(),
    ]);
    return c.json(buildMap(projects.rows, processes));
  });
}
