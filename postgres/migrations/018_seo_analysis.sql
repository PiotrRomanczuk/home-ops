-- 018_seo_analysis.sql
-- Daily SEO analysis written by ops/elitedesk/seo-analyse.py (06:30, after
-- seo-collect at 06:00). One row per site × day × kind:
--   * kind 'daily'  — the morning card: deterministic metrics (7d vs previous 7d,
--                     new queries, district breakdown) + optional LLM narrative.
--   * kind 'weekly' — Monday brief fed to seo-improve.sh (the PR-proposing job).
-- metrics is the exact JSON the LLM saw, so a report is reproducible and the
-- weekly job can re-read a week of numbers without re-querying seo_gsc_daily.
-- Idempotent: safe to re-run on an existing deploy.

CREATE TABLE IF NOT EXISTS public.seo_analysis_daily (
  site        text        NOT NULL,
  day         date        NOT NULL,
  kind        text        NOT NULL DEFAULT 'daily',
  metrics     jsonb       NOT NULL DEFAULT '{}'::jsonb,
  card        text        NOT NULL,
  narrative   text,
  model       text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (site, day, kind),
  CONSTRAINT seo_analysis_kind_chk CHECK (kind IN ('daily', 'weekly'))
);

COMMENT ON TABLE public.seo_analysis_daily IS
  'Morning SEO analysis per site. card = plain-text digest card (always present); '
  'narrative = headless-Claude commentary (NULL when the CLI was unavailable); '
  'metrics = the JSON the narrative was generated from.';
