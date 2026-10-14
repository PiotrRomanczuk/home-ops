/* Integration test for the decisions inbox + digest cards, against a real
 * Postgres (CI `services: postgres`, or a local instance via DATABASE_URL).
 * Skips entirely when DATABASE_URL is unset, like jobs-state-machine.
 *
 * Covers: filing a decision (token only), answering once (console / api /
 * signed link), the 409 on a second answer, expiry, consume, and the card
 * contract's validation + freshness flag.
 */
import type { Hono } from 'hono';
import type pg from 'pg';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';

const dbUrl = process.env.DATABASE_URL;
const token = process.env.INGEST_TOKEN || 'ci-token';
const skip = !dbUrl;
const tokenHdr = { 'X-Ingest-Token': token, 'Content-Type': 'application/json' };
const jsonHdr = { 'Content-Type': 'application/json' };
// biome-ignore lint/suspicious/noExplicitAny: test fixtures read loosely-typed JSON bodies
type Json = Record<string, any>;
const json = async (r: Response) => (await r.json()) as Json;

let pool: pg.Pool;
let app: Hono;

beforeAll(async () => {
  if (skip) return;
  process.env.INGEST_TOKEN = token;
  process.env.LOGS_PASSWORD = 'ci-password';
  process.env.PUBLIC_BASE_URL = 'http://console.test';
  const pgMod = await import('pg');
  pool = new pgMod.default.Pool({ connectionString: dbUrl, max: 4 });
  const r = await pool.query(`SELECT to_regclass('public.decisions') AS d, to_regclass('public.digest_cards') AS c`);
  if (!r.rows[0].d || !r.rows[0].c) throw new Error('apply migrations 020 + 021 first');
  const honoMod = await import('hono');
  const { registerDecisionsRoutes } = await import('../decisions.ts');
  const { registerCardsRoutes } = await import('../cards.ts');
  app = new honoMod.Hono();
  registerDecisionsRoutes(app);
  registerCardsRoutes(app);
});

afterAll(async () => {
  if (!skip && pool) await pool.end();
});

beforeEach(async () => {
  if (skip) return;
  await pool.query('DELETE FROM public.decisions');
  await pool.query('DELETE FROM public.digest_cards');
});

const post = (path: string, body: unknown, headers: Record<string, string> = tokenHdr) =>
  app.fetch(new Request(`http://x${path}`, { method: 'POST', headers, body: JSON.stringify(body) }));
const get = (path: string, headers: Record<string, string> = {}) =>
  app.fetch(new Request(`http://x${path}`, { headers }));

async function file(extra: Record<string, unknown> = {}) {
  const r = await post('/api/decisions', { routine: 'seo-improve', question: 'Merge PR #52?', ...extra });
  expect(r.status).toBe(201);
  return ((await r.json()) as Json).decision;
}

