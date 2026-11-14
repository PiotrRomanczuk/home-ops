-- 032_mac_journal.sql
-- Created: 2026-11-14
--
-- The Mac's day in one place: what was done with Claude Code and what ran on
-- the machine. Writers:
--   agents/claude-collector.py (Mac launchd every 5 min, elitedesk timer every
--     5 min) → POST /api/claude/{sessions,events}: one row per Claude Code
--     session + its prompts/commands/edits/PRs, secrets masked by redact.py;
--   agents/mac/mac-watcher.py → host_metrics / host_logs / activity_now as
--     host 'mac' (existing tables);
--   agents/mac/day-summary.py (21:30) → POST /api/journal: the day's rollup
--     and a local-LLM "what next" note.
-- Readers: GET /api/claude/*, GET /api/journal/day, Postęp (claude_* signals),
-- the Dziś card "mac-dziennik".
--
-- host_profiles marks hosts that sleep (the Mac): the dead-agent sentinel
-- skips them and Dziś shows them as asleep instead of silent.
--
-- 029–031 are taken on open branches; this file starts at 032.
-- Idempotent: safe to re-run. No pg_cron — nothing here is pruned.

CREATE TABLE IF NOT EXISTS public.claude_sessions (
  host          text        NOT NULL,
  session_id    text        NOT NULL,
  surface       text        NOT NULL DEFAULT 'unknown'
                CHECK (surface IN ('cli', 'desktop', 'remote', 'phone', 'headless', 'unknown')),
  cwd           text,
  git_remote    text,                                   -- owner/repo of the cwd's origin
  project_slug  text,                                   -- resolved server-side from git_remote / cwd
  git_branch    text,
  title         text,
  started_at    timestamptz NOT NULL,
  last_at       timestamptz NOT NULL,
  active_ms     bigint      NOT NULL DEFAULT 0,         -- sum of turn durations
  prompts_n     integer     NOT NULL DEFAULT 0,
  tool_calls_n  integer     NOT NULL DEFAULT 0,
  tool_errors_n integer     NOT NULL DEFAULT 0,
  compactions_n integer     NOT NULL DEFAULT 0,
  tools         jsonb       NOT NULL DEFAULT '{}'::jsonb,  -- {tool: n}
  skills        jsonb       NOT NULL DEFAULT '{}'::jsonb,  -- {skill: n}
  subagents     jsonb       NOT NULL DEFAULT '{}'::jsonb,  -- {subagent_type: n}
  mcp           jsonb       NOT NULL DEFAULT '{}'::jsonb,  -- {server: n}
  tokens        jsonb       NOT NULL DEFAULT '{}'::jsonb,  -- {model: {in, out, cache_read, cache_write}}
  cost_usd      numeric(10, 4),
  lines_added   integer,
  lines_removed integer,
  prs           jsonb       NOT NULL DEFAULT '[]'::jsonb,  -- [{number, url, repo}]
  pushes        jsonb       NOT NULL DEFAULT '[]'::jsonb,  -- [branch]
  files_edited  text[]      NOT NULL DEFAULT '{}',
  entrypoint    text,
  version       text,
  live_status   text,                                   -- busy/idle/waiting while the process runs, else NULL
  updated_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (host, session_id)
);

CREATE INDEX IF NOT EXISTS claude_sessions_last_idx ON public.claude_sessions (last_at DESC);
CREATE INDEX IF NOT EXISTS claude_sessions_project_idx ON public.claude_sessions (project_slug, last_at DESC);

COMMENT ON TABLE public.claude_sessions IS
  'One row per Claude Code session (main transcript + its subagents), upserted '
  'by claude-collector via POST /api/claude/sessions. Raw transcripts stay on the host.';

CREATE TABLE IF NOT EXISTS public.claude_events (
  id         bigserial   PRIMARY KEY,
  host       text        NOT NULL,
  session_id text        NOT NULL,
  uuid       text        NOT NULL,                      -- transcript entry uuid or tool_use id
  ts         timestamptz NOT NULL,
  kind       text        NOT NULL CHECK (kind IN (
               'prompt', 'bash', 'edit', 'agent', 'skill', 'mcp', 'git', 'pr', 'compact', 'summary', 'error')),
  text       text        NOT NULL DEFAULT '',           -- secrets masked by the collector
  detail     jsonb       NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (host, session_id, uuid)
);

CREATE INDEX IF NOT EXISTS claude_events_session_idx ON public.claude_events (host, session_id, ts);
CREATE INDEX IF NOT EXISTS claude_events_ts_idx ON public.claude_events (ts DESC);

COMMENT ON TABLE public.claude_events IS
  'What happened inside a Claude session: prompts, Bash commands, edits, subagents, '
  'skills, MCP calls, git pushes/PRs, compactions, away summaries, tool errors.';

CREATE TABLE IF NOT EXISTS public.day_journal (
  host         text        NOT NULL,
  day          date        NOT NULL,
  rollup       jsonb       NOT NULL DEFAULT '{}'::jsonb,
  summary_md   text,
  model        text,
  generated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (host, day)
);

COMMENT ON TABLE public.day_journal IS
  'One row per host per day: the rollup from GET /api/journal/day (outlives the '
  '30-day host_metrics window) plus the local-LLM summary. Written by day-summary.';

CREATE TABLE IF NOT EXISTS public.host_profiles (
  host   text    PRIMARY KEY,
  sleeps boolean NOT NULL DEFAULT false
);

INSERT INTO public.host_profiles (host, sleeps) VALUES ('mac', true) ON CONFLICT (host) DO NOTHING;

COMMENT ON TABLE public.host_profiles IS
  'Per-host traits. sleeps = silence is normal (laptop lid closed): no sentinel '
  'alert, Dziś shows the host as asleep.';

-- Claude activity counts on the Postęp tab.
ALTER TABLE public.project_signals DROP CONSTRAINT IF EXISTS project_signals_signal_check;
ALTER TABLE public.project_signals ADD CONSTRAINT project_signals_signal_check CHECK (signal IN (
  'commits', 'pr_opened', 'pr_merged', 'deploys', 'ci_ok', 'ci_failed',
  'tasks_done', 'tasks_added', 'claude_sessions', 'claude_prompts'));

-- 010's sentinel, minus hosts that are allowed to sleep. Guarded: host_metrics
-- (003) and host_logs (001) exist on every real install, not always in CI.
DO $mig$
BEGIN
  IF to_regclass('public.host_metrics') IS NULL THEN RETURN; END IF;
  EXECUTE $fn$
    CREATE OR REPLACE FUNCTION public.alert_dead_agents() RETURNS integer
    LANGUAGE plpgsql AS $body$
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
        AND NOT EXISTS (SELECT 1 FROM public.host_profiles p WHERE p.host = h.host AND p.sleeps)
        AND NOT EXISTS (
          SELECT 1 FROM public.host_logs g
          WHERE g.source = 'app:home-ops-sentinel'
            AND g.data->>'silent_host' = h.host
            AND g.ts > now() - interval '30 minutes'
        );
      GET DIAGNOSTICS inserted = ROW_COUNT;
      RETURN inserted;
    END;
    $body$
  $fn$;
END
$mig$;
