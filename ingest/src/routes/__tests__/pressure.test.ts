/* Integration test for the runtime signals behind GET /api/pressure, against a
 * real Postgres. Skips when DATABASE_URL is unset. Needs migration 001.
 */
import type pg from 'pg';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { type PressureInput, projectPressure, WEIGHTS } from '../../pressure-model.ts';

const dbUrl = process.env.DATABASE_URL;
const skip = !dbUrl;
const DOWN = 'deploy unreachable from rpi (HTTP 502)';
const UP = 'deploy reachable again from rpi';

let pool: pg.Pool;
let loadRuntime: typeof import('../pressure.ts').loadRuntime;

beforeAll(async () => {
  if (skip) return;
  process.env.INGEST_TOKEN = process.env.INGEST_TOKEN || 'ci-token';
  process.env.LOGS_PASSWORD = 'ci-password';
  const pgMod = await import('pg');
  pool = new pgMod.default.Pool({ connectionString: dbUrl, max: 2 });
  loadRuntime = (await import('../pressure.ts')).loadRuntime;
});

afterAll(async () => {
  if (!skip && pool) await pool.end();
});

beforeEach(async () => {
  if (skip) return;
  await pool.query(`DELETE FROM public.host_logs WHERE source LIKE 'app:pressure-test-%'`);
});

const log = (slug: string, message: string, daysAgo: number) =>
  pool.query(
    `INSERT INTO public.host_logs (ts, host, source, level, message)
     VALUES (now() - make_interval(days => $3), 'rpi', $1, 'error', $2)`,
    [`app:${slug}`, message, daysAgo],
  );

const project = (slug: string): PressureInput => ({
  slug,
  title: slug,
  status: 'hot',
  raw_frontmatter: { verdict: 'aktywny' },
  now_md: null,
  next_md: null,
  pain_md: null,
  repo_meta: null,
});

describe.skipIf(skip)('loadRuntime — down detection', () => {
  it('a DOWN row from 10 days ago with no later UP still counts: +5', async () => {
    await log('pressure-test-old', DOWN, 10);
    const rt = await loadRuntime();
    expect(rt.down.has('pressure-test-old')).toBe(true);
    const row = projectPressure(project('pressure-test-old'), [], rt);
    expect(row?.parts.runtime).toMatchObject({ down: true, points: WEIGHTS.down });
  });

  it('a later UP clears it', async () => {
    await log('pressure-test-ok', DOWN, 10);
    await log('pressure-test-ok', UP, 9);
    expect((await loadRuntime()).down.has('pressure-test-ok')).toBe(false);
  });
});
