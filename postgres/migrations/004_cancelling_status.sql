-- 004_cancelling_status.sql
-- Adds 'cancelling' to job_status enum (Q11 from functional decisions log).
-- A cancel request on a running job sets status='cancelling' (no finished_at —
-- the job is still actually running). The scheduler polls per handler
-- iteration; when it sees 'cancelling' it stops gracefully, then transitions
-- the row to 'cancelled' + sets finished_at. queued/paused jobs continue to
-- jump straight to 'cancelled' on cancel (no in-flight work to drain).

ALTER TYPE job_status ADD VALUE IF NOT EXISTS 'cancelling';
