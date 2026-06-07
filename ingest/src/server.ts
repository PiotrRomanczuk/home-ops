import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { serve } from '@hono/node-server';
import { Hono } from 'hono';
import { deleteCookie, getCookie, setCookie } from 'hono/cookie';
import { logger } from 'hono/logger';
import pg from 'pg';

const DATABASE_URL = process.env.DATABASE_URL;
const INGEST_TOKEN = process.env.INGEST_TOKEN;
const LOGS_PASSWORD = process.env.LOGS_PASSWORD;
const PORT = Number(process.env.PORT ?? 8080);
const PUBLIC_DIR = process.env.PUBLIC_DIR ?? path.resolve(process.cwd(), 'public');

if (!DATABASE_URL) throw new Error('DATABASE_URL required');
if (!INGEST_TOKEN) throw new Error('INGEST_TOKEN required');
if (!LOGS_PASSWORD) throw new Error('LOGS_PASSWORD required');

const pool = new pg.Pool({ connectionString: DATABASE_URL, max: 8 });

const COOKIE_NAME = 'logs_auth';
const COOKIE_VALUE = createHash('sha256').update(LOGS_PASSWORD).digest('hex');

type Level = 'debug' | 'info' | 'warn' | 'error' | 'fatal';
const LEVELS: Level[] = ['debug', 'info', 'warn', 'error', 'fatal'];
const LEVEL_RANK: Record<Level, number> = { debug: 0, info: 1, warn: 2, error: 3, fatal: 4 };

interface Event {
  host: string;
  source: string;
  level: Level;
  message: string;
  data?: Record<string, unknown>;
  ts?: string;
}

function validate(e: unknown): e is Event {
  if (!e || typeof e !== 'object') return false;
  const x = e as Partial<Event>;
  return (
    typeof x.host === 'string' &&
    x.host.length > 0 &&
    x.host.length < 64 &&
    typeof x.source === 'string' &&
    x.source.length > 0 &&
    x.source.length < 128 &&
    typeof x.level === 'string' &&
    (LEVELS as string[]).includes(x.level) &&
    typeof x.message === 'string' &&
    x.message.length > 0
  );
}

async function insertBatch(events: Event[]): Promise<number> {
  if (events.length === 0) return 0;
  const cols: unknown[] = [];
  const placeholders: string[] = [];
  events.forEach((e, i) => {
    const base = i * 6;
    placeholders.push(
      `(COALESCE($${base + 1}::timestamptz, now()), $${base + 2}, $${base + 3}, $${base + 4}, $${base + 5}, $${base + 6}::jsonb)`,
    );
    cols.push(e.ts ?? null, e.host, e.source, e.level, e.message, JSON.stringify(e.data ?? {}));
  });
  const sql = `INSERT INTO public.host_logs (ts, host, source, level, message, data) VALUES ${placeholders.join(', ')}`;
  await pool.query(sql, cols);
  return events.length;
}

// ── host_metrics ──────────────────────────────────────────────────────

interface Metric {
  host: string;
  ts?: string;
  cpu_pct?: number;
  cpu_load_1?: number;
  mem_pct?: number;
  mem_used_mb?: number;
  mem_total_mb?: number;
  swap_pct?: number;
  disk_pct?: number;
  net_rx_kbps?: number;
  net_tx_kbps?: number;
  gpu_pct?: number;
  gpu_mem_pct?: number;
  gpu_temp_c?: number;
  data?: Record<string, unknown>;
}

const METRIC_NUM_KEYS: readonly (keyof Metric)[] = [
  'cpu_pct',
  'cpu_load_1',
  'mem_pct',
  'mem_used_mb',
  'mem_total_mb',
  'swap_pct',
  'disk_pct',
  'net_rx_kbps',
  'net_tx_kbps',
  'gpu_pct',
  'gpu_mem_pct',
  'gpu_temp_c',
] as const;

function validateMetric(m: unknown): m is Metric {
  if (!m || typeof m !== 'object') return false;
  const x = m as Partial<Metric>;
  if (typeof x.host !== 'string' || x.host.length === 0 || x.host.length >= 64) return false;
  for (const k of METRIC_NUM_KEYS) {
    const v = x[k];
    if (v !== undefined && v !== null && typeof v !== 'number') return false;
  }
  return true;
}

