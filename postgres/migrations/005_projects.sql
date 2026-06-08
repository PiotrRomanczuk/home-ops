-- 005_projects.sql
-- Vault-derived project state. A sync worker on elitedesk pulls the planner repo
-- (~/Obsidian/MainCV-Planner) every 60s, parses projects/*.md frontmatter +
-- body sections, and upserts into this table. The UI reads it via
-- GET /api/projects and joins to host_logs via source='app:<slug>' and to
-- gpu_jobs via payload.project='<slug>'.
--
-- Idempotent: safe to re-run on an existing deploy.

CREATE TABLE IF NOT EXISTS public.projects (
  slug             text PRIMARY KEY,
  title            text,
  status           text NOT NULL DEFAULT 'dormant'
                     CHECK (status IN ('hot', 'warm', 'dormant', 'stalled')),
  path             text,
  last_commit      date,
  commits_30d      integer NOT NULL DEFAULT 0,
  updated_at       timestamptz NOT NULL DEFAULT now(),
  synced_at        timestamptz NOT NULL DEFAULT now(),
  now_md           text,
  next_md          text,
  later_md         text,
  pain_md          text,
  notes_md         text,
  raw_frontmatter  jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- Common query patterns:
--   "all hot projects"           — status filter
--   "what's been updated lately" — updated_at sort
CREATE INDEX IF NOT EXISTS projects_status_idx ON public.projects (status);
CREATE INDEX IF NOT EXISTS projects_updated_at_idx ON public.projects (updated_at DESC);

COMMENT ON TABLE public.projects IS
  'Vault-derived project snapshot. Source of truth = ~/Obsidian/MainCV-Planner. '
  'Sync worker upserts every 60s. Join key = slug (also used as app:<slug> source '
  'in host_logs and payload.project in gpu_jobs).';
