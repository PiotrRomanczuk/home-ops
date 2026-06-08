-- 007_schema_migrations.sql
-- Tracking table for the apply-migrations.sh runner. Lets us stop applying
-- migrations by hand via `docker exec psql -f`, drop the read-only mount on
-- /docker-entrypoint-initdb.d/, and make `apply migration N` idempotent.
--
-- Conventions:
--   * filename is the basename (e.g. '005_projects.sql')
--   * applied_at is when the runner ran the file
--   * checksum is sha256(content) — lets us catch "someone edited an
--     already-applied migration"
--
-- This migration is its own first row.

CREATE TABLE IF NOT EXISTS public.schema_migrations (
  filename     text PRIMARY KEY,
  applied_at   timestamptz NOT NULL DEFAULT now(),
  checksum     text
);

-- Backfill rows for prior migrations so the runner doesn't try to re-apply
-- them. Checksums are NULL for these (we don't have a record of what was
-- applied before this commit; if the live DB drifts from the file, the
-- runner will catch it on the NEXT migration).
INSERT INTO public.schema_migrations (filename) VALUES
  ('001_init.sql'),
  ('002_pg_cron.sql'),
  ('003_host_metrics.sql'),
  ('004_cancelling_status.sql'),
  ('005_projects.sql'),
  ('006_task_toggles.sql'),
  ('007_schema_migrations.sql')
ON CONFLICT (filename) DO NOTHING;
