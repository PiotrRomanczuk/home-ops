-- 016_project_repo_meta.sql
-- Computed repo/stack/deploy metadata, independent of the vault-owned columns
-- from 005_projects.sql (title, status, path, last_commit, commits_30d,
-- now_md/next_md/later_md/pain_md/notes_md, raw_frontmatter). Written by
-- ops/elitedesk/github-repo-sync.py via POST /api/projects/repo-sync, which
-- is UPDATE-only — it never inserts or deletes a projects row, so row
-- existence stays owned by the vault sync path (POST /api/projects/sync).
--
-- Deliberately a separate column pair rather than folding into
-- raw_frontmatter or the top-level last_commit/commits_30d: those stay
-- whatever the vault hand-types, while repo_meta is a second, independently
-- refreshed layer the UI can prefer when present.
--
-- Idempotent: safe to re-run on an existing deploy.

ALTER TABLE public.projects
  ADD COLUMN IF NOT EXISTS repo_meta jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS repo_synced_at timestamptz;

CREATE INDEX IF NOT EXISTS projects_repo_synced_at_idx ON public.projects (repo_synced_at);

COMMENT ON COLUMN public.projects.repo_meta IS
  'Computed stack/version/deploy/git metadata. Shape: '
  '{ source, stack: {runtime, framework, key_deps}, version, '
  '  deploy: {url, reachable, checked_at}, git: {last_commit, commits_30d, dirty} }. '
  'Written by github-repo-sync.py (source="github-api") via /api/projects/repo-sync.';

COMMENT ON COLUMN public.projects.repo_synced_at IS
  'When repo_meta was last refreshed. Surfaced in the UI as a freshness label, '
  'same treatment as the vault-sync "synced_at" indicator — staleness is '
  'expected (e.g. between 4h sync-timer ticks), not alerted on.';
