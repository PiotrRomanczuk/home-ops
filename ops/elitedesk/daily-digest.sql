-- daily-digest.sql — the body of the morning home-ops digest.
-- Created: 2026-07-14
--
-- Piped into `psql` inside home-ops-postgres-1 by daily-digest.sh. Every
-- query emits a single pre-formatted text column so the shell can drop the
-- output straight into the email with no post-processing. Read-only: this
-- file must never mutate state.
--
-- Section markers (\echo) double as the email's section headers.

\pset border 0
\pset footer off
\t on
\a
\pset null '-'

\echo ── HOST HEALTH ──────────────────────────────────────
-- Latest sample per host; flag anything silent > 5 min (dead-agent threshold).
SELECT format('  %-10s  seen %-9s ago   cpu %4s%%  mem %4s%%  disk %4s%%   %s',
  m.host,
  to_char(now() - m.ts, 'HH24:MI:SS'),
  coalesce(round(m.cpu_pct)::text, '-'),
  coalesce(round(m.mem_pct)::text, '-'),
  coalesce(round(m.disk_pct)::text, '-'),
  CASE WHEN m.ts < now() - interval '5 minutes' THEN '⚠ SILENT' ELSE 'ok' END)
FROM (
  SELECT DISTINCT ON (host) host, ts, cpu_pct, mem_pct, disk_pct
  FROM host_metrics
  WHERE ts > now() - interval '2 days'
  ORDER BY host, ts DESC
) m
ORDER BY m.host;

\echo
\echo ── SENTINEL ALERTS (24h) ────────────────────────────
-- Dead-agent (010) + unclaimed-job (011) sentinels. Empty = quiet night.
SELECT coalesce(
  string_agg(format('  %s  %s', to_char(ts, 'MM-DD HH24:MI'), left(message, 88)),
             E'\n' ORDER BY ts DESC),
  '  (none — all clear)')
FROM (
  SELECT ts, message FROM host_logs
  WHERE source = 'app:home-ops-sentinel' AND ts > now() - interval '1 day'
  ORDER BY ts DESC LIMIT 8
) s;

\echo
\echo ── ERRORS (24h) ─────────────────────────────────────
SELECT format('  %-6s %s', level, count(*))
FROM host_logs
WHERE level IN ('warn', 'error', 'fatal') AND ts > now() - interval '1 day'
GROUP BY level
ORDER BY array_position(ARRAY['fatal', 'error', 'warn'], level);
\echo   top recurring error/fatal (digits normalised to N):
SELECT format('  %4s×  [%s] %s', c, level, msg)
FROM (
  SELECT count(*) AS c, level,
         left(regexp_replace(message, '[0-9]+', 'N', 'g'), 78) AS msg
  FROM host_logs
  WHERE level IN ('error', 'fatal') AND ts > now() - interval '1 day'
  GROUP BY level, left(regexp_replace(message, '[0-9]+', 'N', 'g'), 78)
  ORDER BY count(*) DESC
  LIMIT 5
) t;

\echo
\echo ── LLM EVAL ─────────────────────────────────────────
SELECT format('  last graded output: %s',
  coalesce(to_char(max(scored_at), 'YYYY-MM-DD HH24:MI')
           || '  (' || to_char(now() - max(scored_at), 'DD"d "HH24"h"') || ' ago)',
           'never'))
FROM eval_scores;
SELECT format('  graded in last 24h: %s', count(*))
FROM eval_scores WHERE scored_at > now() - interval '1 day';
\echo   recent runs (model × task):
SELECT format('  %s  %-12s %-10s n=%-2s pass=%-4s score=%-5s tok/s=%s',
  day, model, task_kind, n,
  coalesce(pass_rate::text, '-'),
  coalesce(avg_score::text, '-'),
  coalesce(avg_tok_per_s::text, '-'))
FROM eval_summary
ORDER BY day DESC
LIMIT 5;

\echo
\echo ── EVAL BOARD ───────────────────────────────────────
-- Only 'testing' + 'active' cards enter the 6-hourly rotation (mig. 012).
SELECT format('  %-9s %s', stage, count(*))
FROM eval_tasks
GROUP BY stage
ORDER BY array_position(
  ARRAY['idea', 'building', 'testing', 'active', 'paused', 'retired'], stage);

\echo
\echo ── GPU JOB QUEUE (24h) ──────────────────────────────
SELECT coalesce(
  string_agg(format('  %-10s %s', status, n), E'\n' ORDER BY status),
  '  (no jobs created in last 24h)')
FROM (
  SELECT status::text AS status, count(*) AS n
  FROM gpu_jobs WHERE created_at > now() - interval '1 day'
  GROUP BY status
) g;
SELECT format('  queued right now: %s', count(*))
FROM gpu_jobs WHERE status = 'queued';
