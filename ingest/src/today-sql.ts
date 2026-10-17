// SQL behind GET /api/today — the console's default "Dziś" tab. Problems and
// hosts reuse PROBLEMS_SQL / HOSTS_SQL from digest-sql.ts so the page and the
// email agree on what needs attention. All read-only.

import { BRIEF_COLS } from './routes/briefs.ts';

// "Today" is Warsaw's calendar day, not the container's UTC one.
const TODAY = `(now() AT TIME ZONE 'Europe/Warsaw')::date`;

// Today's evening brief, else today's morning, else the most recent one.
export const LATEST_BRIEF_SQL = `
  SELECT ${BRIEF_COLS}, brief_date = ${TODAY} AS is_today
    FROM public.daily_briefs
   ORDER BY (brief_date = ${TODAY}) DESC, brief_date DESC, (slot = 'evening') DESC
   LIMIT 1`;

// Unchecked `- [ ]` lines from the vault's Now section of every hot/warm
// project — the NEXT_SQL unnest pattern, across projects instead of one slug.
export const NOW_TASKS_SQL = `
  SELECT p.slug, p.title, p.status, t.ord::int AS ord,
         regexp_replace(regexp_replace(t.line, '^\\s*[-*]\\s+\\[ \\]\\s+', ''), '\\*\\*', '', 'g') AS text
    FROM public.projects p,
         unnest(string_to_array(p.now_md, E'\\n')) WITH ORDINALITY AS t(line, ord)
   WHERE p.status IN ('hot', 'warm') AND t.line ~ '^\\s*[-*]\\s+\\[ \\]'
   ORDER BY CASE p.status WHEN 'hot' THEN 0 ELSE 1 END, p.updated_at DESC, t.ord
   LIMIT 80`;

// Board cards in the Now column that are not done (DB-authoritative kanban).
export const BOARD_NOW_SQL = `
  SELECT b.slug, p.title, p.status, b.position AS ord, b.is_focus,
         regexp_replace(b.text, '\\*\\*', '', 'g') AS text
    FROM public.board_tasks b
    LEFT JOIN public.projects p ON p.slug = b.slug
   WHERE b.column_key = 'now' AND NOT b.done
   ORDER BY b.is_focus DESC, b.slug, b.position
   LIMIT 40`;

// Open decisions — no signed links: this endpoint is viewer-readable.
export const OPEN_DECISIONS_SQL = `
  SELECT id, routine, slug, question, context_url, created_at, expires_at
    FROM public.decisions
   WHERE answer IS NULL AND expires_at >= now()
   ORDER BY created_at LIMIT 10`;

// Latest card per routine, only while still fresh.
export const FRESH_CARDS_SQL = `
  SELECT * FROM (
    SELECT DISTINCT ON (routine) id, routine, slug, ran_at, status, headline, items, metric,
           (ran_at + fresh_for) > now() AS is_fresh
      FROM public.digest_cards ORDER BY routine, ran_at DESC
  ) latest
   WHERE is_fresh
   ORDER BY ran_at DESC`;
