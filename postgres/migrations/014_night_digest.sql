-- 014_night_digest.sql — enqueue an overnight LLM narrative for the morning digest.
-- Date: 2026-07-14
--
-- queue_night_digest() assembles the day's cross-cutting state into summarise
-- chunks and inserts ONE high-priority gpu_jobs row (kind='summarise'). The
-- win10 GPU scheduler runs it overnight (games are done → full GPU access), and
-- the morning digest reads result->>'summary' into its "Overnight narrative" card.
--
-- Called by `ops/elitedesk/daily-digest.sh --mode evening` (21:00 local). It is
-- intentionally NOT cron-scheduled here so timing stays in the host's local TZ
-- (pg_cron runs in UTC — see the 008 weekly-review comment).
--
-- Idempotent per day: skips if a night-digest job for today already exists, so a
-- re-run of the evening timer won't double-queue.

CREATE OR REPLACE FUNCTION public.queue_night_digest() RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
  conv   text := 'night-digest-' || to_char(now(), 'YYYY-MM-DD');
  chunks text[] := '{}';
  c      text;
  new_id bigint;
BEGIN
  -- One overnight narrative per day.
  IF EXISTS (
    SELECT 1 FROM public.gpu_jobs
    WHERE kind = 'summarise' AND payload->>'conversation_id' = conv
  ) THEN
    RETURN NULL;
  END IF;

  -- chunk 1 — infra health + error counts (24h)
  SELECT 'INFRA (last 24h):' || E'\n' ||
    coalesce((
      SELECT string_agg(
        format('%s seen %s ago  cpu %s%%  mem %s%%  disk %s%%%s',
          host, to_char(now() - ts, 'HH24:MI:SS'),
          coalesce(round(cpu_pct)::text, '-'), coalesce(round(mem_pct)::text, '-'),
          coalesce(round(disk_pct)::text, '-'),
          CASE WHEN ts < now() - interval '5 minutes' THEN '  SILENT' ELSE '' END),
        E'\n' ORDER BY host)
      FROM (
        SELECT DISTINCT ON (host) host, ts, cpu_pct, mem_pct, disk_pct
        FROM public.host_metrics WHERE ts > now() - interval '2 days'
        ORDER BY host, ts DESC
      ) m), '(no metrics)')
    || E'\nlog levels: ' ||
    coalesce((
      SELECT string_agg(level || '=' || n, '  ')
      FROM (SELECT level, count(*) n FROM public.host_logs
            WHERE level IN ('warn', 'error', 'fatal') AND ts > now() - interval '1 day'
            GROUP BY level) e), 'none')
    INTO c;
  chunks := array_append(chunks, c);

  -- chunk 2 — top recurring error/fatal (24h, digits normalised)
  SELECT 'TOP ERRORS (24h):' || E'\n' ||
    coalesce((
      SELECT string_agg(format('%sx [%s] %s', n, level, msg), E'\n' ORDER BY n DESC)
      FROM (
        SELECT count(*) n, level, left(regexp_replace(message, '[0-9]+', 'N', 'g'), 100) msg
        FROM public.host_logs
        WHERE level IN ('error', 'fatal') AND ts > now() - interval '1 day'
        GROUP BY level, left(regexp_replace(message, '[0-9]+', 'N', 'g'), 100)
        ORDER BY count(*) DESC LIMIT 6
      ) t), '(none — clear)')
    INTO c;
  chunks := array_append(chunks, c);

  -- chunk 3 — recent LLM eval runs
  SELECT 'EVALS (recent runs):' || E'\n' ||
    coalesce((
      SELECT string_agg(
        format('%s  %s  %s  n=%s pass=%s score=%s tok/s=%s',
          day, model, task_kind, n, coalesce(pass_rate::text, '-'),
          coalesce(avg_score::text, '-'), coalesce(avg_tok_per_s::text, '-')),
        E'\n')
      FROM (SELECT * FROM public.eval_summary ORDER BY day DESC LIMIT 6) s), '(no eval data)')
    INTO c;
  chunks := array_append(chunks, c);

  -- chunk 4 — GPU job activity (24h) + current queue depth
  SELECT 'GPU JOBS (24h):' || E'\n' ||
    coalesce((
      SELECT string_agg(status || '=' || n, '  ' ORDER BY status)
      FROM (SELECT status::text status, count(*) n FROM public.gpu_jobs
            WHERE created_at > now() - interval '1 day' GROUP BY status) g), '(none)')
    || E'\nqueued now: ' || (SELECT count(*) FROM public.gpu_jobs WHERE status = 'queued')::text
    INTO c;
  chunks := array_append(chunks, c);

  -- chunk 5 — project focus (hot/warm Now/Next, planner-synced)
  SELECT 'PROJECTS (hot/warm):' || E'\n' ||
    coalesce((
      SELECT string_agg(
        slug || ' [' || status || ']' ||
        coalesce(E'\n  now: '  || nullif(now_md, ''), '') ||
        coalesce(E'\n  next: ' || nullif(next_md, ''), ''),
        E'\n' ORDER BY slug)
      FROM public.projects WHERE status IN ('hot', 'warm')), '(no projects)')
    INTO c;
  chunks := array_append(chunks, c);

  INSERT INTO public.gpu_jobs (kind, payload, priority)
  VALUES ('summarise',
    jsonb_build_object(
      'model', 'qwen3:8b',
      'chunks', to_jsonb(chunks),
      'title', 'Overnight narrative · ' || to_char(now(), 'YYYY-MM-DD'),
      'conversation_id', conv,
      'lang', 'en',
      'prompt',
        'You are writing the overnight briefing a home-ops operator reads with '
        'morning coffee. Summarise the day across infrastructure health, LLM '
        'evals, GPU jobs, and project progress. Lead with anything that needs '
        'attention (silent hosts, fatal errors, failed jobs); then note '
        'progress; then a one-line outlook for today. Terse, concrete, plain '
        'prose, no preamble.'),
    7)
  RETURNING id INTO new_id;

  RETURN new_id;
END;
$$;

COMMENT ON FUNCTION public.queue_night_digest() IS
  'Enqueues one summarise gpu_job (conversation night-digest-<date>) from the '
  'day''s infra/eval/gpu/project state, for the morning digest''s Overnight '
  'narrative card. Idempotent per day. Called by daily-digest.sh --mode evening.';
