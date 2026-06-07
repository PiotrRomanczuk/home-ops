-- home-ops initial schema
-- Created: 2026-06-07
-- Database: home_ops

-- =====================================================================
-- 1. host_logs — centralised app logs from every host
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.host_logs (
  id          bigserial PRIMARY KEY,
  ts          timestamptz NOT NULL DEFAULT now(),
  host        text NOT NULL,
  source      text NOT NULL,
  level       text NOT NULL CHECK (level IN ('debug','info','warn','error','fatal')),
  message     text NOT NULL,
  data        jsonb NOT NULL DEFAULT '{}'::jsonb,
  ingested_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_host_logs_ts          ON public.host_logs (ts DESC);
CREATE INDEX IF NOT EXISTS idx_host_logs_host_ts     ON public.host_logs (host, ts DESC);
CREATE INDEX IF NOT EXISTS idx_host_logs_source_ts   ON public.host_logs (source, ts DESC);
CREATE INDEX IF NOT EXISTS idx_host_logs_level_alarm ON public.host_logs (level) WHERE level IN ('warn','error','fatal');
CREATE INDEX IF NOT EXISTS idx_host_logs_data_gin    ON public.host_logs USING gin (data);

-- =====================================================================
-- 2. gpu_jobs — pluggable job queue for the Windows idle-GPU scheduler
-- =====================================================================

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'job_status') THEN
    CREATE TYPE job_status AS ENUM ('queued','running','paused','done','failed','cancelled');
  END IF;
END$$;

CREATE TABLE IF NOT EXISTS public.gpu_jobs (
  id           bigserial PRIMARY KEY,
  kind         text NOT NULL,
  payload      jsonb NOT NULL,
  status       job_status NOT NULL DEFAULT 'queued',
  priority     int NOT NULL DEFAULT 0,
  created_at   timestamptz NOT NULL DEFAULT now(),
  started_at   timestamptz,
  finished_at  timestamptz,
  attempts     int NOT NULL DEFAULT 0,
  last_error   text,
  result       jsonb,
  worker_host  text
);

CREATE INDEX IF NOT EXISTS idx_gpu_jobs_queued
  ON public.gpu_jobs (priority DESC, created_at ASC)
  WHERE status = 'queued';

CREATE INDEX IF NOT EXISTS idx_gpu_jobs_status_created
  ON public.gpu_jobs (status, created_at DESC);

-- =====================================================================
-- 3. Retention helper — call from cron / pg_cron to bound disk usage
-- =====================================================================

CREATE OR REPLACE FUNCTION prune_host_logs(keep_days int DEFAULT 30)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
  removed bigint;
BEGIN
  WITH d AS (
    DELETE FROM public.host_logs
    WHERE ts < now() - make_interval(days => keep_days)
    RETURNING 1
  )
  SELECT count(*) INTO removed FROM d;
  RETURN removed;
END;
$$;
