-- 006_task_toggles.sql
-- Single-table queue for project task-checkbox writeback. The UI POSTs a
-- toggle into this table; planner-sync polls every 2s, applies the edit
-- to the markdown file, commits + pushes to the planner remote, and
-- transitions the row to applied/conflict/failed.
--
-- This keeps the worker stateless across restarts (the queue lives in
-- Postgres) and lets us surface pending/conflicted toggles in the UI by
-- reading this table.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS public.task_toggles (
  id          serial PRIMARY KEY,
  created_at  timestamptz NOT NULL DEFAULT now(),
  slug        text NOT NULL,
  section     text NOT NULL CHECK (section IN ('now', 'next', 'later')),
  idx         integer NOT NULL CHECK (idx >= 0),
  done        boolean NOT NULL,
  status      text NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'applied', 'conflict', 'failed')),
  applied_at  timestamptz,
  error       text
);

-- Worker polls queued rows oldest first. Partial index = only queued rows
-- participate, so the query is fast even with terabytes of applied history.
CREATE INDEX IF NOT EXISTS task_toggles_queued_idx
  ON public.task_toggles (created_at)
  WHERE status = 'queued';

-- Drill page queries recent conflicts per slug to render the warn chip.
CREATE INDEX IF NOT EXISTS task_toggles_slug_status_idx
  ON public.task_toggles (slug, status, created_at DESC);

COMMENT ON TABLE public.task_toggles IS
  'Queue for projects/<slug>.md task-checkbox flips. UI enqueues a row, '
  'planner-sync drains every 2s. On git push conflict, status=conflict + '
  'error explains, and a warn event lands in host_logs source=app:home-ops '
  'with data.slug for surfacing in the project drill page.';
