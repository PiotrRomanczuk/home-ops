// SQL behind /api/claude/* (migration 032). Kept apart from the route so the
// statements read as one block: upsert, project resolution, Postęp signals.

const TZ = `'Europe/Warsaw'`;

export const SESSION_COLS = `host, session_id, surface, cwd, git_remote, project_slug, git_branch, title,
  started_at, last_at, active_ms, prompts_n, tool_calls_n, tool_errors_n, compactions_n, tools, skills,
  subagents, mcp, tokens, cost_usd, lines_added, lines_removed, prs, pushes, files_edited, entrypoint,
  version, live_status, updated_at`;

export const UPSERT_SESSIONS_SQL = `
  INSERT INTO public.claude_sessions (host, session_id, surface, cwd, git_remote, git_branch, title,
    started_at, last_at, active_ms, prompts_n, tool_calls_n, tool_errors_n, compactions_n, tools, skills,
    subagents, mcp, tokens, cost_usd, lines_added, lines_removed, prs, pushes, files_edited, entrypoint, version)
  SELECT $1, r.session_id, r.surface, r.cwd, r.git_remote, r.git_branch, r.title, r.started_at, r.last_at,
    r.active_ms, r.prompts_n, r.tool_calls_n, r.tool_errors_n, r.compactions_n, r.tools, r.skills,
    r.subagents, r.mcp, r.tokens, r.cost_usd, r.lines_added, r.lines_removed, r.prs, r.pushes,
    r.files_edited, r.entrypoint, r.version
  FROM jsonb_to_recordset($2::jsonb) AS r(session_id text, surface text, cwd text, git_remote text,
    git_branch text, title text, started_at timestamptz, last_at timestamptz, active_ms bigint,
    prompts_n int, tool_calls_n int, tool_errors_n int, compactions_n int, tools jsonb, skills jsonb,
    subagents jsonb, mcp jsonb, tokens jsonb, cost_usd numeric, lines_added int, lines_removed int,
    prs jsonb, pushes jsonb, files_edited text[], entrypoint text, version text)
  ON CONFLICT (host, session_id) DO UPDATE SET
    surface = EXCLUDED.surface, cwd = COALESCE(EXCLUDED.cwd, claude_sessions.cwd),
    git_remote = COALESCE(EXCLUDED.git_remote, claude_sessions.git_remote),
    git_branch = COALESCE(EXCLUDED.git_branch, claude_sessions.git_branch),
    title = COALESCE(EXCLUDED.title, claude_sessions.title),
    started_at = LEAST(EXCLUDED.started_at, claude_sessions.started_at),
    last_at = GREATEST(EXCLUDED.last_at, claude_sessions.last_at),
    active_ms = EXCLUDED.active_ms, prompts_n = EXCLUDED.prompts_n, tool_calls_n = EXCLUDED.tool_calls_n,
    tool_errors_n = EXCLUDED.tool_errors_n, compactions_n = EXCLUDED.compactions_n, tools = EXCLUDED.tools,
    skills = EXCLUDED.skills, subagents = EXCLUDED.subagents, mcp = EXCLUDED.mcp, tokens = EXCLUDED.tokens,
    cost_usd = COALESCE(EXCLUDED.cost_usd, claude_sessions.cost_usd),
    lines_added = COALESCE(EXCLUDED.lines_added, claude_sessions.lines_added),
    lines_removed = COALESCE(EXCLUDED.lines_removed, claude_sessions.lines_removed),
    prs = EXCLUDED.prs, pushes = EXCLUDED.pushes, files_edited = EXCLUDED.files_edited,
    entrypoint = COALESCE(EXCLUDED.entrypoint, claude_sessions.entrypoint),
    version = COALESCE(EXCLUDED.version, claude_sessions.version), updated_at = now()`;

