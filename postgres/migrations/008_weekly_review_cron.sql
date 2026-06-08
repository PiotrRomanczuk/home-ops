-- 008_weekly_review_cron.sql
-- Fridays at 18:00, one summarise job per hot/warm project covering the
-- past 7 days of warn+ events emitted with source='app:<slug>'.
--
-- "Use the queue daily" bridge — the first scheduled producer that turns
-- the LLM stack from on-demand into ambient. Result lands as a job that
-- the chat tab renders as a readable summary (see chat-api.js change).
--
-- Idempotent: the cron.schedule call replaces an existing schedule with
-- the same jobname.

CREATE OR REPLACE FUNCTION public.queue_weekly_reviews() RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
  proj record;
  chunk_array text[];
  inserted integer := 0;
BEGIN
  FOR proj IN
    SELECT slug FROM public.projects WHERE status IN ('hot', 'warm') ORDER BY slug
  LOOP
    -- Build chunks: one per day with warn+ events for the project. The
    -- summarise.py handler consumes chunks as a list[str].
    SELECT array_agg(chunk ORDER BY chunk_date) INTO chunk_array
    FROM (
      SELECT
        date_trunc('day', ts)::date AS chunk_date,
        date_trunc('day', ts)::date::text || E':\n' ||
        string_agg(
          to_char(ts, 'HH24:MI') || ' [' || level || '] ' || left(message, 240),
          E'\n' ORDER BY ts
        ) AS chunk
      FROM public.host_logs
      WHERE source = 'app:' || proj.slug
        AND ts >= now() - interval '7 days'
        AND level IN ('warn', 'error', 'fatal')
      GROUP BY date_trunc('day', ts)
    ) d;

    IF chunk_array IS NULL OR cardinality(chunk_array) = 0 THEN
      CONTINUE;  -- nothing to summarise this week
    END IF;

    -- conversation_id = 'weekly-<slug>-<year>-<ISO week>' so the same
    -- conversation thread carries each week's review for a project.
    INSERT INTO public.gpu_jobs (kind, payload, priority)
    VALUES (
      'summarise',
      jsonb_build_object(
        'model', 'qwen3:8b',
        'chunks', to_jsonb(chunk_array),
        'project', proj.slug,
        'title', 'Weekly review · ' || proj.slug || ' · ' || to_char(now(), 'IYYY-"W"IW'),
        'conversation_id', 'weekly-' || proj.slug || '-' || to_char(now(), 'IYYY-IW'),
        'lang', 'en',
        'prompt', 'You are summarising one week of warn/error events from a single project. Be terse. Group by recurring failure mode. Highlight anything that escalated.'
      ),
      5
    );
    inserted := inserted + 1;
  END LOOP;
  RETURN inserted;
END;
$$;

COMMENT ON FUNCTION public.queue_weekly_reviews() IS
  'Inserts one summarise gpu_jobs row per hot/warm project covering the '
  'last 7d of warn+ host_logs events. Scheduled Fridays 18:00 by pg_cron.';

-- Idempotent — cron.schedule with the same jobname updates the existing row.
SELECT cron.schedule(
  'weekly-review',
  '0 18 * * 5',   -- Friday 18:00, postgres TZ (UTC unless reconfigured)
  'SELECT public.queue_weekly_reviews()'
);
