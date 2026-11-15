-- 026_activity.sql
-- Created: 2026-11-08
--
-- What the server is doing. elitedesk's activity-watcher (agents/elitedesk/
-- activity-watcher.py) turns journald's systemd --user lifecycle messages into
-- one row per unit run, adds GitHub Actions jobs that ran on the self-hosted
-- runners, and posts a "right now" snapshot (running units, next timers, CPU
-- per owning unit/container). The console's Serwer tab and the Dziś card read
-- them through /api/activity/*.
--
-- 025 is taken by the gmail branch; this file starts at 026.
-- Idempotent: safe to re-run. The cron.schedule call stays the LAST statement
-- so CI can strip it (stock postgres has no pg_cron).

CREATE TABLE IF NOT EXISTS public.unit_runs (
  id            bigserial   PRIMARY KEY,
  host          text        NOT NULL,
  kind          text        NOT NULL CHECK (kind IN ('timer', 'service', 'gha')),
  unit          text        NOT NULL,              -- systemd unit, or "<workflow> / <job>" for gha
  invocation_id text        NOT NULL,              -- systemd INVOCATION_ID, or "gha:<job id>"
  project_slug  text,
  started_at    timestamptz NOT NULL,
  finished_at   timestamptz,
  result        text        NOT NULL CHECK (result IN ('running', 'ok', 'failed')),
  exit_code     integer,
  cpu_ms        bigint,
  mem_peak_mb   integer,
  repeat_count  integer     NOT NULL DEFAULT 1,    -- >1 = a restart loop folded into one row
  url           text,
  detail        text,                              -- one-line reason/context ("exit-code", branch, …)
  log_tail      text[]      NOT NULL DEFAULT '{}',
  updated_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (host, invocation_id)
);

CREATE INDEX IF NOT EXISTS unit_runs_started_idx ON public.unit_runs (started_at DESC);
CREATE INDEX IF NOT EXISTS unit_runs_project_idx ON public.unit_runs (project_slug, started_at DESC);

COMMENT ON TABLE public.unit_runs IS
  'One row per systemd --user unit run or GitHub Actions job on a self-hosted '
  'runner. Upserted by activity-watcher via POST /api/activity/runs.';

CREATE TABLE IF NOT EXISTS public.activity_now (
  host     text        PRIMARY KEY,
  ts       timestamptz NOT NULL DEFAULT now(),
  snapshot jsonb       NOT NULL DEFAULT '{}'::jsonb  -- {running:[…], next_timers:[…], owners:[…], load_1, cpu_pct}
);

COMMENT ON TABLE public.activity_now IS
  'Latest "right now" snapshot per host (overwritten every ~30 s by activity-watcher).';

CREATE OR REPLACE FUNCTION public.prune_unit_runs(keep_days int DEFAULT 90)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE removed bigint;
BEGIN
  WITH d AS (
    DELETE FROM public.unit_runs
    WHERE started_at < now() - make_interval(days => keep_days)
    RETURNING 1
  )
  SELECT count(*) INTO removed FROM d;
  RETURN removed;
END;
$$;

-- Nightly at 03:45, away from the hourly prunes (:00/:15/:30).
SELECT cron.schedule(
  'prune-unit-runs',
  '45 3 * * *',
  $$SELECT prune_unit_runs(90)$$
);
