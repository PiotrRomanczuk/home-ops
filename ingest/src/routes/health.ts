import type { Hono } from 'hono';
import { pool } from '../db.ts';

export function registerHealthRoutes(app: Hono): void {
  app.get('/api/health', async (c) => {
    try {
      await pool.query('SELECT 1');
      return c.json({ ok: true });
    } catch (err) {
      return c.json({ ok: false, error: (err as Error).message }, 503);
    }
  });
}
