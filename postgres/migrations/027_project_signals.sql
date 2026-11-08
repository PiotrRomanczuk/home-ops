-- 027_project_signals.sql
-- Created: 2026-11-08
--
-- How projects move forward, one count per project per day per signal. Many
-- writers, one table:
--   github-repo-sync (every 4 h) recomputes the last 12 weeks from GitHub —
--     commits on the default branch, PRs opened/merged, Production deploys,
--     CI runs ok/failed — and REPLACES that window for those signals;
--   planner-sync (every 60 s) ADDS vault tasks ticked [x] / newly added,
--     diffed against its previous snapshot (agents/elitedesk/task_ticks.py);
--   vault-ticks-backfill.py seeds past weeks from the vault's git history.
-- Routine runs are not stored here — GET /api/progress counts them from
-- unit_runs (026). The console's Postęp tab reads GET /api/progress.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS public.project_signals (
  project_slug text        NOT NULL,
  day          date        NOT NULL,
  signal       text        NOT NULL CHECK (signal IN (
                 'commits', 'pr_opened', 'pr_merged', 'deploys', 'ci_ok', 'ci_failed',
                 'tasks_done', 'tasks_added')),
  n            integer     NOT NULL CHECK (n >= 0),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (project_slug, day, signal)
);

CREATE INDEX IF NOT EXISTS project_signals_day_idx ON public.project_signals (day);

COMMENT ON TABLE public.project_signals IS
  'Daily progress counts per project (GitHub, vault ticks). Written via '
  'POST /api/progress/signals; read by GET /api/progress.';
