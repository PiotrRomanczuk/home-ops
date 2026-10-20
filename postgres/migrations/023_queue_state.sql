-- 023_queue_state.sql
-- Created: 2026-10-20
--
-- The agent queue (vault QUEUE.md: one window, one ticket in progress, an
-- ordered queue, a local-LLM lane, items waiting for Piotr, done-in-window).
-- planner-sync parses the file every tick (agents/elitedesk/queue_md.py) and
-- upserts the single row here via POST /api/queue/sync; GET /api/today reads
-- it for the "Kolejka" card. The vault stays authoritative — this is a mirror.
-- See docs/adr/2026-10-20-queue-state.md.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS public.queue_state (
  id             smallint    PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  window_from    date,
  window_to      date,
  capacity_hours numeric(5,2),
  focus          text,
  rules          text,
  sections       jsonb       NOT NULL DEFAULT '{}'::jsonb,  -- {in_progress:[…], queue:[…], local:[…], waiting:[…], done:[…]}
  summary        jsonb       NOT NULL DEFAULT '{}'::jsonb,  -- counts per section + done_hours
  source_hash    text,                                       -- md5 of QUEUE.md; unchanged file = no write
  synced_at      timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.queue_state IS
  'Mirror of the vault QUEUE.md (agent queue). Single row, upserted by '
  'planner-sync via POST /api/queue/sync; read by GET /api/today and /api/queue.';
