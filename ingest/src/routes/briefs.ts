import type { Hono } from 'hono';
import { tokenOnly, viewerOrToken } from '../auth.ts';
import { pool } from '../db.ts';

// daily_briefs — morning/evening day briefs (migration 022). A cloud routine
// commits briefs/YYYY-MM-DD-<slot>.md to the daily-brief repo; brief-pull on
// elitedesk parses the frontmatter and POSTs here. Upsert on (date, slot) so
// a re-run or a re-pull is harmless. Contract: docs/adr/2026-10-17-daily-briefs.md.

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const SLOTS = new Set(['morning', 'evening']);
const MAX_BODY = 20_000;
const MAX_TITLE = 200;
const MAX_SOURCES = 20;
const MAX_SOURCE_LEN = 80;

// brief_date::text — node-pg would turn a `date` into a local-midnight Date.
export const BRIEF_COLS = `id, brief_date::text AS brief_date, slot, title, body_md, sources, generated_at, created_at`;

export interface BriefInput {
  date: string;
  slot: string;
  title: string | null;
  body_md: string;
  sources: string[];
  generated_at: string | null;
}

function isRealDate(s: string): boolean {
  return DATE_RE.test(s) && new Date(`${s}T00:00:00Z`).toISOString().slice(0, 10) === s;
}

function cleanSources(v: unknown): string[] | null {
  if (v === undefined || v === null) return [];
  if (!Array.isArray(v) || v.length > MAX_SOURCES) return null;
  const out: string[] = [];
  for (const s of v) {
    if (typeof s !== 'string' || !s.trim() || s.length > MAX_SOURCE_LEN) return null;
    out.push(s.trim());
  }
  return out;
}

/** Validate a POST body; returns the clean brief or an error message. */
export function parseBrief(body: Record<string, unknown>): BriefInput | string {
  const date = typeof body.date === 'string' ? body.date : '';
  if (!isRealDate(date)) return 'date required (YYYY-MM-DD)';
  const slot = typeof body.slot === 'string' ? body.slot : '';
  if (!SLOTS.has(slot)) return 'slot must be morning|evening';
  const bodyMd = typeof body.body_md === 'string' ? body.body_md.trim() : '';
  if (!bodyMd || bodyMd.length > MAX_BODY) return `body_md required (1..${MAX_BODY} chars)`;
  const title = body.title === undefined || body.title === null ? null : String(body.title).trim() || null;
  if (title && title.length > MAX_TITLE) return `title too long (max ${MAX_TITLE})`;
  const sources = cleanSources(body.sources);
  if (sources === null) return `sources: up to ${MAX_SOURCES} non-empty strings`;
  const gen = body.generated_at;
  if (gen !== undefined && gen !== null && (typeof gen !== 'string' || Number.isNaN(Date.parse(gen))))
    return 'generated_at must be an ISO 8601 timestamp';
  return { date, slot, title, body_md: bodyMd, sources, generated_at: (gen as string | null | undefined) ?? null };
}

export function registerBriefsRoutes(app: Hono): void {
  app.use('/api/briefs', viewerOrToken);
  app.use('/api/briefs/*', viewerOrToken);
  app.post('/api/briefs', tokenOnly);

  // Most recent brief: newest date first, evening beats morning on the same day.
  app.get('/api/briefs/latest', async (c) => {
    const r = await pool.query(
      `SELECT ${BRIEF_COLS} FROM public.daily_briefs
        ORDER BY brief_date DESC, (slot = 'evening') DESC LIMIT 1`,
    );
    return c.json({ brief: r.rows[0] ?? null });
  });

  // ?date=YYYY-MM-DD[&slot=] → that day's briefs; no date → last 14 days.
  app.get('/api/briefs', async (c) => {
    const date = c.req.query('date');
    const slot = c.req.query('slot');
    if (date !== undefined && !isRealDate(date)) return c.json({ error: 'invalid date' }, 400);
    if (slot !== undefined && !SLOTS.has(slot)) return c.json({ error: 'invalid slot' }, 400);
    const r = await pool.query(
      `SELECT ${BRIEF_COLS} FROM public.daily_briefs
        WHERE ($1::date IS NULL AND brief_date > current_date - 14 OR brief_date = $1::date)
          AND ($2::text IS NULL OR slot = $2::text)
        ORDER BY brief_date DESC, (slot = 'evening') DESC`,
      [date ?? null, slot ?? null],
    );
    return c.json({ briefs: r.rows });
  });

  app.post('/api/briefs', async (c) => {
    const body = (await c.req.json().catch(() => ({}))) as Record<string, unknown>;
    const b = parseBrief(body);
    if (typeof b === 'string') return c.json({ error: b }, 400);
    const r = await pool.query(
      `INSERT INTO public.daily_briefs (brief_date, slot, title, body_md, sources, generated_at)
       VALUES ($1::date, $2, $3, $4, $5::jsonb, $6::timestamptz)
       ON CONFLICT (brief_date, slot) DO UPDATE SET
         title = EXCLUDED.title, body_md = EXCLUDED.body_md, sources = EXCLUDED.sources,
         generated_at = EXCLUDED.generated_at, created_at = now()
       RETURNING ${BRIEF_COLS}, (xmax = 0) AS inserted`,
      [b.date, b.slot, b.title, b.body_md, JSON.stringify(b.sources), b.generated_at],
    );
    const { inserted, ...brief } = r.rows[0];
    return c.json({ brief, inserted }, inserted ? 201 : 200);
  });
}
