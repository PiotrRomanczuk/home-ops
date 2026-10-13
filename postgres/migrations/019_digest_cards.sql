-- 019_digest_cards.sql
-- Created: 2026-10-13
--
-- The routine → digest contract. Every scheduled routine (SEO collector,
-- job radar, social publisher, backups, …) ends its run by posting ONE card:
-- what it did, in one sentence, plus at most a few items with links and one
-- number with a delta. The morning digest renders the latest card per
-- routine; a card older than `fresh_for` reads as "did not run" rather than
-- as today's news (the failure mode of the old digest.d/*.txt files).
--
-- History is kept (one row per run) so the digest can show weekly trends
-- (published this week vs last) without each routine keeping its own ledger.
-- pg_cron prunes rows older than 90 days.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS public.digest_cards (
  id          bigserial PRIMARY KEY,
  routine     text        NOT NULL,                 -- 'seo-analyse', 'job-radar', …
  slug        text,                                 -- project slug when the routine serves one
  ran_at      timestamptz NOT NULL DEFAULT now(),
  status      text        NOT NULL DEFAULT 'ok'
                CHECK (status IN ('ok', 'warn', 'fail', 'skipped')),
  headline    text        NOT NULL,                 -- one sentence, ≤ 200 chars
  items       jsonb       NOT NULL DEFAULT '[]'::jsonb,  -- [{text, url?}] ≤ 5
  metric      jsonb,                                -- {label, value, delta?, unit?}
  fresh_for   interval    NOT NULL DEFAULT interval '26 hours',
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS digest_cards_routine_ran_idx
  ON public.digest_cards (routine, ran_at DESC);

COMMENT ON TABLE public.digest_cards IS
  'One card per routine run: headline + items + metric. The digest renders '
  'the latest card per routine and treats cards older than fresh_for as '
  '"did not run".';

CREATE OR REPLACE FUNCTION public.prune_digest_cards(keep_days int DEFAULT 90)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE removed bigint;
BEGIN
  WITH d AS (
    DELETE FROM public.digest_cards
    WHERE ran_at < now() - make_interval(days => keep_days)
    RETURNING 1
  )
  SELECT count(*) INTO removed FROM d;
  RETURN removed;
END;
$$;

DO $mig$
BEGIN
  -- Dynamic SQL: cron.job does not exist where pg_cron is absent (CI, local),
  -- and a static reference would fail at plan time even inside the IF.
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
    EXECUTE $q$
      SELECT cron.schedule('prune-digest-cards', '45 3 * * *', 'SELECT public.prune_digest_cards(90)')
       WHERE NOT EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'prune-digest-cards')
    $q$;
  END IF;
END
$mig$;
