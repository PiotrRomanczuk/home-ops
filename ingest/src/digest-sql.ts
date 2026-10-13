// SQL behind GET /api/digest. Each query returns rows the route composes into
// the digest model; keeping them here keeps the route readable and lets the
// console reuse the same model later. All read-only.

// Hosts seen in the last 7 days by logs OR metrics. A host with logs but no
// metrics (elitedesk today) shows as "reports no metrics" instead of vanishing
// from the count — the old "2/2 up" was really 2 of 3.
export const HOSTS_SQL = `
  SELECT COALESCE(m.host, e.host) AS host,
         m.ts AS last_metric_ts, e.last_event_ts,
         round(m.cpu_pct) AS cpu_pct, round(m.mem_pct) AS mem_pct, round(m.disk_pct) AS disk_pct
    FROM (SELECT DISTINCT ON (host) host, ts, cpu_pct, mem_pct, disk_pct
            FROM public.host_metrics WHERE ts > now() - interval '7 days'
           ORDER BY host, ts DESC) m
    FULL OUTER JOIN (SELECT host, max(ts) AS last_event_ts FROM public.host_logs
                      WHERE ts > now() - interval '7 days' GROUP BY host) e ON e.host = m.host
   ORDER BY 1`;

// Errors grouped into *problems*: one row per (source, host). A multi-line
// stack trace or a message with changing numbers stays one problem; the top
// pattern supplies the sample line. 2 961 rows become 3 lines.
export const PROBLEMS_SQL = `
  WITH recent AS (
    SELECT source, host, level, message, ts,
           left(regexp_replace(message, '[0-9]+', 'N', 'g'), 120) AS pattern
      FROM public.host_logs
     WHERE level IN ('error', 'fatal') AND ts > now() - interval '24 hours'
  ), top_pattern AS (
    SELECT DISTINCT ON (source, host) source, host, pattern,
           (array_agg(message ORDER BY ts DESC))[1] AS sample
      FROM recent GROUP BY source, host, pattern
     ORDER BY source, host, count(*) DESC, length(pattern) DESC
  ), grouped AS (
    SELECT source, host,
           count(*)::int AS n_24h,
           count(DISTINCT pattern)::int AS n_patterns,
           max(level) AS level,
           max(ts) AS last_seen
      FROM recent GROUP BY source, host
  )
  SELECT g.*, t.pattern, t.sample,
         (SELECT min(ts) FROM public.host_logs h
           WHERE h.source = g.source AND h.host = g.host AND h.level IN ('error','fatal')
             AND h.ts > now() - interval '30 days') AS first_seen
    FROM grouped g JOIN top_pattern t USING (source, host)
   ORDER BY n_24h DESC
   LIMIT 6`;

// Site probes from the Pi: rpi-sentinel posts app:<slug> transition events
// (DOWN / RECOVERED) with host='rpi'. Other app:* sources are applications'
// own logs (job-search pipeline steps …), not reachability.
export const SITES_SQL = `
  SELECT source, level, message, ts
    FROM public.host_logs
   WHERE source LIKE 'app:%' AND host = 'rpi'
     AND ts > now() - interval '24 hours'
   ORDER BY ts DESC LIMIT 10`;

// Today's focus: pinned Board card, else first unchecked Next line.
export const FOCUS_SQL = `
  SELECT regexp_replace(text, '\\*\\*', '', 'g') AS text
    FROM public.board_tasks WHERE slug = $1 AND is_focus LIMIT 1`;

export const NEXT_SQL = `
  SELECT regexp_replace(regexp_replace(t.line, '^\\s*[-*]\\s+\\[ \\]\\s+', ''), '\\*\\*', '', 'g') AS text
    FROM public.projects p,
         unnest(string_to_array(p.next_md, E'\\n')) WITH ORDINALITY AS t(line, ord)
   WHERE p.slug = $1 AND t.line ~ '^\\s*[-*]\\s+\\[ \\]'
   ORDER BY t.ord LIMIT 4`;

// Latest card per routine + how many runs this week vs last (the trend line).
export const CARDS_SQL = `
  WITH latest AS (
    SELECT DISTINCT ON (routine) id, routine, slug, ran_at, status, headline, items, metric,
           (ran_at + fresh_for) > now() AS is_fresh
      FROM public.digest_cards ORDER BY routine, ran_at DESC
  ), runs AS (
    SELECT routine,
           count(*) FILTER (WHERE ran_at > now() - interval '7 days')::int AS runs_7d,
           count(*) FILTER (WHERE ran_at <= now() - interval '7 days' AND ran_at > now() - interval '14 days')::int AS runs_prev_7d
      FROM public.digest_cards GROUP BY routine
  )
  SELECT l.*, r.runs_7d, r.runs_prev_7d FROM latest l JOIN runs r USING (routine)
   ORDER BY l.ran_at DESC`;

// Acceptance per routine over 30 days: does the routine earn its keep?
export const ACCEPTANCE_SQL = `
  SELECT routine,
         count(*)::int AS answered,
         count(*) FILTER (WHERE answer IN ('yes','approve','merge','publish','ok'))::int AS accepted,
         count(*) FILTER (WHERE public.decision_state(decisions.*) = 'expired')::int AS expired
    FROM public.decisions
   WHERE created_at > now() - interval '30 days' AND (answer IS NOT NULL OR expires_at < now())
   GROUP BY routine`;

export const NARRATIVE_SQL = `
  SELECT left(result->>'summary', 6000) AS summary
    FROM public.gpu_jobs
   WHERE kind = 'summarise' AND payload->>'conversation_id' LIKE 'night-digest-%'
     AND status = 'done' AND result ? 'summary' AND (result->>'summary') <> ''
     AND created_at > now() - interval '18 hours'
   ORDER BY created_at DESC LIMIT 1`;
