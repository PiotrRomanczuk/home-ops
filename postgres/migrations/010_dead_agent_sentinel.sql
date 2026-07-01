-- 010_dead_agent_sentinel.sql
-- Created: 2026-07-01
--
-- Every 5 minutes, flag watcher agents that stopped reporting metrics.
-- Motivating incident: rpi-watcher's log side was silent for 23 days and
-- nothing surfaced it. Metrics sample every 30s, so >5 min of silence
-- means the agent (or its host) is down.
--
-- The alert is an ordinary host_logs row (host='elitedesk',
-- source='app:home-ops-sentinel', level='error') so it shows up in the
-- Logs view, the Status tab's recent-errors list, and the 1h error count
-- that turns the mobile banner red. `data.silent_host` carries which
-- agent went quiet; the NOT EXISTS guard re-alerts at most every 30 min
-- per host while the outage lasts.
--
-- Scope: hosts seen in host_metrics within 7 days. A host silent longer
-- than that ages out of the sentinel (and out of the dashboard) instead
-- of alerting forever.

CREATE OR REPLACE FUNCTION public.alert_dead_agents() RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
  inserted integer := 0;
BEGIN
  INSERT INTO public.host_logs (host, source, level, message, data)
  SELECT
    'elitedesk',
    'app:home-ops-sentinel',
    'error',
    'agent silent: ' || h.host || ' last metric ' ||
      to_char(now() - h.latest, 'HH24:MI:SS') || ' ago',
    jsonb_build_object('silent_host', h.host, 'last_metric_ts', h.latest)
  FROM (
    SELECT host, max(ts) AS latest
    FROM public.host_metrics
    WHERE ts > now() - interval '7 days'
    GROUP BY host
  ) h
  WHERE h.latest < now() - interval '5 minutes'
    AND NOT EXISTS (
      SELECT 1 FROM public.host_logs g
      WHERE g.source = 'app:home-ops-sentinel'
        AND g.data->>'silent_host' = h.host
        AND g.ts > now() - interval '30 minutes'
    );
  GET DIAGNOSTICS inserted = ROW_COUNT;
  RETURN inserted;
END;
$$;

COMMENT ON FUNCTION public.alert_dead_agents() IS
  'Inserts an error-level host_logs row per watcher host whose last '
  'host_metrics sample is older than 5 min. Re-alerts every 30 min while '
  'silent. Scheduled */5 by pg_cron.';

-- Idempotent — cron.schedule with the same jobname updates the existing row.
SELECT cron.schedule(
  'dead-agent-sentinel',
  '*/5 * * * *',
  'SELECT public.alert_dead_agents()'
);