async function insertMetricsBatch(metrics: Metric[]): Promise<number> {
  if (metrics.length === 0) return 0;
  const cols: unknown[] = [];
  const placeholders: string[] = [];
  // Field order: ts, host, then 12 numeric fields (matches METRIC_NUM_KEYS),
  // then data jsonb. 15 placeholders per row.
  const fieldsPerRow = 15;
  metrics.forEach((m, i) => {
    const base = i * fieldsPerRow;
    const ph = Array.from({ length: fieldsPerRow }, (_, j) => `$${base + j + 1}`);
    placeholders.push(
      `(COALESCE(${ph[0]}::timestamptz, now()), ${ph[1]}, ${ph[2]}, ${ph[3]}, ${ph[4]}, ${ph[5]}, ${ph[6]}, ${ph[7]}, ${ph[8]}, ${ph[9]}, ${ph[10]}, ${ph[11]}, ${ph[12]}, ${ph[13]}, ${ph[14]}::jsonb)`,
    );
    cols.push(
      m.ts ?? null,
      m.host,
      m.cpu_pct ?? null,
      m.cpu_load_1 ?? null,
      m.mem_pct ?? null,
      m.mem_used_mb ?? null,
      m.mem_total_mb ?? null,
      m.swap_pct ?? null,
      m.disk_pct ?? null,
      m.net_rx_kbps ?? null,
      m.net_tx_kbps ?? null,
      m.gpu_pct ?? null,
      m.gpu_mem_pct ?? null,
      m.gpu_temp_c ?? null,
      JSON.stringify(m.data ?? {}),
    );
  });
  const sql = `INSERT INTO public.host_metrics
    (ts, host, cpu_pct, cpu_load_1, mem_pct, mem_used_mb, mem_total_mb,
     swap_pct, disk_pct, net_rx_kbps, net_tx_kbps, gpu_pct, gpu_mem_pct, gpu_temp_c, data)
    VALUES ${placeholders.join(', ')}`;
  await pool.query(sql, cols);
  return metrics.length;
}

const MIME: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
};

async function serveStatic(name: string): Promise<Response> {
  const safe = name.replace(/[^\w.-]/g, '');
  const ext = path.extname(safe).toLowerCase();
  const mime = MIME[ext] ?? 'application/octet-stream';
  try {
    const body = await readFile(path.join(PUBLIC_DIR, safe));
    return new Response(body, { headers: { 'content-type': mime, 'cache-control': 'no-cache' } });
  } catch {
    return new Response('not found', { status: 404 });
  }
}

const app = new Hono();
app.use('*', logger());

// ── auth helpers ──────────────────────────────────────────────────────

function hasViewerAuth(c: { req: { header: (k: string) => string | undefined; raw: { headers: Headers } } }): boolean {
  const cookie = getCookie(c as never, COOKIE_NAME);
  return cookie === COOKIE_VALUE;
}

function hasIngestToken(c: { req: { header: (k: string) => string | undefined } }): boolean {
  return c.req.header('X-Ingest-Token') === INGEST_TOKEN;
}

// Token-only routes (machine ingestion). MUST come before /api/* viewer routes.
app.use('/api/ingest', async (c, next) => (hasIngestToken(c) ? next() : c.json({ error: 'unauthorized' }, 401)));
app.use('/api/ingest/*', async (c, next) => (hasIngestToken(c) ? next() : c.json({ error: 'unauthorized' }, 401)));

// /api/metrics: POST = token only (machine), GET = viewer cookie OR token.
app.use('/api/metrics', async (c, next) => {
  if (c.req.method === 'POST') {
    return hasIngestToken(c) ? next() : c.json({ error: 'unauthorized' }, 401);
  }
  return hasViewerAuth(c) || hasIngestToken(c) ? next() : c.json({ error: 'unauthorized' }, 401);
});

// Viewer-accessible API: cookie OR token. Public read endpoints used by the browser viewer.
app.use('/api/logs', async (c, next) =>
  hasViewerAuth(c) || hasIngestToken(c) ? next() : c.json({ error: 'unauthorized' }, 401),
);
app.use('/api/jobs', async (c, next) =>
  hasViewerAuth(c) || hasIngestToken(c) ? next() : c.json({ error: 'unauthorized' }, 401),
);
app.use('/api/jobs/*', async (c, next) =>
  hasViewerAuth(c) || hasIngestToken(c) ? next() : c.json({ error: 'unauthorized' }, 401),
);
app.use('/api/sources', async (c, next) =>
  hasViewerAuth(c) || hasIngestToken(c) ? next() : c.json({ error: 'unauthorized' }, 401),
);

