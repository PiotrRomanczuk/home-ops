-- 013_board_tasks.sql
-- Created: 2026-07-14
--
-- DB-authoritative kanban for project task management (the Board tab).
-- Columns mirror the vault's Now/Next/Later sections 1:1 so planner-sync can
-- render board_tasks back into projects/<slug>.md and keep the Obsidian vault
-- (and the morning digest) consistent. `done` maps to the markdown `[x]`;
-- there is no separate Done column, which keeps the rendered vault clean.
--
-- Source of truth for interactive edits = this table (fast, synchronous, like
-- eval_tasks). planner-sync pushes changes to the vault and imports vault-only
-- edits back when the board hasn't changed (see agents/elitedesk/planner-sync.py).
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS public.board_tasks (
  id          bigserial PRIMARY KEY,
  slug        text    NOT NULL DEFAULT 'home-ops',
  column_key  text    NOT NULL CHECK (column_key IN ('now', 'next', 'later')),
  text        text    NOT NULL,
  done        boolean NOT NULL DEFAULT false,
  is_focus    boolean NOT NULL DEFAULT false,
  position    integer NOT NULL DEFAULT 0,   -- order within (slug, column_key)
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Board reads and the DB→vault render both walk (slug, column, position).
CREATE INDEX IF NOT EXISTS board_tasks_slug_col_pos_idx
  ON public.board_tasks (slug, column_key, position);

-- At most one "Today's focus" card per project. Enforced in the DB; the API
-- also clears others transactionally when pinning a new focus.
CREATE UNIQUE INDEX IF NOT EXISTS board_tasks_one_focus
  ON public.board_tasks (slug) WHERE is_focus;

COMMENT ON TABLE public.board_tasks IS
  'DB-authoritative kanban cards (Board tab). column_key mirrors vault '
  'Now/Next/Later; done = markdown [x]; is_focus pins the digest Today''s '
  'focus. planner-sync renders this back into projects/<slug>.md.';
