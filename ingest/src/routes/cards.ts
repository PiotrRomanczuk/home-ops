import type { Hono } from 'hono';
import { tokenOnly, viewerOrToken } from '../auth.ts';
import { pool } from '../db.ts';

// digest_cards — the routine → digest contract (migration 020). A routine
// posts one card at the end of each run; the digest and the console read the
// latest card per routine. Validation is strict on purpose: a card is the one
// sentence Piotr reads about that routine, so the shape must stay small.

const ROUTINE_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const SLUG_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const STATUSES = new Set(['ok', 'warn', 'fail', 'skipped']);
const MAX_HEADLINE = 200;
const MAX_ITEMS = 5;
const MAX_ITEM_TEXT = 160;

const COLS = 'id, routine, slug, ran_at, status, headline, items, metric, fresh_for, created_at';

interface CardItem {
  text: string;
  url?: string;
}

function cleanItems(v: unknown): CardItem[] | null {
  if (v === undefined) return [];
  if (!Array.isArray(v) || v.length > MAX_ITEMS) return null;
  const out: CardItem[] = [];
  for (const raw of v) {
    if (!raw || typeof raw !== 'object') return null;
    const { text, url } = raw as { text?: unknown; url?: unknown };
    if (typeof text !== 'string' || !text.trim() || text.length > MAX_ITEM_TEXT) return null;
    if (url !== undefined && (typeof url !== 'string' || !/^https?:\/\//.test(url))) return null;
    out.push(url ? { text: text.trim(), url } : { text: text.trim() });
  }
  return out;
}

function cleanMetric(v: unknown): Record<string, unknown> | null | undefined {
  if (v === undefined || v === null) return null;
  if (!v || typeof v !== 'object') return undefined;
  const m = v as { label?: unknown; value?: unknown; delta?: unknown; unit?: unknown; lower_is_better?: unknown };
  if (typeof m.label !== 'string' || !m.label.trim() || m.label.length > 40) return undefined;
  if (typeof m.value !== 'number' && typeof m.value !== 'string') return undefined;
  if (m.delta !== undefined && typeof m.delta !== 'number') return undefined;
  if (m.unit !== undefined && typeof m.unit !== 'string') return undefined;
  // lower_is_better: a falling delta is good news (errors, crawl findings).
  const lowerIsBetter = m.lower_is_better === true ? true : undefined;
  return { label: m.label.trim(), value: m.value, delta: m.delta, unit: m.unit, lower_is_better: lowerIsBetter };
}

export function registerCardsRoutes(app: Hono): void {
  app.use('/api/cards', viewerOrToken);
  app.post('/api/cards', tokenOnly);

  // Latest card per routine (default), or a routine's history with ?routine=.
  app.get('/api/cards', async (c) => {
    const routine = c.req.query('routine');
    if (routine) {
      if (!ROUTINE_RE.test(routine)) return c.json({ error: 'invalid routine' }, 400);
      const days = Math.min(Number(c.req.query('days') || 14), 90);
      const r = await pool.query(
        `SELECT ${COLS} FROM public.digest_cards
          WHERE routine = $1 AND ran_at > now() - make_interval(days => $2::int)
          ORDER BY ran_at DESC`,
        [routine, days],
      );
      return c.json({ cards: r.rows });
    }
    const r = await pool.query(
      `SELECT DISTINCT ON (routine) ${COLS},
              (ran_at + fresh_for) > now() AS is_fresh
         FROM public.digest_cards
        ORDER BY routine, ran_at DESC`,
    );
    return c.json({ cards: r.rows });
  });

  app.post('/api/cards', async (c) => {
    const body = (await c.req.json().catch(() => ({}))) as Record<string, unknown>;
    const routine = typeof body.routine === 'string' ? body.routine : '';
    if (!ROUTINE_RE.test(routine)) return c.json({ error: 'routine required (slug-like)' }, 400);
    const slug = body.slug === undefined || body.slug === null ? null : String(body.slug);
    if (slug !== null && !SLUG_RE.test(slug)) return c.json({ error: 'invalid slug' }, 400);
    const status = body.status === undefined ? 'ok' : String(body.status);
    if (!STATUSES.has(status)) return c.json({ error: 'status must be ok|warn|fail|skipped' }, 400);
    const headline = typeof body.headline === 'string' ? body.headline.trim() : '';
    if (!headline || headline.length > MAX_HEADLINE)
      return c.json({ error: `headline required (1..${MAX_HEADLINE})` }, 400);
    const items = cleanItems(body.items);
    if (items === null) return c.json({ error: `items: up to ${MAX_ITEMS} of {text, url?}` }, 400);
    const metric = cleanMetric(body.metric);
    if (metric === undefined) return c.json({ error: 'metric: {label, value, delta?, unit?}' }, 400);
    const freshHours = body.fresh_hours === undefined ? 26 : Number(body.fresh_hours);
    if (!Number.isFinite(freshHours) || freshHours < 1 || freshHours > 24 * 14) {
      return c.json({ error: 'fresh_hours must be 1..336' }, 400);
    }
    const r = await pool.query(
      `INSERT INTO public.digest_cards (routine, slug, status, headline, items, metric, fresh_for)
       VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, make_interval(hours => $7::int))
       RETURNING ${COLS}`,
      [routine, slug, status, headline, JSON.stringify(items), metric ? JSON.stringify(metric) : null, freshHours],
    );
    return c.json({ card: r.rows[0] }, 201);
  });
}
