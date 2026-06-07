-- pg_cron — scheduled retention prunes.
-- Created: 2026-06-07
--
-- The pg_cron extension is loaded by `shared_preload_libraries=pg_cron`
-- (set in docker-compose.yml command:). The extension itself only lives
-- in one database — here, `home_ops` (set by `cron.database_name=home_ops`).
-- Schedules survive container restarts because they live in the cron.job table.

CREATE EXTENSION IF NOT EXISTS pg_cron;

-- =====================================================================
-- gpu_jobs retention: keep failed/cancelled forever, prune done at 30d
-- (Decision Q13b → C.) The function is idempotent and safe to run.
-- =====================================================================

CREATE OR REPLACE FUNCTION prune_done_gpu_jobs(keep_days int DEFAULT 30)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
  removed bigint;
BEGIN
  WITH d AS (
    DELETE FROM public.gpu_jobs
    WHERE status = 'done'
      AND finished_at IS NOT NULL
      AND finished_at < now() - make_interval(days => keep_days)
    RETURNING 1
  )
  SELECT count(*) INTO removed FROM d;
  RETURN removed;
END;
$$;

-- =====================================================================
-- Schedule both prunes nightly. cron.schedule is idempotent on the
-- (jobname, database) pair — re-running this migration is safe.
-- =====================================================================

SELECT cron.schedule(
  'prune-host-logs',
  '0 4 * * *',
  $$SELECT prune_host_logs(30)$$
);

SELECT cron.schedule(
  'prune-done-gpu-jobs',
  '15 4 * * *',
  $$SELECT prune_done_gpu_jobs(30)$$
);
