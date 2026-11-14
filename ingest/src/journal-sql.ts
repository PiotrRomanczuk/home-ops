// SQL behind GET /api/journal/day — one Warsaw day of one host ($1 host,
// $2 day). Machine side from host_metrics/host_logs (mac-watcher), Claude side
// from claude_* (every host; the human's own time counts on $1 only). The
// all-host Claude queries take the day alone, as $1.
// "Active" Claude time = distinct 5-minute buckets with any event.

const TZ = `'Europe/Warsaw'`;
const IN_DAY = (col: string, day = '$2') =>
  `${col} >= (${day}::date)::timestamp AT TIME ZONE ${TZ} AND ${col} < (${day}::date + 1)::timestamp AT TIME ZONE ${TZ}`;
const INTERVAL = `coalesce((m.data->>'interval_s')::numeric, 30)`;
const BUCKET_MIN = `(count(DISTINCT floor(extract(epoch FROM e.ts) / 300)) * 5)::int`;
const list = (key: string) =>
  `jsonb_array_elements(CASE jsonb_typeof(m.data->'${key}') WHEN 'array' THEN m.data->'${key}' ELSE '[]'::jsonb END)`;

export const HOURS_SQL = `
  SELECT extract(hour FROM m.ts AT TIME ZONE ${TZ})::int AS hour,
         count(*)::int AS samples,
         sum(${INTERVAL})::float AS seconds,
         round(avg(m.cpu_pct)::numeric, 1)::float AS cpu,
         round(avg(m.gpu_pct)::numeric, 1)::float AS gpu,
         round(max(m.mem_pct)::numeric, 1)::float AS mem_max,
         round(sum(m.net_rx_kbps * ${INTERVAL} / 1024)::numeric, 1)::float AS rx_mb,
         round(sum(m.net_tx_kbps * ${INTERVAL} / 1024)::numeric, 1)::float AS tx_mb
    FROM public.host_metrics m
   WHERE m.host = $1 AND ${IN_DAY('m.ts')}
   GROUP BY 1 ORDER BY 1`;

export const APPS_SQL = `
  SELECT 'cpu' AS kind, e->>'name' AS name, round(sum((e->>'pct')::numeric / 100 * ${INTERVAL}))::float AS value
    FROM public.host_metrics m CROSS JOIN LATERAL ${list('top_cpu')} e
   WHERE m.host = $1 AND ${IN_DAY('m.ts')} GROUP BY 2
  UNION ALL
  SELECT 'net', e->>'name', round(sum(coalesce((e->>'rx')::numeric, 0) + coalesce((e->>'tx')::numeric, 0)) / 1048576, 1)::float
    FROM public.host_metrics m CROSS JOIN LATERAL ${list('top_net')} e
   WHERE m.host = $1 AND ${IN_DAY('m.ts')} GROUP BY 2
  UNION ALL
  SELECT 'mem', e->>'name', max((e->>'rss_mb')::numeric)::float
    FROM public.host_metrics m CROSS JOIN LATERAL ${list('top_mem')} e
   WHERE m.host = $1 AND ${IN_DAY('m.ts')} GROUP BY 2`;

export const PROCS_SQL = `
  SELECT l.ts, l.data FROM public.host_logs l
   WHERE l.host = $1 AND l.source = 'agent:mac-watcher' AND l.message LIKE 'proc %' AND ${IN_DAY('l.ts')}
   ORDER BY l.ts LIMIT 500`;

export const SESSIONS_SQL = `
  SELECT s.host, s.session_id, s.title, s.project_slug, s.surface, s.cwd, s.git_branch, s.cost_usd,
         s.prs, s.live_status, min(e.ts) AS first_ts, max(e.ts) AS last_ts,
         (count(*) FILTER (WHERE e.kind = 'prompt'))::int AS prompts_day,
         (count(*) FILTER (WHERE e.kind = 'error'))::int AS errors_day,
         (count(*) FILTER (WHERE e.kind IN ('bash', 'edit', 'agent', 'skill', 'mcp')))::int AS actions_day,
         ${BUCKET_MIN} AS active_min
    FROM public.claude_events e
    JOIN public.claude_sessions s ON s.host = e.host AND s.session_id = e.session_id
   WHERE ${IN_DAY('e.ts', '$1')}
   GROUP BY s.host, s.session_id ORDER BY min(e.ts)`;

export const TOTALS_SQL = `
  SELECT (count(DISTINCT e.session_id))::int AS sessions,
         (count(*) FILTER (WHERE e.kind = 'prompt'))::int AS prompts,
         (count(*) FILTER (WHERE e.kind = 'error'))::int AS errors,
         ${BUCKET_MIN} AS active_min
    FROM public.claude_events e WHERE e.host = $1 AND ${IN_DAY('e.ts')}`;

export const BY_PROJECT_SQL = `
  SELECT s.project_slug, (count(DISTINCT (e.host, e.session_id)))::int AS sessions,
         (count(*) FILTER (WHERE e.kind = 'prompt'))::int AS prompts, ${BUCKET_MIN} AS active_min
    FROM public.claude_events e
    JOIN public.claude_sessions s ON s.host = e.host AND s.session_id = e.session_id
   WHERE ${IN_DAY('e.ts', '$1')} GROUP BY 1 ORDER BY active_min DESC`;

export const PRS_SQL = `
  SELECT DISTINCT e.text AS url FROM public.claude_events e WHERE e.kind = 'pr' AND ${IN_DAY('e.ts', '$1')}`;

export const JOURNAL_SQL = `
  SELECT summary_md, model, generated_at FROM public.day_journal WHERE host = $1 AND day = $2::date`;

export const UPSERT_JOURNAL_SQL = `
  INSERT INTO public.day_journal (host, day, rollup, summary_md, model, generated_at)
  VALUES ($1, $2::date, $3::jsonb, $4, $5, now())
  ON CONFLICT (host, day) DO UPDATE SET rollup = EXCLUDED.rollup, summary_md = EXCLUDED.summary_md,
    model = EXCLUDED.model, generated_at = now()`;