// ── login + viewer pages ──────────────────────────────────────────────

app.post('/api/auth/login', async (c) => {
  const body = (await c.req.json().catch(() => ({}))) as { password?: string };
  if (body.password !== LOGS_PASSWORD) return c.json({ error: 'invalid password' }, 401);
  setCookie(c, COOKIE_NAME, COOKIE_VALUE, {
    httpOnly: true,
    sameSite: 'Lax',
    path: '/',
    maxAge: 60 * 60 * 24 * 30,
  });
  return c.json({ ok: true });
});

app.post('/api/auth/logout', async (c) => {
  deleteCookie(c, COOKIE_NAME);
  return c.json({ ok: true });
});

app.get('/login', () => serveStatic('login.html'));
app.get('/static/:name', async (c) => serveStatic(c.req.param('name')));

app.get('/', (c) => {
  if (!hasViewerAuth(c)) return c.redirect('/login');
  return serveStatic('index.html');
});

// ── ingest API ────────────────────────────────────────────────────────

app.get('/api/health', async (c) => {
  try {
    await pool.query('SELECT 1');
    return c.json({ ok: true });
  } catch (err) {
    return c.json({ ok: false, error: (err as Error).message }, 503);
  }
});

app.post('/api/ingest', async (c) => {
  let body: unknown;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: 'invalid json' }, 400);
  }
  let events: Event[];
  if (body && typeof body === 'object' && 'events' in body && Array.isArray((body as { events: unknown }).events)) {
    events = (body as { events: unknown[] }).events as Event[];
  } else {
    events = [body as Event];
  }
  if (events.length === 0) return c.json({ inserted: 0 });
  if (events.length > 500) return c.json({ error: 'batch too large (max 500)' }, 413);
  const bad = events.findIndex((e) => !validate(e));
  if (bad >= 0) return c.json({ error: 'invalid event', index: bad }, 400);
  try {
    const inserted = await insertBatch(events);
    return c.json({ inserted });
  } catch (err) {
    console.error('insert failed:', err);
    return c.json({ error: 'db write failed' }, 503);
  }
});

// ── viewer queries ────────────────────────────────────────────────────

app.get('/api/logs', async (c) => {
  const hosts = c.req.queries('host') ?? [];
  const sources = c.req.queries('source') ?? [];
  const levelMin = (c.req.query('level_min') ?? 'debug') as Level;
  const sinceMin = Number(c.req.query('since_min') ?? '60');
  const grep = c.req.query('grep') ?? '';
  const after = Number(c.req.query('after') ?? '0');
  const limit = Math.min(Math.max(Number(c.req.query('limit') ?? '200'), 1), 1000);

  const params: unknown[] = [];
  const where: string[] = [];
  if (after > 0) {
    params.push(after);
    where.push(`id > $${params.length}`);
  }
  if (hosts.length) {
    params.push(hosts);
    where.push(`host = ANY($${params.length}::text[])`);
  }
  if (sources.length) {
    params.push(sources);
    where.push(`source = ANY($${params.length}::text[])`);
  }
  if (LEVEL_RANK[levelMin] > 0) {
    const allowed = LEVELS.filter((l) => LEVEL_RANK[l] >= LEVEL_RANK[levelMin]);
    params.push(allowed);
    where.push(`level = ANY($${params.length}::text[])`);
  }
  if (sinceMin > 0 && after === 0) {
    params.push(`${sinceMin} minutes`);
    where.push(`ts >= now() - $${params.length}::interval`);
  }
  if (grep) {
    params.push(`%${grep}%`);
    where.push(`(message ILIKE $${params.length} OR data::text ILIKE $${params.length})`);
  }

  const sql = `
    SELECT id, ts, host, source, level, message, data
    FROM public.host_logs
    ${where.length ? `WHERE ${where.join(' AND ')}` : ''}
    ORDER BY ${after > 0 ? 'id ASC' : 'id DESC'}
    LIMIT ${limit}
  `;
  const r = await pool.query(sql, params);
  return c.json({ rows: r.rows, latest_id: r.rows.length ? Number(r.rows.at(0)?.id ?? r.rows.at(-1)?.id ?? 0) : 0 });
});

