import type { Hono } from 'hono';
import { hasIngestToken, hasViewerAuth } from '../auth.ts';
import { pool } from '../db.ts';

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

interface Rejected {
  index: number;
  reason: string;
}

// Returns null on success, otherwise a short reason that goes back to the
// client in the rejected[] array. Keep reasons short and stable — agents log
// them verbatim.
function validateMetric(m: unknown): string | null {
  if (!m || typeof m !== 'object') return 'not an object';
  const x = m as Partial<Metric>;
  if (typeof x.host !== 'string' || x.host.length === 0 || x.host.length >= 64) return 'invalid host';
  for (const k of METRIC_NUM_KEYS) {
    const v = x[k];
    if (v !== undefined && v !== null && typeof v !== 'number') return `${k} not a number`;
  }
  return null;
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

export function registerMetricsRoutes(app: Hono): void {
  app.use('/api/metrics', async (c, next) => {
    if (c.req.method === 'POST') {
      return hasIngestToken(c) ? next() : c.json({ error: 'unauthorized' }, 401);
    }
    return hasViewerAuth(c) || hasIngestToken(c) ? next() : c.json({ error: 'unauthorized' }, 401);
  });

  app.post('/api/metrics', async (c) => {
    let body: unknown;
    try {
      body = await c.req.json();
    } catch {
      return c.json({ error: 'invalid json' }, 400);
    }
    let metrics: unknown[];
    if (
      body &&
      typeof body === 'object' &&
      'metrics' in body &&
      Array.isArray((body as { metrics: unknown }).metrics)
    ) {
      metrics = (body as { metrics: unknown[] }).metrics;
    } else {
      metrics = [body];
    }
    if (metrics.length === 0) return c.json({ inserted: 0, rejected: [] });
    if (metrics.length > 500) return c.json({ error: 'batch too large (max 500)' }, 413);

    const good: Metric[] = [];
    const rejected: Rejected[] = [];
    metrics.forEach((m, i) => {
      const reason = validateMetric(m);
      if (reason) rejected.push({ index: i, reason });
      else good.push(m as Metric);
    });

    try {
      const inserted = await insertMetricsBatch(good);
      return c.json({ inserted, rejected });
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
}
