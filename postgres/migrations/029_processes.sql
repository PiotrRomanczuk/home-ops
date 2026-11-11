-- 029_processes.sql
-- Created: 2026-11-11
--
-- Project map ("Mapa" tab): BPMN process notes from the planner vault.
-- A process is a note with `type: process` plus a BPMN 2.0 file next to it
-- (2-Obszary/mapy/procesy/<slug>.md + .bpmn). planner-sync POSTs the full set
-- every tick to /api/processes/sync; rows missing from the payload are
-- deleted, like projects. The vault stays the source of truth — this table is
-- a mirror for the UI.
--
-- `lanes` = lane names read from the diagram (project slugs or external
-- nodes such as ollama); `warnings` = lane/projects mismatches, missing or
-- invalid diagram — shown as a badge, never a sync failure.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS public.processes (
  slug       text        PRIMARY KEY,
  title      text        NOT NULL,
  trigger    text,                                 -- cron | event | manual
  schedule   text,
  summary    text,
  projects   text[]      NOT NULL DEFAULT '{}',    -- frontmatter `projects:` (link targets)
  lanes      text[]      NOT NULL DEFAULT '{}',    -- lane names in the diagram
  bpmn_xml   text,                                 -- NULL when the diagram is missing / too big
  bpmn_hash  text,                                 -- sha256 of the file, for write-back conflicts
  path       text,                                 -- note path relative to the vault root
  warnings   jsonb       NOT NULL DEFAULT '[]'::jsonb,
  synced_at  timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.processes IS
  'BPMN process notes mirrored from the planner vault by planner-sync; read by the Mapa tab.';
