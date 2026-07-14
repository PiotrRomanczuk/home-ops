-- 015_task_toggle_text.sql
-- Anchor task toggles to the task's text, not just its positional index.
--
-- Toggles referenced tasks by (section, idx) captured at UI render time. If
-- the vault file changed before the toggle drained (item inserted/removed
-- above), the flip landed on the wrong task. The UI now also sends the task
-- text; planner-sync flips the matching-text line first and only falls back
-- to idx when the text isn't found (e.g. concurrent rewording).
--
-- Nullable: old queued rows and token-only callers without text keep the
-- positional behavior.
--
-- Idempotent: safe to re-run.

ALTER TABLE public.task_toggles
  ADD COLUMN IF NOT EXISTS text text;
