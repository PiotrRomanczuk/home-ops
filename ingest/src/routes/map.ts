import type { Hono } from 'hono';
import { viewerOrToken } from '../auth.ts';
import { pool } from '../db.ts';
import { buildMap, type MapProcessRow } from '../map-model.ts';
import { rankPressure } from '../pressure-model.ts';
import { loadRuntime, PRESSURE_COLUMNS } from './pressure.ts';

// GET /api/map — project ecosystem graph for the Mapa tab (see map-model.ts),
// with each project's pressure score (pressure-model.ts) on its node.
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
    const [projects, processes, rt] = await Promise.all([
      pool.query(`SELECT ${PRESSURE_COLUMNS} FROM public.projects ORDER BY slug`),
      processRows(),
      loadRuntime(),
    ]);
    const map = buildMap(projects.rows, processes);
    const dependents = new Map(map.nodes.map((n) => [n.id, n.dependents]));
    const scores = new Map(rankPressure(projects.rows, dependents, rt).map((r) => [r.slug.toLowerCase(), r.score]));
    for (const n of map.nodes) n.pressure = scores.get(n.id) ?? null;
    return c.json(map);
  });
}
