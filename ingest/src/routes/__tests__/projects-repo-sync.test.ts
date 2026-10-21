/* Integration test for POST /api/projects/repo-sync.
 *
 * The core contract this guards: repo-sync is UPDATE-only. It must never
 * create or delete a projects row — row existence stays owned by
 * /api/projects/sync (the vault sync path). A slug with no matching row
 * is reported back in `unknownSlugs`, not silently inserted.
 *
 * Skips if DATABASE_URL isn't set (so local dev doesn't blow up if Postgres
 * isn't running) — same pattern as jobs-state-machine.test.ts.
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
  process.env.INGEST_TOKEN = ingestToken;
  process.env.LOGS_PASSWORD = 'ci-password';

  const pgMod = await import('pg');
  pool = new pgMod.default.Pool({ connectionString: dbUrl, max: 4 });
  const r = await pool.query(`SELECT to_regclass('public.projects') AS t`);
  if (!r.rows[0].t) throw new Error('projects table missing — apply migrations');
  const r2 = await pool.query(`SELECT column_name FROM information_schema.columns
    WHERE table_schema='public' AND table_name='projects' AND column_name='repo_meta'`);
  if (r2.rowCount === 0) throw new Error('repo_meta column missing — apply migration 016');

  const honoMod = await import('hono');
  const { registerProjectsRoutes } = await import('../projects.ts');
  app = new honoMod.Hono();
  registerProjectsRoutes(app);
});

afterAll(async () => {
  if (!skip && pool) await pool.end();
});

beforeEach(async () => {
  if (!skip) await pool.query('TRUNCATE public.projects');
});

async function jsonReq(path: string, init: RequestInit = {}) {
  const headers = new Headers({ ...tokenHdr, ...(init.body ? jsonHdr : {}) });
  return app.fetch(new Request(`http://test${path}`, { ...init, headers }));
}

async function insertProject(slug: string) {
  await pool.query(`INSERT INTO public.projects (slug, title, status) VALUES ($1, $1, 'warm')`, [slug]);
}

describe.skipIf(skip)('POST /api/projects/repo-sync', () => {
  it('updates repo_meta + repo_synced_at for an existing slug', async () => {
    await insertProject('strummy');
    const res = await jsonReq('/api/projects/repo-sync', {
      method: 'POST',
      body: JSON.stringify({
        entries: [{ slug: 'strummy', repo_meta: { version: '0.158.5' }, source: 'github-api' }],
      }),
    });
    expect(res.status).toBe(200);
    const body = (await res.json()) as { updated: number; unknownSlugs: string[] };
    expect(body.updated).toBe(1);
    expect(body.unknownSlugs).toEqual([]);

    const r = await pool.query(`SELECT repo_meta, repo_synced_at FROM public.projects WHERE slug='strummy'`);
    expect(r.rows[0].repo_meta.version).toBe('0.158.5');
    expect(r.rows[0].repo_meta.source).toBe('github-api');
    expect(r.rows[0].repo_synced_at).not.toBeNull();
  });

  it('reports unknown slugs and never creates a row for them', async () => {
    const res = await jsonReq('/api/projects/repo-sync', {
      method: 'POST',
      body: JSON.stringify({ entries: [{ slug: 'ghost-project', repo_meta: { version: '1.0.0' } }] }),
    });
    expect(res.status).toBe(200);
    const body = (await res.json()) as { updated: number; unknownSlugs: string[] };
    expect(body.updated).toBe(0);
    expect(body.unknownSlugs).toEqual(['ghost-project']);

    const r = await pool.query(`SELECT count(*)::int AS n FROM public.projects WHERE slug='ghost-project'`);
    expect(r.rows[0].n).toBe(0);
  });

  it('never touches vault-owned columns (title/status/now_md)', async () => {
    await insertProject('strummy');
    await pool.query(
      `UPDATE public.projects SET title='Strummy', status='hot', now_md='- [ ] ship it' WHERE slug='strummy'`,
    );
    await jsonReq('/api/projects/repo-sync', {
      method: 'POST',
      body: JSON.stringify({ entries: [{ slug: 'strummy', repo_meta: { version: '9.9.9' } }] }),
    });
    const r = await pool.query(`SELECT title, status, now_md FROM public.projects WHERE slug='strummy'`);
    expect(r.rows[0]).toEqual({ title: 'Strummy', status: 'hot', now_md: '- [ ] ship it' });
  });

  it('requires a token', async () => {
    const res = await app.fetch(
      new Request('http://test/api/projects/repo-sync', {
        method: 'POST',
        headers: jsonHdr,
        body: JSON.stringify({ entries: [] }),
      }),
    );
    expect(res.status).toBe(401);
  });

  it('rejects a non-array entries payload', async () => {
    const res = await jsonReq('/api/projects/repo-sync', {
      method: 'POST',
      body: JSON.stringify({ entries: 'nope' }),
    });
    expect(res.status).toBe(400);
  });

  it('GET /api/projects and GET /api/projects/:slug include repo_meta + repo_synced_at', async () => {
    await insertProject('strummy');
    await jsonReq('/api/projects/repo-sync', {
      method: 'POST',
      body: JSON.stringify({ entries: [{ slug: 'strummy', repo_meta: { version: '0.158.5' } }] }),
    });

    const list = (await (await jsonReq('/api/projects')).json()) as {
      projects: Array<{ repo_meta: { version: string }; repo_synced_at: string | null }>;
    };
    expect(list.projects[0]?.repo_meta.version).toBe('0.158.5');
    expect(list.projects[0]?.repo_synced_at).not.toBeNull();

    const one = (await (await jsonReq('/api/projects/strummy')).json()) as {
      project: { repo_meta: { version: string } };
    };
    expect(one.project.repo_meta.version).toBe('0.158.5');
  });
});
