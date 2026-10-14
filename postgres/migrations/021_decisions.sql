-- 021_decisions.sql
-- Created: 2026-10-13
--
-- The approval inbox. A routine that is about to do something irreversible
-- or public (publish a post, merge a PR, send something out) does not do it;
-- it files a decision and stops. The morning digest shows open decisions
-- with signed yes/no links (see ingest/src/decision-links.ts); the Decisions
-- tab in the console lists them too. On its next run the routine reads the
-- answer and acts, or sees `expired` and reports that in its card.
--
-- Trees: a decision may name a parent. Answering a parent can file children;
-- that is the whole "decision tree" model — no separate graph table.
--
-- Rejections carry a one-word reason. That is the acceptance signal the
-- digest uses to show whether a routine earns its keep.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS public.decisions (
  id            bigserial PRIMARY KEY,
  routine       text        NOT NULL,              -- who is asking
  slug          text,                              -- project it concerns
  question      text        NOT NULL,              -- one sentence, ≤ 300 chars
  detail        text,                              -- optional longer context (markdown-ish plain text)
  context_url   text,                              -- PR, draft, preview …
  options       jsonb       NOT NULL DEFAULT '["yes","no"]'::jsonb,  -- ["yes","no"] or [{key,label,consequence}]
  ref           text,                              -- routine's own handle (post id, PR number)
  parent_id     bigint      REFERENCES public.decisions(id) ON DELETE SET NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz NOT NULL DEFAULT now() + interval '3 days',
  answer        text,                              -- chosen option key
  reason        text,                              -- short free text, required on rejection by convention
  answered_at   timestamptz,
  answered_via  text        CHECK (answered_via IN ('link', 'console', 'api')),
  consumed_at   timestamptz                        -- set by the routine once it acted on the answer
);

-- The inbox query: open decisions, oldest first.
CREATE INDEX IF NOT EXISTS decisions_open_idx
  ON public.decisions (created_at) WHERE answer IS NULL;

-- A routine polls "answers I have not consumed yet".
CREATE INDEX IF NOT EXISTS decisions_routine_pending_idx
  ON public.decisions (routine) WHERE answer IS NOT NULL AND consumed_at IS NULL;

-- Derived state, kept in SQL so every reader agrees.
CREATE OR REPLACE FUNCTION public.decision_state(d public.decisions)
RETURNS text
LANGUAGE sql IMMUTABLE
AS $$
  SELECT CASE
    WHEN d.answer IS NOT NULL THEN 'answered'
    WHEN d.expires_at < now()  THEN 'expired'
    ELSE 'open'
  END
$$;

COMMENT ON TABLE public.decisions IS
  'Approval inbox for routines: question + options, answered by signed link, '
  'console or API. parent_id links follow-up questions into trees.';
