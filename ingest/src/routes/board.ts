import type { Hono } from 'hono';
import { tokenOnly, viewerOrToken } from '../auth.ts';
import { pool } from '../db.ts';

// Board tab — DB-authoritative kanban over board_tasks. column_key mirrors the
// vault Now/Next/Later; planner-sync renders rows back into projects/<slug>.md.
// Moves/reorders are optimistic on the client (see public/board-api.js); the
// server owns position renumbering and the single-focus invariant.

const COLUMNS = new Set(['now', 'next', 'later']);
const SLUG_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const MAX_TEXT = 2000;

const COLS = 'id, slug, column_key, text, done, is_focus, position, created_at, updated_at';

function cleanText(v: unknown): string | null {
  if (typeof v !== 'string') return null;
  const t = v.trim();
  if (!t || t.length > MAX_TEXT) return null;
  return t;
}

export function registerBoardRoutes(app: Hono): void {
  // Bulk import (seed + vault→board reconciliation) is worker-only.
  app.use('/api/board/import', tokenOnly);
  app.use('/api/board', viewerOrToken);
  app.use('/api/board/*', viewerOrToken);

  // List a project's cards + a change watermark (planner-sync polls this).
  app.get('/api/board', async (c) => {
    const slug = c.req.query('slug') || 'home-ops';
    if (!SLUG_RE.test(slug)) return c.json({ error: 'invalid slug' }, 400);
    const r = await pool.query(
      `SELECT ${COLS} FROM public.board_tasks
        WHERE slug = $1
        ORDER BY array_position(ARRAY['now','next','later'], column_key), position, id`,
      [slug],
    );
    const w = await pool.query(`SELECT max(updated_at) AS updated_at FROM public.board_tasks WHERE slug = $1`, [slug]);
    return c.json({ tasks: r.rows, updatedAt: w.rows[0]?.updated_at ?? null });
  });

  // Create a card, appended to the end of its column.
  app.post('/api/board', async (c) => {
    const body = (await c.req.json().catch(() => ({}))) as {
      slug?: string;
      column?: string;
      text?: string;
    };
    const slug = body.slug || 'home-ops';
    if (!SLUG_RE.test(slug)) return c.json({ error: 'invalid slug' }, 400);
    if (!body.column || !COLUMNS.has(body.column)) return c.json({ error: 'invalid column' }, 400);
    const text = cleanText(body.text);
    if (text == null) return c.json({ error: `text required (1..${MAX_TEXT} chars)` }, 400);
    const r = await pool.query(
      `INSERT INTO public.board_tasks (slug, column_key, text, position)
       VALUES ($1, $2, $3,
         COALESCE((SELECT max(position) + 1 FROM public.board_tasks WHERE slug = $1 AND column_key = $2), 0))
       RETURNING ${COLS}`,
      [slug, body.column, text],
    );
    return c.json({ task: r.rows[0] }, 201);
  });

  // Move / reorder. The client sends the resulting ordered id list for the
  // target column (and the source column when it changed); the server sets
  // column_key on the moved card then renumbers positions transactionally.
  app.post('/api/board/:id/move', async (c) => {
    const id = Number(c.req.param('id'));
    if (!Number.isInteger(id)) return c.json({ error: 'invalid id' }, 400);
    const body = (await c.req.json().catch(() => ({}))) as {
      column?: string;
      order?: number[];
      fromColumn?: string;
      fromOrder?: number[];
    };
    if (!body.column || !COLUMNS.has(body.column)) return c.json({ error: 'invalid column' }, 400);
    if (!Array.isArray(body.order)) return c.json({ error: 'order (array) required' }, 400);

    const client = await pool.connect();
    try {
      await client.query('BEGIN');
      const cur = await client.query(`SELECT slug FROM public.board_tasks WHERE id = $1`, [id]);
      if (cur.rowCount === 0) {
        await client.query('ROLLBACK');
        return c.json({ error: 'not found' }, 404);
      }
      const slug = cur.rows[0].slug as string;
      await client.query(`UPDATE public.board_tasks SET column_key = $2, updated_at = now() WHERE id = $1`, [
        id,
        body.column,
      ]);
      const renumber = async (order: number[]) => {
        for (let i = 0; i < order.length; i++) {
          await client.query(
            `UPDATE public.board_tasks SET position = $3, updated_at = now()
              WHERE id = $1 AND slug = $2`,
            [order[i], slug, i],
          );
        }
      };
      await renumber(body.order);
      if (body.fromColumn && COLUMNS.has(body.fromColumn) && Array.isArray(body.fromOrder)) {
        await renumber(body.fromOrder);
      }
      await client.query('COMMIT');
    } catch (e) {
      await client.query('ROLLBACK');
      throw e;
    } finally {
      client.release();
    }
    const r = await pool.query(`SELECT ${COLS} FROM public.board_tasks WHERE id = $1`, [id]);
    return c.json({ task: r.rows[0] });
  });

  // Edit text / done / focus. Pinning focus clears the project's other focuses.
  app.post('/api/board/:id/update', async (c) => {
    const id = Number(c.req.param('id'));
    if (!Number.isInteger(id)) return c.json({ error: 'invalid id' }, 400);
    const body = (await c.req.json().catch(() => ({}))) as {
      text?: string;
      done?: boolean;
      is_focus?: boolean;
    };
    const hasText = 'text' in body;
    const hasDone = 'done' in body;
    const hasFocus = 'is_focus' in body;
    if (!hasText && !hasDone && !hasFocus) return c.json({ error: 'nothing to update' }, 400);
    let text: string | null = null;
    if (hasText) {
      text = cleanText(body.text);
      if (text == null) return c.json({ error: `text must be 1..${MAX_TEXT} chars` }, 400);
    }

    const client = await pool.connect();
    try {
      await client.query('BEGIN');
      const cur = await client.query(`SELECT slug FROM public.board_tasks WHERE id = $1`, [id]);
      if (cur.rowCount === 0) {
        await client.query('ROLLBACK');
        return c.json({ error: 'not found' }, 404);
      }
      if (hasFocus && body.is_focus === true) {
        await client.query(
          `UPDATE public.board_tasks SET is_focus = false, updated_at = now()
            WHERE slug = $1 AND is_focus AND id <> $2`,
          [cur.rows[0].slug, id],
        );
      }
      await client.query(
        `UPDATE public.board_tasks
            SET text = CASE WHEN $2 THEN $3 ELSE text END,
                done = CASE WHEN $4 THEN $5 ELSE done END,
                is_focus = CASE WHEN $6 THEN $7 ELSE is_focus END,
                updated_at = now()
          WHERE id = $1`,
        [id, hasText, text, hasDone, body.done ?? false, hasFocus, body.is_focus ?? false],
      );
      await client.query('COMMIT');
    } catch (e) {
      await client.query('ROLLBACK');
      throw e;
    } finally {
      client.release();
    }
    const r = await pool.query(`SELECT ${COLS} FROM public.board_tasks WHERE id = $1`, [id]);
    return c.json({ task: r.rows[0] });
  });

  app.post('/api/board/:id/delete', async (c) => {
    const id = Number(c.req.param('id'));
    if (!Number.isInteger(id)) return c.json({ error: 'invalid id' }, 400);
    const r = await pool.query(`DELETE FROM public.board_tasks WHERE id = $1`, [id]);
    if (r.rowCount === 0) return c.json({ error: 'not found' }, 404);
    return c.json({ ok: true });
  });

  // Replace all cards for a slug (planner-sync: seed on first run + import
  // Obsidian-only edits). Positions follow array order within each column;
  // focus is re-pinned by matching text so an Obsidian edit doesn't lose it.
  app.post('/api/board/import', async (c) => {
    const body = (await c.req.json().catch(() => ({}))) as {
      slug?: string;
      tasks?: Array<{ column?: string; text?: string; done?: boolean }>;
      focusText?: string | null;
    };
    const slug = body.slug || 'home-ops';
    if (!SLUG_RE.test(slug)) return c.json({ error: 'invalid slug' }, 400);
    if (!Array.isArray(body.tasks)) return c.json({ error: 'tasks (array) required' }, 400);
    const rows: Array<{ column: string; text: string; done: boolean }> = [];
    for (const t of body.tasks) {
      const text = cleanText(t?.text);
      if (!t?.column || !COLUMNS.has(t.column) || text == null) continue;
      rows.push({ column: t.column, text, done: t.done === true });
    }
    const focusText = typeof body.focusText === 'string' ? body.focusText.trim() : null;

    const client = await pool.connect();
    try {
      await client.query('BEGIN');
      await client.query(`DELETE FROM public.board_tasks WHERE slug = $1`, [slug]);
      const posByCol: Record<string, number> = { now: 0, next: 0, later: 0 };
      let focusPinned = false;
      for (const row of rows) {
        const isFocus = !focusPinned && focusText != null && row.text === focusText;
        if (isFocus) focusPinned = true;
        const pos = posByCol[row.column] ?? 0;
        posByCol[row.column] = pos + 1;
        await client.query(
          `INSERT INTO public.board_tasks (slug, column_key, text, done, position, is_focus)
           VALUES ($1, $2, $3, $4, $5, $6)`,
          [slug, row.column, row.text, row.done, pos, isFocus],
        );
      }
      await client.query('COMMIT');
    } catch (e) {
      await client.query('ROLLBACK');
      throw e;
    } finally {
      client.release();
    }
    const w = await pool.query(`SELECT max(updated_at) AS updated_at FROM public.board_tasks WHERE slug = $1`, [slug]);
    return c.json({ count: rows.length, updatedAt: w.rows[0]?.updated_at ?? null });
  });
}
