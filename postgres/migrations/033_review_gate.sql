-- 033_review_gate.sql
-- Created: 2026-11-15
--
-- "Open it before you accept it." A decision that merges code is answered
-- only from its review page (/review/:id), never from a card button or a
-- signed link in the digest email. The page shows everything the routine and
-- CI filed for the exact commit being decided on (review_sections) plus the
-- pr-review findings (028), and hands out a short-lived token bound to that
-- commit; the answer is accepted only with that token.
--
-- Routines (ingest-token callers) may still answer through the API with
-- 'later' or a refusal — that is how pr-decide retires a question about an
-- older commit — but never with an option that merges.
--
-- Questions pr-decide opened before this migration (up to 7 days old) get the
-- gate too: no card button merges them after the deploy.
--
-- Idempotent: safe to re-run.

ALTER TABLE public.decisions ADD COLUMN IF NOT EXISTS requires_review boolean NOT NULL DEFAULT false;
ALTER TABLE public.decisions ADD COLUMN IF NOT EXISTS reviewed_at timestamptz; -- review page first opened

UPDATE public.decisions SET requires_review = true
 WHERE routine = 'pr-decide' AND answer IS NULL AND NOT requires_review;

ALTER TABLE public.decisions DROP CONSTRAINT IF EXISTS decisions_answered_via_check;
ALTER TABLE public.decisions ADD CONSTRAINT decisions_answered_via_check
  CHECK (answered_via IN ('link', 'console', 'api', 'review'));

-- One row per (PR head commit, section). A new push is a new SHA, so the page
-- for a new question never shows documentation filed for older code.
CREATE TABLE IF NOT EXISTS public.review_sections (
  id         bigserial   PRIMARY KEY,
  repo       text        NOT NULL,
  number     integer     NOT NULL,
  head_sha   text        NOT NULL,
  key        text        NOT NULL CHECK (key ~ '^[a-z0-9][a-z0-9_-]{0,31}$'),
  title      text        NOT NULL,
  position   integer     NOT NULL DEFAULT 100,  -- lower first
  body_md    text,                              -- shown inline (markdown, rendered client-side)
  url        text        CHECK (url IS NULL OR url ~ '^https?://'),  -- or a link to an artefact
  source     text        NOT NULL,              -- who filed it: pr-decide, strummy-ci, ...
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (repo, number, head_sha, key),
  CHECK (body_md IS NOT NULL OR url IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS review_sections_pr_idx ON public.review_sections (repo, number, head_sha);

COMMENT ON TABLE public.review_sections IS
  'Documentation shown on the review page of a decision, per PR head commit (ingest/src/routes/review.ts).';
