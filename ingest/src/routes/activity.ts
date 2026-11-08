import type { Hono } from 'hono';
import { dedupeRuns, parseRunsBatch, parseSnapshot, RUN_RESULTS } from '../activity-model.ts';
import { tokenOnly, viewerOrToken } from '../auth.ts';
import { pool } from '../db.ts';

// What the server is doing (migration 026). activity-watcher posts unit runs
// and a "right now" snapshot; the Serwer tab and the Dziś card read them.
// A run is upserted on (host, invocation_id): the watcher re-sends a run when
// it finishes, and a later post never erases what an earlier one knew.

const RUN_COLS = `id, host, kind, unit, invocation_id, project_slug, started_at, finished_at,
  result, exit_code, cpu_ms, mem_peak_mb, repeat_count, url, detail`;

const UPSERT_SQL = `
  INSERT INTO public.unit_runs (host, kind, unit, invocation_id, project_slug, started_at, finished_at,
    result, exit_code, cpu_ms, mem_peak_mb, repeat_count, url, detail, log_tail)
  SELECT $1, r.kind, r.unit, r.invocation_id, r.project_slug, r.started_at, r.finished_at,
    r.result, r.exit_code, r.cpu_ms, r.mem_peak_mb, r.repeat_count, r.url, r.detail, r.log_tail
  FROM jsonb_to_recordset($2::jsonb) AS r(kind text, unit text, invocation_id text, project_slug text,
    started_at timestamptz, finished_at timestamptz, result text, exit_code int, cpu_ms bigint,
    mem_peak_mb int, repeat_count int, url text, detail text, log_tail text[])
  ON CONFLICT (host, invocation_id) DO UPDATE SET
    project_slug = COALESCE(EXCLUDED.project_slug, unit_runs.project_slug),
    finished_at  = COALESCE(EXCLUDED.finished_at, unit_runs.finished_at),
    result       = EXCLUDED.result,
    exit_code    = COALESCE(EXCLUDED.exit_code, unit_runs.exit_code),
    cpu_ms       = COALESCE(EXCLUDED.cpu_ms, unit_runs.cpu_ms),
    mem_peak_mb  = COALESCE(EXCLUDED.mem_peak_mb, unit_runs.mem_peak_mb),
    repeat_count = GREATEST(EXCLUDED.repeat_count, unit_runs.repeat_count),
    url          = COALESCE(EXCLUDED.url, unit_runs.url),
    detail       = COALESCE(EXCLUDED.detail, unit_runs.detail),
    log_tail     = CASE WHEN cardinality(EXCLUDED.log_tail) > 0 THEN EXCLUDED.log_tail ELSE unit_runs.log_tail END,
    updated_at   = now()`;

function clampInt(raw: string | undefined, def: number, min: number, max: number): number {
  const n = Number.parseInt(raw ?? '', 10);
  return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : def;
}

async function readJson(c: { req: { json: () => Promise<unknown> } }): Promise<unknown> {
  try {
    return await c.req.json();
  } catch {
    return undefined;
  }
}

export function registerActivityRoutes(app: Hono): void {
  app.use('/api/activity/*', viewerOrToken);
  app.post('/api/activity/*', tokenOnly);

  app.post('/api/activity/runs', async (c) => {
    const batch = parseRunsBatch(await readJson(c));
    if (typeof batch === 'string') return c.json({ error: batch }, 400);
    const runs = dedupeRuns(batch.runs);
    if (runs.length) await pool.query(UPSERT_SQL, [batch.host, JSON.stringify(runs)]);
    return c.json({ upserted: runs.length, rejected: batch.rejected });
  });

  app.post('/api/activity/now', async (c) => {
    const snap = parseSnapshot(await readJson(c));
    if (typeof snap === 'string') return c.json({ error: snap }, 400);
    await pool.query(
      `INSERT INTO public.activity_now (host, ts, snapshot) VALUES ($1, now(), $2::jsonb)
       ON CONFLICT (host) DO UPDATE SET ts = now(), snapshot = EXCLUDED.snapshot`,
      [snap.host, JSON.stringify(snap.snapshot)],
    );
    return c.json({ status: 'ok' });
  });

  app.get('/api/activity/now', async (c) => {
    const [now, sum] = await Promise.all([
      pool.query(`SELECT host, ts, snapshot FROM public.activity_now ORDER BY host`),
      pool.query(`SELECT count(*)::int AS runs, coalesce(sum(repeat_count) FILTER (WHERE result = 'failed'), 0)::int AS failed,
          coalesce(array_agg(DISTINCT unit) FILTER (WHERE result = 'failed'), '{}') AS failing_units
        FROM public.unit_runs WHERE started_at > now() - interval '24 hours'`),
    ]);
    return c.json({ hosts: now.rows, summary_24h: sum.rows[0] });
  });

  app.get('/api/activity/runs', async (c) => {
    const q = c.req.query();
    const where = ['started_at > now() - make_interval(hours => $1)'];
    const args: unknown[] = [clampInt(q.since_h, 24, 1, 24 * 90)];
    const add = (sql: string, v: unknown) => {
      args.push(v);
      where.push(sql.replace('?', `$${args.length}`));
    };
    if (q.project) add('project_slug = ?', q.project);
    if (q.unit) add('unit = ?', q.unit);
    if (q.result && (RUN_RESULTS as readonly string[]).includes(q.result)) add('result = ?', q.result);
    if (q.kind) add('kind = ?', q.kind);
    args.push(clampInt(q.limit, 500, 1, 5000));
    const r = await pool.query(
      `SELECT ${RUN_COLS} FROM public.unit_runs WHERE ${where.join(' AND ')}
       ORDER BY started_at DESC LIMIT $${args.length}`,
      args,
    );
    return c.json({ runs: r.rows });
  });

  app.get('/api/activity/runs/:id', async (c) => {
    const id = Number.parseInt(c.req.param('id'), 10);
    if (!Number.isFinite(id)) return c.json({ error: 'invalid id' }, 400);
    const r = await pool.query(`SELECT ${RUN_COLS}, log_tail FROM public.unit_runs WHERE id = $1`, [id]);
    if (!r.rowCount) return c.json({ error: 'not found' }, 404);
    return c.json({ run: r.rows[0] });
  });
}
