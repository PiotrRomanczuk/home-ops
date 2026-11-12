import type { Hono } from 'hono';
import { tokenOnly, viewerOrToken } from '../auth.ts';
import { pool } from '../db.ts';
import { parsePlaces } from '../storage-model.ts';

// storage_places (migration 029) — the vault storage register, one row per
// place note. planner-sync POSTs the full set when the notes change; the
// handler upserts by id and deletes ids that left the vault, in one
// transaction, like /api/projects/sync. Contract: docs/adr/2026-11-12-storage-places.md.

// ::text on dates — node-pg would turn a `date` into a local-midnight Date.
const COLS = `id, nazwa, gdzie, sciezka, rola, stan, porzadek, backup,
  sprawdzone::text AS sprawdzone, test_odtworzenia::text AS test_odtworzenia,
  sprawdzenie, problem, note_path, updated_at::text AS updated_at, synced_at`;

const UPSERT = `INSERT INTO public.storage_places
    (id, nazwa, gdzie, sciezka, rola, stan, porzadek, backup, sprawdzone, test_odtworzenia,
     sprawdzenie, problem, note_path, updated_at, synced_at, raw_frontmatter)
  VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, now(), $15::jsonb)
  ON CONFLICT (id) DO UPDATE SET
    nazwa = EXCLUDED.nazwa, gdzie = EXCLUDED.gdzie, sciezka = EXCLUDED.sciezka, rola = EXCLUDED.rola,
    stan = EXCLUDED.stan, porzadek = EXCLUDED.porzadek, backup = EXCLUDED.backup,
    sprawdzone = EXCLUDED.sprawdzone, test_odtworzenia = EXCLUDED.test_odtworzenia,
    sprawdzenie = EXCLUDED.sprawdzenie, problem = EXCLUDED.problem, note_path = EXCLUDED.note_path,
    updated_at = EXCLUDED.updated_at, synced_at = now(), raw_frontmatter = EXCLUDED.raw_frontmatter`;

// Filters the GET accepts; values are checked against the column's CHECK by Postgres.
const FILTERS = ['stan', 'porzadek', 'backup', 'gdzie'] as const;

export function registerStorageRoutes(app: Hono): void {
  app.use('/api/storage', viewerOrToken);
  app.use('/api/storage/*', viewerOrToken);
  app.post('/api/storage/sync', tokenOnly);

  app.post('/api/storage/sync', async (c) => {
    let body: unknown;
    try {
      body = await c.req.json();
    } catch {
      return c.json({ error: 'invalid json' }, 400);
    }
    const parsed = parsePlaces(body);
    if (typeof parsed === 'string') return c.json({ error: parsed }, 400);
    // An empty set would wipe the table — a broken vault clone, not a real register.
    if (parsed.places.length === 0) return c.json({ error: 'no valid places', rejected: parsed.rejected }, 400);

    const client = await pool.connect();
    try {
      await client.query('BEGIN');
      for (const p of parsed.places) {
        await client.query(UPSERT, [
          p.id,
          p.nazwa,
          p.gdzie,
          p.sciezka,
          p.rola,
          p.stan,
          p.porzadek,
          p.backup,
          p.sprawdzone,
          p.test_odtworzenia,
          p.sprawdzenie,
          p.problem,
          p.note_path,
          p.updated_at,
          JSON.stringify(p.raw_frontmatter),
        ]);
      }
      const ids = parsed.places.map((p) => p.id);
      const del = await client.query(`DELETE FROM public.storage_places WHERE id <> ALL($1::int[])`, [ids]);
      await client.query('COMMIT');
      return c.json({ upserted: ids.length, removed: del.rowCount ?? 0, rejected: parsed.rejected });
    } catch (err) {
      await client.query('ROLLBACK');
      console.error('storage sync failed:', err);
      return c.json({ error: 'db write failed' }, 503);
    } finally {
      client.release();
    }
  });

  app.get('/api/storage', async (c) => {
    const where: string[] = [];
    const params: string[] = [];
    for (const key of FILTERS) {
      const value = c.req.query(key);
      if (!value) continue;
      params.push(value);
      where.push(`${key} = $${params.length}`);
    }
    const sql = `SELECT ${COLS} FROM public.storage_places
      ${where.length ? `WHERE ${where.join(' AND ')}` : ''} ORDER BY id`;
    const r = await pool.query(sql, params);
    const count = (field: 'porzadek' | 'backup') =>
      r.rows.reduce<Record<string, number>>((acc, row) => {
        acc[row[field]] = (acc[row[field]] ?? 0) + 1;
        return acc;
      }, {});
    return c.json({
      places: r.rows,
      summary: { total: r.rowCount, porzadek: count('porzadek'), backup: count('backup') },
    });
  });
}