describe.skipIf(skip)('decisions inbox', () => {
  it('requires the ingest token to file, and hands signed links only to token callers', async () => {
    const anon = await post('/api/decisions', { routine: 'x', question: 'q' }, jsonHdr);
    expect(anon.status).toBe(401);
    const d = await file();
    expect(d.state).toBe('open');
    expect(d.options).toEqual([
      { key: 'yes', label: 'yes' },
      { key: 'no', label: 'no' },
    ]);
    expect(d.links.yes).toMatch(/^http:\/\/console\.test\/d\/\d+\/yes\/\d+\/[\w-]{32}$/);

    process.env.AUTH_PUBLIC = '1';
    const listed = await json(await get('/api/decisions', tokenHdr));
    expect(listed.decisions[0].links.no).toBeDefined();
  });

  it('answers once; a second answer is a 409 that returns the existing row', async () => {
    const d = await file();
    const a = await post(`/api/decisions/${d.id}/answer`, { option: 'yes' }, tokenHdr);
    expect(a.status).toBe(200);
    expect((await json(a)).decision).toMatchObject({ answer: 'yes', answered_via: 'api', state: 'answered' });
    const b = await post(`/api/decisions/${d.id}/answer`, { option: 'no', reason: 'late' }, tokenHdr);
    expect(b.status).toBe(409);
    expect((await json(b)).decision.answer).toBe('yes');
  });

  it('rejects an option that was not offered', async () => {
    const d = await file({ options: ['publish', 'hold'] });
    const r = await post(`/api/decisions/${d.id}/answer`, { option: 'yes' }, tokenHdr);
    expect(r.status).toBe(400);
  });

  it('signed link: GET confirms, POST records with reason, replay is refused', async () => {
    const d = await file();
    const url = new URL(d.links.no).pathname;
    const page = await get(url);
    expect(page.status).toBe(200);
    expect(await page.text()).toContain('Merge PR #52?');
    expect((await getRow(d.id)).answer).toBeNull(); // GET never answers

    const rec = await app.fetch(
      new Request(`http://x${url}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 'reason=wrong+tone',
      }),
    );
    expect(rec.status).toBe(200);
    expect(await getRow(d.id)).toMatchObject({ answer: 'no', reason: 'wrong tone', answered_via: 'link' });

    const again = await app.fetch(new Request(`http://x${url}`, { method: 'POST' }));
    expect(again.status).toBe(409);
    const forged = await get(url.replace(/\/no\//, '/yes/'));
    expect(forged.status).toBe(403);
  });

  it('expires: state flips, answering fails, link page says so', async () => {
    const d = await file();
    await pool.query(`UPDATE public.decisions SET expires_at = now() - interval '1 minute' WHERE id = $1`, [d.id]);
    expect((await getRow(d.id)).state).toBe('expired');
    const r = await post(`/api/decisions/${d.id}/answer`, { option: 'yes' }, tokenHdr);
    expect(r.status).toBe(409);
    // The link's own exp is still in the future, so the signature passes and
    // the page reports the DB state instead of recording anything.
    const page = await get(new URL(d.links.yes).pathname);
    expect(page.status).toBe(409);
    expect(await page.text()).toContain('expired');
  });

  it('consume marks an answered decision as acted on, once', async () => {
    const d = await file();
    expect((await post(`/api/decisions/${d.id}/consume`, {})).status).toBe(409);
    await post(`/api/decisions/${d.id}/answer`, { option: 'yes' }, tokenHdr);
    expect((await post(`/api/decisions/${d.id}/consume`, {})).status).toBe(200);
    expect((await post(`/api/decisions/${d.id}/consume`, {})).status).toBe(409);
  });
});

describe.skipIf(skip)('digest cards', () => {
  it('validates the contract and reports freshness', async () => {
    const bad = await post('/api/cards', { routine: 'seo', headline: '' });
    expect(bad.status).toBe(400);
    const ok = await post('/api/cards', {
      routine: 'seo-analyse',
      slug: 'gitara-lekcje',
      headline: 'Traffic flat, 2 hypotheses added',
      items: [{ text: 'H3: district pages', url: 'https://example.com/plan' }],
      metric: { label: 'clicks 7d', value: 12, delta: 3 },
    });
    expect(ok.status).toBe(201);
    await post('/api/cards', { routine: 'job-radar', headline: 'old', fresh_hours: 1 });
    await pool.query(`UPDATE public.digest_cards SET ran_at = now() - interval '2 hours' WHERE routine = 'job-radar'`);
    const latest = await json(await get('/api/cards', tokenHdr));
    const byRoutine = Object.fromEntries(
      latest.cards.map((c: { routine: string; is_fresh: boolean }) => [c.routine, c.is_fresh]),
    );
    expect(byRoutine).toEqual({ 'seo-analyse': true, 'job-radar': false });
  });
});

async function getRow(id: string | number) {
  const r = await pool.query(
    `SELECT answer, reason, answered_via, public.decision_state(decisions.*) AS state FROM public.decisions WHERE id = $1`,
    [id],
  );
  return r.rows[0];
}