// Which vault project a session worked on, best evidence first: the cwd's git
// origin vs the note's `repo:` (bare name or a github URL with a remark), the
// cwd's folder name vs the slug, the cwd under the note's `path:`. Sessions
// started from ~ (most of them) fall back to the project whose ~/code/<group>/
// <slug>/ folder holds most of the files the session edited.
export const RESOLVE_PROJECT_SQL = `
  UPDATE public.claude_sessions s SET project_slug = COALESCE((
    SELECT p.slug FROM public.projects p
     WHERE (s.git_remote IS NOT NULL AND lower(split_part(s.git_remote, '/', 2)) =
              lower(substring(p.raw_frontmatter->>'repo' from '([^/[:space:]]+)(?:[[:space:]].*)?$')))
        OR lower(p.slug) = lower(regexp_replace(s.cwd, '^.*/', ''))
        OR (coalesce(p.path, '') LIKE '~/%' AND
            regexp_replace(s.cwd, '^/(Users|home)/[^/]+', '~') || '/' LIKE p.path || '/%')
     ORDER BY (s.git_remote IS NOT NULL AND lower(split_part(s.git_remote, '/', 2)) =
              lower(substring(p.raw_frontmatter->>'repo' from '([^/[:space:]]+)(?:[[:space:]].*)?$'))) DESC,
              (lower(p.slug) = lower(regexp_replace(s.cwd, '^.*/', ''))) DESC, length(p.path) DESC NULLS LAST
     LIMIT 1
  ), (
    SELECT p.slug
      FROM unnest(s.files_edited) AS f(path)
      CROSS JOIN LATERAL (SELECT substring(f.path from '/code/(.*)$') AS rest) r
      JOIN public.projects p ON lower(p.slug) IN (lower(split_part(r.rest, '/', 1)), lower(split_part(r.rest, '/', 2)))
     GROUP BY p.slug ORDER BY count(*) DESC, p.slug LIMIT 1
  ))
  WHERE s.host = $1 AND s.session_id = ANY($2)`;

export const LIVE_SET_SQL = `
  UPDATE public.claude_sessions s SET live_status = l.status
    FROM jsonb_to_recordset($2::jsonb) AS l(session_id text, status text)
   WHERE s.host = $1 AND s.session_id = l.session_id AND s.live_status IS DISTINCT FROM l.status`;

export const LIVE_CLEAR_SQL = `
  UPDATE public.claude_sessions SET live_status = NULL
   WHERE host = $1 AND live_status IS NOT NULL AND NOT (session_id = ANY($2))`;

export const INSERT_EVENTS_SQL = `
  INSERT INTO public.claude_events (host, session_id, uuid, ts, kind, text, detail)
  SELECT $1, e.session_id, e.uuid, e.ts, e.kind, e.text, e.detail
  FROM jsonb_to_recordset($2::jsonb) AS e(session_id text, uuid text, ts timestamptz, kind text,
    text text, detail jsonb)
  ON CONFLICT (host, session_id, uuid) DO NOTHING`;

export const SESSION_DAYS_SQL = `
  SELECT DISTINCT to_char((ts AT TIME ZONE ${TZ})::date, 'YYYY-MM-DD') AS day
    FROM public.claude_events WHERE host = $1 AND session_id = ANY($2) AND kind = 'prompt'`;

// Postęp: prompts and sessions per project per Warsaw day, recomputed (not
// added) for the touched days, so re-sent batches never double-count.
export const SIGNALS_DELETE_SQL = `
  DELETE FROM public.project_signals
   WHERE signal IN ('claude_sessions', 'claude_prompts') AND day = ANY($1::date[])`;

export const SIGNALS_INSERT_SQL = `
  INSERT INTO public.project_signals (project_slug, day, signal, n)
  SELECT s.project_slug, (e.ts AT TIME ZONE ${TZ})::date, x.signal,
         CASE x.signal WHEN 'claude_prompts' THEN count(*) ELSE count(DISTINCT (e.host, e.session_id)) END
    FROM public.claude_events e
    JOIN public.claude_sessions s USING (host, session_id)
   CROSS JOIN (VALUES ('claude_prompts'), ('claude_sessions')) AS x(signal)
   WHERE e.kind = 'prompt' AND s.project_slug IS NOT NULL
     AND (e.ts AT TIME ZONE ${TZ})::date = ANY($1::date[])
   GROUP BY 1, 2, 3`;
