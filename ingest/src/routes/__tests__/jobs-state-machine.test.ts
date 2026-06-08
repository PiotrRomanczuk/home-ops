/* Integration test for the gpu_jobs cancellation state machine.
 *
 * Hits the real route handlers via Hono's `app.fetch`, with a real Postgres
 * underneath (the workflow's `services: postgres` block). Tests the full
 * state machine that was historically subtle to get right:
 *
 *   queued     --claim-->   running
 *   running    --complete-> done
 *   running    --fail-->    failed
 *   running    --pause-->   queued
 *   running    --cancel-->  cancelling (no finished_at yet)
 *   cancelling --complete-> cancelled  (worker honoured the cancel)
 *   cancelling --fail-->    cancelled  (worker died mid-cancel)
 *   cancelling --pause-->   cancelled  (worker handed back to scheduler)
 *   queued     --cancel-->  cancelled  (immediate)
 *   paused     --cancel-->  cancelled  (immediate)
 *   done/failed/cancelled --cancel--> 409
 *
 * Plus the partial-result endpoint (no status change, scoped to
 * running|cancelling) introduced for mid-flight streaming.
 *
 * Skips if DATABASE_URL isn't set (so local dev doesn't blow up if Postgres
 * isn't running).
 */
import type { Hono } from 'hono';
import type pg from 'pg';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';

const dbUrl = process.env.DATABASE_URL;
const ingestToken = process.env.INGEST_TOKEN || 'ci-token';
const skip = !dbUrl;

const tokenHdr = { 'X-Ingest-Token': ingestToken };
const jsonHdr = { 'Content-Type': 'application/json' };

let pool: pg.Pool;
let app: Hono;

beforeAll(async () => {
  if (skip) return;
  // Force env BEFORE we dynamically import the routes — env.ts throws at
  // module-load if DATABASE_URL/INGEST_TOKEN/LOGS_PASSWORD aren't set, so
  // we couldn't even import the test file from a dev machine without pg.
  process.env.INGEST_TOKEN = ingestToken;
  process.env.LOGS_PASSWORD = 'ci-password';

  const pgMod = await import('pg');
  pool = new pgMod.default.Pool({ connectionString: dbUrl, max: 4 });
  const r = await pool.query(`SELECT to_regclass('public.gpu_jobs') AS t`);
  if (!r.rows[0].t) throw new Error('gpu_jobs table missing — apply migrations');

  const honoMod = await import('hono');
  const { registerJobsRoutes } = await import('../jobs.ts');
  app = new honoMod.Hono();
  registerJobsRoutes(app);
});

afterAll(async () => {
  if (!skip && pool) await pool.end();
});

beforeEach(async () => {
  if (!skip) await pool.query('TRUNCATE public.gpu_jobs RESTART IDENTITY');
});

async function jsonReq(path: string, init: RequestInit = {}) {
  const headers = new Headers({ ...tokenHdr, ...(init.body ? jsonHdr : {}) });
  return app.fetch(new Request(`http://test${path}`, { ...init, headers }));
}

async function insertQueued(payload: Record<string, unknown> = {}, kind = 'generate') {
  const r = await pool.query(
    `INSERT INTO public.gpu_jobs (kind, payload, priority) VALUES ($1, $2::jsonb, 0) RETURNING id`,
    [kind, JSON.stringify(payload)],
  );
  return r.rows[0].id as number;
}

async function getStatus(id: number) {
  const r = await pool.query(`SELECT status, finished_at, result FROM public.gpu_jobs WHERE id=$1`, [id]);
  return r.rows[0];
}

