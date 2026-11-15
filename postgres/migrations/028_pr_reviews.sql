-- 028_pr_reviews.sql
-- Created: 2026-11-11
--
-- "Second pair of eyes": every open PR gets an independent review by the
-- pr-review routine (fresh `claude -p`, read-only, no access to the session
-- that wrote the code). One row per reviewed head commit — a new push is a
-- new SHA and gets its own review. pr-decide reads the row for the PR's
-- current head before offering "Scal", so nothing unreviewed reaches main.
--
-- `findings` keeps only the findings that survived the verification pass;
-- `dropped` counts the ones the verifier rejected (false-positive rate).
-- `round` = fix rounds done by pr-agent before this review (0 = first look).
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS public.pr_reviews (
  id          bigserial   PRIMARY KEY,
  repo        text        NOT NULL,                 -- repository name (owner is implied)
  number      integer     NOT NULL,                 -- PR number
  head_sha    text        NOT NULL,                 -- the commit that was reviewed
  verdict     text        NOT NULL CHECK (verdict IN ('ok', 'zmiany', 'bloker')),
  summary     text        NOT NULL,
  findings    jsonb       NOT NULL DEFAULT '[]'::jsonb,  -- [{severity, file, line, problem, evidence, suggestion}]
  dropped     integer     NOT NULL DEFAULT 0,       -- findings rejected by the verification pass
  round       integer     NOT NULL DEFAULT 0,
  model       text,
  cost_usd    numeric(8, 4),
  comment_url text,                                 -- the PR comment, NULL on a dry run
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (repo, number, head_sha)
);

CREATE INDEX IF NOT EXISTS pr_reviews_pr_idx ON public.pr_reviews (repo, number, created_at DESC);

COMMENT ON TABLE public.pr_reviews IS
  'Independent PR reviews by pr-review (ops/elitedesk/pr_review.py); read by pr-decide before merging.';
