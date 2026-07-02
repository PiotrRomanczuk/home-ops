-- 012_eval_tasks.sql
-- Created: 2026-07-02
--
-- Board-managed lifecycle for LLM eval tasks (the Evals tab in the viewer).
-- One row per task card. The board is AUTHORITATIVE for what eval-tick runs:
-- only stages 'testing' and 'active' enter the 6-hourly rotation. Moving a
-- card to 'paused'/'retired' removes it from runs without touching its
-- task directory on disk.
--
-- Stages: idea → building → testing → active → paused → retired
--   idea      card only, no files yet (name + notes sketch the task)
--   building  files being written (PROMPT.md / stub / tests)
--   testing   in rotation, provisional — watching first results
--   active    steady benchmark member
--   paused    temporarily out of rotation (files kept)
--   retired   permanently out (files may be deleted)
--
-- has_files / files_seen_at are maintained by eval-tick each tick (it is
-- the only component that can see ~/llm-eval on the host filesystem; the
-- ingest container cannot). Unknown task dirs are auto-registered by
-- eval-tick as stage='testing' so they always surface on the board.
--
-- Results join: eval_scores.rationale = eval_tasks.name (task_kind='coding').

CREATE TABLE IF NOT EXISTS public.eval_tasks (
  id            serial PRIMARY KEY,
  name          text NOT NULL UNIQUE CHECK (name ~ '^[a-z0-9][a-z0-9_-]{0,63}$'),
  kind          text NOT NULL DEFAULT 'python' CHECK (kind IN ('python', 'strummy')),
  stage         text NOT NULL DEFAULT 'idea'
                  CHECK (stage IN ('idea', 'building', 'testing', 'active', 'paused', 'retired')),
  notes         text,
  timeout_s     integer CHECK (timeout_s > 0 AND timeout_s <= 3600),
  has_files     boolean NOT NULL DEFAULT false,
  files_seen_at timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- Seed the tasks that exist on elitedesk today so the board is not empty
-- on first load. The four python tasks are the running benchmark; the three
-- strummy reconstruction tasks are built + manually proven but not yet
-- wired into the tick (stage='testing' so they run as soon as the strummy
-- runner is integrated). Idempotent via ON CONFLICT.
INSERT INTO public.eval_tasks (name, kind, stage, has_files, files_seen_at) VALUES
  ('balanced-brackets', 'python',  'active',  true, now()),
  ('parse-duration',    'python',  'active',  true, now()),
  ('reverse-words',     'python',  'active',  true, now()),
  ('rle-encode',        'python',  'active',  true, now()),
  ('string-similarity', 'strummy', 'testing', true, now()),
  ('db-error-helpers',  'strummy', 'testing', true, now()),
  ('notes',             'strummy', 'testing', true, now())
ON CONFLICT (name) DO NOTHING;
