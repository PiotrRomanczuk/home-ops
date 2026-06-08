import type { Hono } from 'hono';
import { tokenOnly, viewerOrToken } from '../auth.ts';
import { pool } from '../db.ts';

export function registerJobsRoutes(app: Hono): void {
  // Viewer-or-token middlewares come first (broader paths).
  // Worker-only middlewares come second (narrower paths). Order matters: both
  // middlewares run on /api/jobs/claim etc, so the narrow token check enforces
  // that workers must present the token, not just a viewer cookie.
  app.use('/api/jobs', viewerOrToken);
  app.use('/api/jobs/*', viewerOrToken);

  app.use('/api/jobs/claim', tokenOnly);
  app.use('/api/jobs/:id/complete', tokenOnly);
  app.use('/api/jobs/:id/fail', tokenOnly);
  app.use('/api/jobs/:id/pause', tokenOnly);
  app.use('/api/jobs/:id/result', tokenOnly);

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
    // From 'running' → 'done' (normal completion).
    // From 'cancelling' → 'cancelled' (user cancelled mid-flight; the handler
    // finished its current iteration, returned a result, we honour the cancel).
    const id = Number(c.req.param('id'));
    const body = (await c.req.json().catch(() => ({}))) as { result?: unknown };
    const r = await pool.query(
      `UPDATE public.gpu_jobs
          SET status = CASE WHEN status='cancelling' THEN 'cancelled'::job_status
                            ELSE 'done'::job_status END,
              finished_at = now(),
              result = $2::jsonb
        WHERE id=$1 AND status IN ('running','cancelling')
        RETURNING *`,
      [id, JSON.stringify(body.result ?? null)],
    );
    if (r.rowCount === 0) return c.json({ error: 'not running' }, 409);
    return c.json({ job: r.rows[0] });
  });

  app.post('/api/jobs/:id/fail', async (c) => {
    // From 'cancelling' → 'cancelled' too — if cancellation arrived while the
    // handler was failing anyway, the user-intent is cancel, not failure.
    const id = Number(c.req.param('id'));
    const body = (await c.req.json().catch(() => ({}))) as { error?: string };
    const r = await pool.query(
      `UPDATE public.gpu_jobs
          SET status = CASE WHEN status='cancelling' THEN 'cancelled'::job_status
                            ELSE 'failed'::job_status END,
              finished_at = now(),
              last_error = $2
        WHERE id=$1 AND status IN ('running','cancelling')
        RETURNING *`,
      [id, (body.error ?? '').slice(0, 4000)],
    );
    if (r.rowCount === 0) return c.json({ error: 'not running' }, 409);
    return c.json({ job: r.rows[0] });
  });

  app.get('/api/jobs/:id', async (c) => {
    const id = Number(c.req.param('id'));
    const r = await pool.query(`SELECT * FROM public.gpu_jobs WHERE id=$1`, [id]);
    if (r.rowCount === 0) return c.json({ error: 'not found' }, 404);
    return c.json({ job: r.rows[0] });
  });

  app.post('/api/jobs/:id/pause', async (c) => {
    const id = Number(c.req.param('id'));
    // From 'running' → 'queued' (requeue; e.g. gaming preempted us).
    // From 'cancelling' → 'cancelled' (don't requeue; user wanted it gone).
    const r = await pool.query(
      `UPDATE public.gpu_jobs
          SET status = CASE WHEN status='cancelling' THEN 'cancelled'::job_status
                            ELSE 'queued'::job_status END,
              started_at = CASE WHEN status='cancelling' THEN started_at ELSE NULL END,
              worker_host = CASE WHEN status='cancelling' THEN worker_host ELSE NULL END,
              finished_at = CASE WHEN status='cancelling' THEN now() ELSE finished_at END
        WHERE id=$1 AND status IN ('running','cancelling') RETURNING *`,
      [id],
    );
    if (r.rowCount === 0) return c.json({ error: 'not running' }, 409);
    return c.json({ job: r.rows[0] });
  });

  // Mid-flight streaming: worker overwrites the result jsonb without changing
  // status or finished_at. Scoped to 'running'/'cancelling' so a terminal
  // result can never be clobbered by a late partial. /complete is still what
  // flips status to done/cancelled — this endpoint is the firehose, /complete
  // is the seal.
  app.post('/api/jobs/:id/result', async (c) => {
    const id = Number(c.req.param('id'));
    const body = (await c.req.json().catch(() => ({}))) as { result?: unknown };
    const r = await pool.query(
      `UPDATE public.gpu_jobs
          SET result = $2::jsonb
        WHERE id=$1 AND status IN ('running','cancelling')
        RETURNING *`,
      [id, JSON.stringify(body.result ?? null)],
    );
    if (r.rowCount === 0) return c.json({ error: 'not running' }, 409);
    return c.json({ job: r.rows[0] });
  });
}
