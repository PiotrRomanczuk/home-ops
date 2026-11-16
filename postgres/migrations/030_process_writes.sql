-- 030_process_writes.sql
-- Created: 2026-11-11
--
-- BPMN edits from the Mapa tab, queued for planner-sync to write back into
-- the planner vault (same pattern as task_toggles, 006/015). The browser never
-- touches git: it posts the new diagram with the hash it was opened at;
-- planner-sync writes the file, commits and pushes, or marks `conflict` when
-- the vault copy changed in the meantime (someone edited it in Obsidian or
-- another tab saved first). The vault stays the source of truth.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS public.process_writes (
  id          bigserial   PRIMARY KEY,
  slug        text        NOT NULL,                  -- processes.slug
  base_hash   text        NOT NULL,                  -- processes.bpmn_hash the editor started from
  bpmn_xml    text        NOT NULL,
  status      text        NOT NULL DEFAULT 'queued'
                          CHECK (status IN ('queued', 'applied', 'conflict', 'failed')),
  error       text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  applied_at  timestamptz
);

CREATE INDEX IF NOT EXISTS process_writes_queued_idx ON public.process_writes (created_at) WHERE status = 'queued';

COMMENT ON TABLE public.process_writes IS
  'BPMN saves from the Mapa tab, drained by planner-sync into the vault (processes.bpmn_hash = optimistic lock).';