describe.skipIf(skip)('cancellation state machine', () => {
  it('queued → cancel → cancelled immediately', async () => {
    const id = await insertQueued({ model: 'qwen3:8b' });
    const res = await jsonReq(`/api/jobs/${id}/cancel`, { method: 'POST' });
    expect(res.status).toBe(200);
    const row = await getStatus(id);
    expect(row.status).toBe('cancelled');
    expect(row.finished_at).not.toBeNull();
  });

  it('claim → cancel → cancelling (not yet cancelled)', async () => {
    const id = await insertQueued();
    await jsonReq('/api/jobs/claim', { method: 'POST', body: JSON.stringify({ worker_host: 'win10' }) });
    const res = await jsonReq(`/api/jobs/${id}/cancel`, { method: 'POST' });
    expect(res.status).toBe(200);
    const row = await getStatus(id);
    expect(row.status).toBe('cancelling');
    // CRITICAL: finished_at must stay null — the worker is still draining.
    expect(row.finished_at).toBeNull();
  });

  it('cancelling → complete → cancelled (worker honoured cancel)', async () => {
    const id = await insertQueued();
    await jsonReq('/api/jobs/claim', { method: 'POST', body: JSON.stringify({ worker_host: 'win10' }) });
    await jsonReq(`/api/jobs/${id}/cancel`, { method: 'POST' });
    const res = await jsonReq(`/api/jobs/${id}/complete`, {
      method: 'POST',
      body: JSON.stringify({ result: { response: 'partial' } }),
    });
    expect(res.status).toBe(200);
    const row = await getStatus(id);
    expect(row.status).toBe('cancelled');
    // Result preserved — the user can see how far it got.
    expect(row.result).toEqual({ response: 'partial' });
  });

  it('cancelling → fail → cancelled (worker died mid-cancel)', async () => {
    const id = await insertQueued();
    await jsonReq('/api/jobs/claim', { method: 'POST', body: JSON.stringify({ worker_host: 'win10' }) });
    await jsonReq(`/api/jobs/${id}/cancel`, { method: 'POST' });
    await jsonReq(`/api/jobs/${id}/fail`, { method: 'POST', body: JSON.stringify({ error: 'segfault' }) });
    const row = await getStatus(id);
    expect(row.status).toBe('cancelled');
  });

  it('cancelling → pause → cancelled (worker handed back)', async () => {
    const id = await insertQueued();
    await jsonReq('/api/jobs/claim', { method: 'POST', body: JSON.stringify({ worker_host: 'win10' }) });
    await jsonReq(`/api/jobs/${id}/cancel`, { method: 'POST' });
    await jsonReq(`/api/jobs/${id}/pause`, { method: 'POST' });
    const row = await getStatus(id);
    expect(row.status).toBe('cancelled');
  });

  it('done → cancel → 409 (cannot cancel terminal)', async () => {
    const id = await insertQueued();
    await jsonReq('/api/jobs/claim', { method: 'POST', body: JSON.stringify({ worker_host: 'win10' }) });
    await jsonReq(`/api/jobs/${id}/complete`, { method: 'POST', body: JSON.stringify({ result: {} }) });
    const res = await jsonReq(`/api/jobs/${id}/cancel`, { method: 'POST' });
    expect(res.status).toBe(409);
  });

  it('failed → cancel → 409', async () => {
    const id = await insertQueued();
    await jsonReq('/api/jobs/claim', { method: 'POST', body: JSON.stringify({ worker_host: 'win10' }) });
    await jsonReq(`/api/jobs/${id}/fail`, { method: 'POST', body: JSON.stringify({ error: 'oom' }) });
    const res = await jsonReq(`/api/jobs/${id}/cancel`, { method: 'POST' });
    expect(res.status).toBe(409);
  });

  it('cancelled → cancel → 409 (already cancelled)', async () => {
    const id = await insertQueued();
    await jsonReq(`/api/jobs/${id}/cancel`, { method: 'POST' });
    const res = await jsonReq(`/api/jobs/${id}/cancel`, { method: 'POST' });
    expect(res.status).toBe(409);
  });
});

describe.skipIf(skip)('normal lifecycle', () => {
  it('claim → complete → done with result', async () => {
    const id = await insertQueued({ model: 'qwen3:8b', prompt: 'hi' });
    const claim = await jsonReq('/api/jobs/claim', {
      method: 'POST',
      body: JSON.stringify({ worker_host: 'win10' }),
    });
    const claimed = (await claim.json()) as { job: { id: number } };
    expect(claimed.job.id).toBe(id);

    await jsonReq(`/api/jobs/${id}/complete`, {
      method: 'POST',
      body: JSON.stringify({ result: { response: 'hello back', eval_count: 42 } }),
    });
    const row = await getStatus(id);
    expect(row.status).toBe('done');
    expect(row.result).toEqual({ response: 'hello back', eval_count: 42 });
  });

  it('claim with kind filter only picks matching kinds', async () => {
    await insertQueued({}, 'generate');
    const embedId = await insertQueued({}, 'embed');
    const r = await jsonReq('/api/jobs/claim', {
      method: 'POST',
      body: JSON.stringify({ worker_host: 'win10', kinds: ['embed'] }),
    });
    const { job } = (await r.json()) as { job: { id: number; kind: string } };
    expect(job.id).toBe(embedId);
    expect(job.kind).toBe('embed');
  });

  it('claim returns 204 when queue is empty', async () => {
    const r = await jsonReq('/api/jobs/claim', {
      method: 'POST',
      body: JSON.stringify({ worker_host: 'win10' }),
    });
    expect(r.status).toBe(204);
  });
});

describe.skipIf(skip)('partial result endpoint (mid-flight streaming)', () => {
  it('updates result without changing status', async () => {
    const id = await insertQueued();
    await jsonReq('/api/jobs/claim', { method: 'POST', body: JSON.stringify({ worker_host: 'win10' }) });
    const res = await jsonReq(`/api/jobs/${id}/result`, {
      method: 'POST',
      body: JSON.stringify({ result: { response: 'streaming…', partial: true } }),
    });
    expect(res.status).toBe(200);
    const row = await getStatus(id);
    expect(row.status).toBe('running');
    expect(row.result).toEqual({ response: 'streaming…', partial: true });
  });

  it('refuses partial on queued jobs (only running/cancelling allowed)', async () => {
    const id = await insertQueued();
    const res = await jsonReq(`/api/jobs/${id}/result`, {
      method: 'POST',
      body: JSON.stringify({ result: { response: 'nope' } }),
    });
    expect(res.status).toBe(409);
  });

  it('allows partial during cancelling (caps the firehose mid-drain)', async () => {
    const id = await insertQueued();
    await jsonReq('/api/jobs/claim', { method: 'POST', body: JSON.stringify({ worker_host: 'win10' }) });
    await jsonReq(`/api/jobs/${id}/cancel`, { method: 'POST' });
    const res = await jsonReq(`/api/jobs/${id}/result`, {
      method: 'POST',
      body: JSON.stringify({ result: { response: 'last gasp' } }),
    });
    expect(res.status).toBe(200);
    const row = await getStatus(id);
    expect(row.status).toBe('cancelling'); // still cancelling, /complete will seal
    expect(row.result).toEqual({ response: 'last gasp' });
  });
});
