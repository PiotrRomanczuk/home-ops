-- 009_eval.sql — local-LLM evaluation harness tables.
-- Created: 2026-07-01
--
-- A recurring Claude Code agent (Max subscription) on elitedesk submits
-- tagged generate/summarise/embed jobs to gpu_jobs and, on the next tick,
-- grades the previous batch's outputs 0..1 into eval_scores. No pg_cron
-- here — the agent drives cadence via a systemd --user timer. gpu_jobs.result
-- is frozen once a job is 'done', so scores live in their own table.
--
-- Eval jobs are ordinary gpu_jobs rows tagged in payload with:
--   eval_run_id (int), task_kind (text), intent (text). Handlers ignore
--   unknown payload keys, so no scheduler change is needed.

CREATE TABLE IF NOT EXISTS public.eval_runs (
  id          bigserial PRIMARY KEY,
  started_at  timestamptz NOT NULL DEFAULT now(),
  model_focus text,                 -- model rotated into focus this run (nullable)
  note        text
);

CREATE TABLE IF NOT EXISTS public.eval_scores (
  id          bigserial PRIMARY KEY,
  run_id      bigint REFERENCES public.eval_runs(id) ON DELETE CASCADE,
  gpu_job_id  bigint,               -- soft ref; gpu_jobs are pruned after 30d
  task_kind   text NOT NULL CHECK (task_kind IN ('coding','summarise','reasoning','embed')),
  model       text NOT NULL,
  passed      boolean,              -- agentic coding: did the test end green?
  iterations  integer,              -- agentic coding: test runs / edit rounds
  score       numeric(3,2) CHECK (score >= 0 AND score <= 1),
  verdict     text CHECK (verdict IN ('usable','marginal','unusable')),
  tok_per_s   numeric,
  latency_ms  integer,
  rationale   text,
  scored_at   timestamptz NOT NULL DEFAULT now()
);

-- One score per job — makes the judge step idempotent (re-running a tick
-- can't double-count a job it already graded).
CREATE UNIQUE INDEX IF NOT EXISTS uq_eval_scores_job
  ON public.eval_scores (gpu_job_id) WHERE gpu_job_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_eval_scores_run        ON public.eval_scores (run_id);
CREATE INDEX IF NOT EXISTS idx_eval_scores_model_kind ON public.eval_scores (model, task_kind);

-- Weekly rollup: avg quality + speed + volume by model × task_kind × day.
CREATE OR REPLACE VIEW public.eval_summary AS
SELECT
  date_trunc('day', scored_at)::date              AS day,
  model,
  task_kind,
  count(*)                                         AS n,
  round(avg(passed::int)::numeric, 2)              AS pass_rate,     -- coding
  round(avg(iterations), 1)                        AS avg_iterations,-- coding
  round(avg(score), 3)                             AS avg_score,     -- judged
  round(avg(tok_per_s), 1)                         AS avg_tok_per_s,
  count(*) FILTER (WHERE verdict = 'usable')       AS n_usable,
  count(*) FILTER (WHERE verdict = 'unusable')     AS n_unusable
FROM public.eval_scores
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 2, 3;

COMMENT ON TABLE public.eval_scores IS
  'One graded local-LLM output per row. Written by the llm-eval-tick Claude '
  'agent; gpu_job_id soft-references gpu_jobs (which prune after 30d).';