// ── host_metrics API ──────────────────────────────────────────────────

app.post('/api/metrics', async (c) => {
  let body: unknown;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: 'invalid json' }, 400);
  }
  let metrics: Metric[];
  if (body && typeof body === 'object' && 'metrics' in body && Array.isArray((body as { metrics: unknown }).metrics)) {
    metrics = (body as { metrics: unknown[] }).metrics as Metric[];
  } else {
    metrics = [body as Metric];
  }
  if (metrics.length === 0) return c.json({ inserted: 0 });
  if (metrics.length > 500) return c.json({ error: 'batch too large (max 500)' }, 413);
  const bad = metrics.findIndex((m) => !validateMetric(m));
  if (bad >= 0) return c.json({ error: 'invalid metric', index: bad }, 400);
  try {
    const inserted = await insertMetricsBatch(metrics);
    return c.json({ inserted });
  } catch (err) {
    console.error('metrics insert failed:', err);
    return c.json({ error: 'db write failed' }, 503);
  }
});

app.get('/api/metrics', async (c) => {
  const hosts = c.req.queries('host') ?? [];
  const sinceMin = Number(c.req.query('since_min') ?? '60');
  const limit = Math.min(Math.max(Number(c.req.query('limit') ?? '200'), 1), 5000);
  const latestOnly = c.req.query('latest') === '1';

  const params: unknown[] = [];
  const where: string[] = [];
  if (hosts.length) {
    params.push(hosts);
    where.push(`host = ANY($${params.length}::text[])`);
  }
  if (sinceMin > 0 && !latestOnly) {
    params.push(`${sinceMin} minutes`);
    where.push(`ts >= now() - $${params.length}::interval`);
  }

  let sql: string;
  if (latestOnly) {
    // One row per host: the most recent sample. Useful for the status footer.
    sql = `
      SELECT DISTINCT ON (host) *
      FROM public.host_metrics
      ${where.length ? `WHERE ${where.join(' AND ')}` : ''}
      ORDER BY host, ts DESC
    `;
  } else {
    sql = `
      SELECT * FROM public.host_metrics
      ${where.length ? `WHERE ${where.join(' AND ')}` : ''}
      ORDER BY ts DESC
      LIMIT ${limit}
    `;
  }
  const r = await pool.query(sql, params);
  return c.json({ rows: r.rows });
});

app.get('/api/sources', async () => {
  const r = await pool.query(`
    SELECT host, ARRAY_AGG(DISTINCT source ORDER BY source) AS sources
    FROM public.host_logs
    WHERE ts > now() - INTERVAL '30 days'
    GROUP BY host
    ORDER BY host
  `);
  return Response.json({ hosts: r.rows });
});

// ── jobs API (for the GPU scheduler / viewer /jobs tab) ──────────────

app.get('/api/jobs', async (c) => {
  const status = c.req.query('status');
  const limit = Math.min(Number(c.req.query('limit') ?? 100), 1000);
  const params: unknown[] = [];
  let where = '';
  if (status) {
    params.push(status);
    where = 'WHERE status = $1';
  }
  const sql = `SELECT * FROM public.gpu_jobs ${where} ORDER BY id DESC LIMIT ${limit}`;
  const r = await pool.query(sql, params);
  return c.json({ jobs: r.rows });
});

app.post('/api/jobs', async (c) => {
  const body = (await c.req.json()) as { kind?: string; payload?: unknown; priority?: number };
  if (!body.kind || typeof body.kind !== 'string') return c.json({ error: 'kind required' }, 400);
  if (body.payload == null) return c.json({ error: 'payload required' }, 400);
  const r = await pool.query(
    `INSERT INTO public.gpu_jobs (kind, payload, priority) VALUES ($1, $2::jsonb, $3) RETURNING *`,
    [body.kind, JSON.stringify(body.payload), body.priority ?? 0],
  );
  return c.json({ job: r.rows[0] });
});

