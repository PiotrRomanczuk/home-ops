-- 022_daily_briefs.sql
-- Created: 2026-10-17
--
-- Morning / evening briefs written by a cloud routine (Claude Code routine →
-- repo PiotrRomanczuk/daily-brief, briefs/YYYY-MM-DD-<slot>.md). elitedesk
-- pulls that repo every 15 min (ops/elitedesk/brief-pull.py) and upserts each
-- file here via POST /api/briefs, so the console's "Dziś" tab can show it
-- without exposing the API to the internet. See
-- docs/adr/2026-10-17-daily-briefs.md for the file contract.
--
-- One row per (brief_date, slot): a re-generated brief replaces the old one.
-- pg_cron prunes rows older than 120 days (the repo keeps full history).
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS public.daily_briefs (
  id            bigserial PRIMARY KEY,
  brief_date    date        NOT NULL,
  slot          text        NOT NULL CHECK (slot IN ('morning', 'evening')),
  title         text,
  body_md       text        NOT NULL,                 -- markdown, ≤ 20k chars (API-enforced)
  sources       jsonb       NOT NULL DEFAULT '[]'::jsonb,  -- ["calendar", "planner", …]
  generated_at  timestamptz,                          -- from the file's frontmatter
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (brief_date, slot)
);

CREATE INDEX IF NOT EXISTS daily_briefs_date_idx
  ON public.daily_briefs (brief_date DESC);

COMMENT ON TABLE public.daily_briefs IS
  'Morning/evening day briefs pulled from the daily-brief repo. Upserted on '
  '(brief_date, slot) by brief-pull; read by GET /api/today.';

CREATE OR REPLACE FUNCTION public.prune_daily_briefs(keep_days int DEFAULT 120)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE removed bigint;
BEGIN
  WITH d AS (
    DELETE FROM public.daily_briefs
    WHERE brief_date < current_date - keep_days
    RETURNING 1
  )
  SELECT count(*) INTO removed FROM d;
  RETURN removed;
END;
$$;

DO $mig$
BEGIN
  -- Dynamic SQL: cron.job does not exist where pg_cron is absent (CI, local).
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
    EXECUTE $q$
      SELECT cron.schedule('prune-daily-briefs', '50 3 * * *', 'SELECT public.prune_daily_briefs(120)')
       WHERE NOT EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'prune-daily-briefs')
    $q$;
  END IF;
END
$mig$;
