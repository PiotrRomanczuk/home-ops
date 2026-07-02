-- 011_unclaimed_job_sentinel.sql
-- Created: 2026-07-02
--
-- Every 5 minutes, flag queued gpu_jobs that no worker has claimed.
-- Motivating incident: GpuScheduler was stopped by hand for the eval week
-- (2026-07-02); with no worker running, any job submitted to the queue
-- sits in status='queued' forever with nothing surfacing it. The
-- dead-agent sentinel (010) cannot catch this — win10's watcher keeps
-- reporting metrics while the scheduler service is down.
--
-- Same alert channel as 010: an error-level host_logs row
-- (source='app:home-ops-sentinel') so it lands in the Logs view, the
-- Status tab's recent errors, and the mobile red banner. One alert per
-- sweep (oldest job named, total count in data), re-alerted at most
-- every 30 minutes while the backlog persists.
--
-- Threshold: 10 minutes. Claim latency is ~250ms when a worker is
-- polling (POLL_SECONDS=5), so 10 min of queued means no worker, a
-- paused worker, or a gaming pause long enough to be worth seeing.

CREATE OR REPLACE FUNCTION public.alert_unclaimed_jobs() RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
  inserted integer := 0;
BEGIN
  INSERT INTO public.host_logs (host, source, level, message, data)
  SELECT
    'elitedesk',
    'app:home-ops-sentinel',
    'error',
    'gpu queue stalled: ' || q.n || ' queued job(s), oldest #' || q.oldest_id ||
      ' (' || q.oldest_kind || ') waiting ' ||
      to_char(now() - q.oldest_created, 'HH24:MI:SS'),
    jsonb_build_object(
      'queued_count', q.n,
      'oldest_job_id', q.oldest_id,
      'oldest_kind', q.oldest_kind,
      'oldest_created_at', q.oldest_created
    )
  FROM (
    SELECT count(*) AS n,
           min(created_at) AS oldest_created,
           (array_agg(id ORDER BY created_at))[1] AS oldest_id,
           (array_agg(kind ORDER BY created_at))[1] AS oldest_kind
    FROM public.gpu_jobs
    WHERE status = 'queued'
  ) q
  WHERE q.n > 0
    AND q.oldest_created < now() - interval '10 minutes'
    AND NOT EXISTS (
      SELECT 1 FROM public.host_logs g
      WHERE g.source = 'app:home-ops-sentinel'
        AND g.data ? 'queued_count'
        AND g.ts > now() - interval '30 minutes'
    );
  GET DIAGNOSTICS inserted = ROW_COUNT;
  RETURN inserted;
END;
$$;

COMMENT ON FUNCTION public.alert_unclaimed_jobs() IS
  'Inserts one error-level host_logs row when queued gpu_jobs have gone '
  'unclaimed for >10 min (worker down or paused). Re-alerts every 30 min '
  'while the backlog persists. Scheduled */5 by pg_cron.';

-- Idempotent — cron.schedule with the same jobname updates the existing row.
SELECT cron.schedule(
  'unclaimed-job-sentinel',
  '*/5 * * * *',
  'SELECT public.alert_unclaimed_jobs()'
);