app.post('/api/jobs/:id/cancel', async (c) => {
  // queued/paused → 'cancelled' immediately (no work to drain).
  // running     → 'cancelling' (no finished_at; scheduler polls per
  //               iteration, drains, then transitions to 'cancelled').
  // Anything else (done/failed/cancelled/cancelling) → 409.
  const id = Number(c.req.param('id'));
  const r = await pool.query(
    `UPDATE public.gpu_jobs
        SET status = CASE WHEN status IN ('queued','paused') THEN 'cancelled'::job_status
                          WHEN status = 'running' THEN 'cancelling'::job_status
                          ELSE status END,
            finished_at = CASE WHEN status IN ('queued','paused') THEN now()
                               ELSE finished_at END
      WHERE id=$1 AND status IN ('queued','paused','running')
      RETURNING *`,
    [id],
  );
  if (r.rowCount === 0) return c.json({ error: 'not cancellable' }, 409);
  return c.json({ job: r.rows[0] });
});

// Worker endpoints — atomic claim + lifecycle. Token auth (machine consumer).
app.use('/api/jobs/claim', async (c, next) => (hasIngestToken(c) ? next() : c.json({ error: 'unauthorized' }, 401)));
app.use('/api/jobs/:id/complete', async (c, next) =>
  hasIngestToken(c) ? next() : c.json({ error: 'unauthorized' }, 401),
);
app.use('/api/jobs/:id/fail', async (c, next) => (hasIngestToken(c) ? next() : c.json({ error: 'unauthorized' }, 401)));
app.use('/api/jobs/:id/pause', async (c, next) =>
  hasIngestToken(c) ? next() : c.json({ error: 'unauthorized' }, 401),
);

app.post('/api/jobs/claim', async (c) => {
  const body = (await c.req.json().catch(() => ({}))) as { worker_host?: string; kinds?: string[] };
  const params: unknown[] = [body.worker_host ?? null];
  const kindFilter = body.kinds?.length ? `AND kind = ANY($2::text[])` : '';
  if (body.kinds?.length) params.push(body.kinds);
  const sql = `
    WITH claimed AS (
      SELECT id FROM public.gpu_jobs
      WHERE status = 'queued' ${kindFilter}
      ORDER BY priority DESC, created_at ASC
      FOR UPDATE SKIP LOCKED
      LIMIT 1
    )
    UPDATE public.gpu_jobs j SET
      status = 'running',
      started_at = now(),
      attempts = attempts + 1,
      worker_host = $1
    FROM claimed
    WHERE j.id = claimed.id
    RETURNING j.*`;
  const r = await pool.query(sql, params);
  if (r.rowCount === 0) return c.body(null, 204);
  return c.json({ job: r.rows[0] });
});

app.post('/api/jobs/:id/complete', async (c) => {
  const id = Number(c.req.param('id'));
  const body = (await c.req.json().catch(() => ({}))) as { result?: unknown };
  const r = await pool.query(
    `UPDATE public.gpu_jobs SET status='done', finished_at=now(), result=$2::jsonb WHERE id=$1 AND status='running' RETURNING *`,
    [id, JSON.stringify(body.result ?? null)],
  );
  if (r.rowCount === 0) return c.json({ error: 'not running' }, 409);
  return c.json({ job: r.rows[0] });
});

app.post('/api/jobs/:id/fail', async (c) => {
  const id = Number(c.req.param('id'));
  const body = (await c.req.json().catch(() => ({}))) as { error?: string };
  const r = await pool.query(
    `UPDATE public.gpu_jobs SET status='failed', finished_at=now(), last_error=$2 WHERE id=$1 AND status='running' RETURNING *`,
    [id, (body.error ?? '').slice(0, 4000)],
  );
  if (r.rowCount === 0) return c.json({ error: 'not running' }, 409);
  return c.json({ job: r.rows[0] });
});

app.post('/api/jobs/:id/pause', async (c) => {
  const id = Number(c.req.param('id'));
  // Pause = put back on the queue so any worker can pick it up when GPU frees.
  const r = await pool.query(
    `UPDATE public.gpu_jobs SET status='queued', started_at=NULL, worker_host=NULL WHERE id=$1 AND status='running' RETURNING *`,
    [id],
  );
  if (r.rowCount === 0) return c.json({ error: 'not running' }, 409);
  return c.json({ job: r.rows[0] });
});

serve({ fetch: app.fetch, port: PORT }, (info) => {
  console.log(`home-ops listening on :${info.port}`);
});
