/* Integration test for the review gate (migration 033), against a real
 * Postgres like decisions.test.ts; skips when DATABASE_URL is unset.
 *
 * Covers: filing review sections (token only), a review-required decision
 * refused from the console and from a signed link, the page itself, and the
 * answer accepted only with the page's token, for the same commit, after
 * every section was opened.
 */
import { readFileSync } from 'node:fs';
import type { Hono } from 'hono';
import type pg from 'pg';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import type { sectionsVersion } from '../../review-store.ts';

const dbUrl = process.env.DATABASE_URL;
const token = process.env.INGEST_TOKEN || 'ci-token';
const skip = !dbUrl;
const SHA = 'a1b2c3d'.padEnd(40, '0');
const tokenHdr = { 'X-Ingest-Token': token, 'Content-Type': 'application/json' };
const formHdr = { 'Content-Type': 'application/x-www-form-urlencoded' };
// biome-ignore lint/suspicious/noExplicitAny: test fixtures read loosely-typed JSON bodies
type Json = Record<string, any>;

let pool: pg.Pool;
let app: Hono;
let secret: string;
let issue: (s: string, id: number, sha: string, version: string) => string;
let versionOf: typeof sectionsVersion;

beforeAll(async () => {
  if (skip) return;
  Object.assign(process.env, { INGEST_TOKEN: token, LOGS_PASSWORD: 'ci-password', AUTH_PUBLIC: '1' });
  process.env.PUBLIC_BASE_URL = 'http://console.test';
  const pgMod = await import('pg');
  pool = new pgMod.default.Pool({ connectionString: dbUrl, max: 4 });
  const r = await pool.query(
    `SELECT to_regclass('public.review_sections') AS s, to_regclass('public.pr_reviews') AS p`,
  );
  if (!r.rows[0].s || !r.rows[0].p) throw new Error('apply migrations 021, 028 and 033 first');
  const honoMod = await import('hono');
  const { registerDecisionsRoutes } = await import('../decisions.ts');
  const { registerReviewRoutes } = await import('../review.ts');
  ({
    env: { DECISION_SECRET: secret },
  } = await import('../../env.ts'));
  ({ issueReviewToken: issue } = await import('../../review-token.ts'));
  ({ sectionsVersion: versionOf } = await import('../../review-store.ts'));
  app = new honoMod.Hono();
  registerDecisionsRoutes(app);
  registerReviewRoutes(app);
});

afterAll(async () => {
  if (!skip && pool) await pool.end();
});

beforeEach(async () => {
  if (skip) return;
  await pool.query('DELETE FROM public.decisions');
  await pool.query('DELETE FROM public.review_sections');
  await pool.query('DELETE FROM public.pr_reviews');
});

const req = (path: string, init: RequestInit = {}) => app.fetch(new Request(`http://x${path}`, init));
const postJson = (path: string, body: unknown, headers: Record<string, string> = tokenHdr) =>
  req(path, { method: 'POST', headers, body: JSON.stringify(body) });
const postForm = (path: string, fields: Record<string, string>) =>
  req(path, { method: 'POST', headers: formHdr, body: new URLSearchParams(fields).toString() });

const MERGE_OPTIONS = [
  { key: 'yes', label: 'Scal' },
  { key: 'force', label: 'Scal mimo uwag' },
  { key: 'no', label: 'Odrzuć' },
  { key: 'later', label: 'Później' },
];

async function fileDecision(options: unknown[] = [MERGE_OPTIONS[0], MERGE_OPTIONS[2]]): Promise<Json> {
  const r = await postJson('/api/decisions', {
    routine: 'pr-decide',
    question: 'strummy #1079: fix',
    options,
    ref: `strummy#1079@${SHA}`,
    requires_review: true,
  });
  expect(r.status).toBe(201);
  return ((await r.json()) as Json).decision;
}

async function fileSections(body_md = 'Naprawia **zadania**.') {
  const sections = [{ key: 'summary', title: 'Opis PR', body_md }];
  const r = await postJson('/api/reviews/sections', {
    repo: 'strummy',
    number: 1079,
    head_sha: SHA,
    source: 'pr-decide',
    sections,
  });
  expect(r.status).toBe(201);
}

describe.skipIf(skip)('review gate', () => {
  it('files sections with the ingest token only, and validates them', async () => {
    const body = {
      repo: 'strummy',
      number: 1,
      head_sha: SHA,
      source: 'ci',
      sections: [{ key: 'x', title: 'X', body_md: 'y' }],
    };
    expect((await postJson('/api/reviews/sections', body, { 'Content-Type': 'application/json' })).status).toBe(401);
    expect((await postJson('/api/reviews/sections', { ...body, head_sha: 'not-hex' })).status).toBe(400);
    expect(
      (await postJson('/api/reviews/sections', { ...body, sections: [{ key: 'Bad Key', title: 'X', body_md: 'y' }] }))
        .status,
    ).toBe(400);
    expect((await postJson('/api/reviews/sections', body)).status).toBe(201);
  });

  it('refuses the console button and the signed link, hands out a review URL instead', async () => {
    const d = await fileDecision();
    expect(d.links).toEqual({});
    expect(d.review_url).toBe(`http://console.test/review/${d.id}`);
    const fromConsole = await postJson(
      `/api/decisions/${d.id}/answer`,
      { option: 'yes' },
      { 'Content-Type': 'application/json' },
    );
    expect(fromConsole.status).toBe(403);
    // A routine (ingest token) may still retire it — that is how pr-decide supersedes.
    const api = await postJson(`/api/decisions/${d.id}/answer`, { option: 'no', reason: 'superseded' });
    expect(api.status).toBe(200);
  });

  it('refuses a merging option from an ingest-token caller; it may still retire or refuse the question', async () => {
    const d = await fileDecision(MERGE_OPTIONS);
    const fixing = await fileDecision([
      { key: 'fix', label: 'Popraw' },
      { key: 'later', label: 'Później' },
    ]);
    expect((await postJson(`/api/decisions/${fixing.id}/answer`, { option: 'fix' })).status).toBe(403);
    for (const option of ['yes', 'force']) {
      const r = await postJson(`/api/decisions/${d.id}/answer`, { option });
      expect(r.status).toBe(403);
      expect(((await r.json()) as Json).error).toContain('review page');
    }
    const still = await pool.query('SELECT answer FROM public.decisions WHERE id = $1', [d.id]);
    expect(still.rows[0].answer).toBeNull();
    expect((await postJson(`/api/decisions/${d.id}/answer`, { option: 'later', reason: 'superseded' })).status).toBe(
      200,
    );
    const other = await fileDecision(MERGE_OPTIONS);
    expect((await postJson(`/api/decisions/${other.id}/answer`, { option: 'no', reason: 'x' })).status).toBe(200);
  });

  it('forces requires_review for pr-decide even when the caller omits the flag', async () => {
    const ask = (routine: string) =>
      postJson('/api/decisions', { routine, question: 'q', options: ['yes', 'no'], ref: `strummy#1@${SHA}` });
    const d = ((await (await ask('pr-decide')).json()) as Json).decision;
    expect(d.requires_review).toBe(true);
    expect(d.links).toEqual({});
    expect(d.review_url).toBe(`http://console.test/review/${d.id}`);
    const apiYes = await postJson(`/api/decisions/${d.id}/answer`, { option: 'yes' });
    expect(apiYes.status).toBe(403);
    const other = ((await (await ask('some-routine')).json()) as Json).decision;
    expect(other.requires_review).toBe(false);
    expect(Object.keys(other.links)).toEqual(['yes', 'no']);
  });

  it('migration 033 puts the gate on questions that were open before it, and is idempotent', async () => {
    const sql = readFileSync(new URL('../../../../postgres/migrations/033_review_gate.sql', import.meta.url), 'utf8');
    const ins = (routine: string, answer: string | null) =>
      pool.query(
        `INSERT INTO public.decisions (routine, question, options, expires_at, answer, answered_at, answered_via)
         VALUES ($1, 'q', '["yes","no"]'::jsonb, now() + interval '1 day', $2, CASE WHEN $2::text IS NULL THEN NULL ELSE now() END,
                 CASE WHEN $2::text IS NULL THEN NULL ELSE 'console' END) RETURNING id`,
        [routine, answer],
      );
    const old = (await ins('pr-decide', null)).rows[0].id;
    const answered = (await ins('pr-decide', 'no')).rows[0].id;
    const unrelated = (await ins('seo-decide', null)).rows[0].id;
    for (let i = 0; i < 2; i++) await pool.query(sql);
    const rows = await pool.query('SELECT id, requires_review FROM public.decisions WHERE id = ANY($1)', [
      [old, answered, unrelated],
    ]);
    const flag = (id: string) => rows.rows.find((r) => String(r.id) === String(id))?.requires_review;
    expect(flag(old)).toBe(true);
    expect(flag(answered)).toBe(false);
    expect(flag(unrelated)).toBe(false);
  });

  it('rejects a page whose section was re-filed under the same key after it loaded', async () => {
    const d = await fileDecision();
    await fileSections('CI: pending');
    const html = await (await req(`/review/${d.id}`)).text();
    const tok = /name="token" value="([^"]+)"/.exec(html)?.[1] ?? '';
    await fileSections('CI: failure');
    const stale = await postForm(`/review/${d.id}`, { option: 'yes', token: tok, opened: 'pr-review,summary' });
    expect(stale.status).toBe(409);
    const body = await stale.text();
    expect(body).toContain('sekcje się zmieniły');
    expect(body).toContain('CI: failure');
    const fresh = /name="token" value="([^"]+)"/.exec(body)?.[1] ?? '';
    const ok = await postForm(`/review/${d.id}`, { option: 'yes', token: fresh, opened: 'pr-review,summary' });
    expect(ok.status).toBe(200);
  });

  it('shows the page, marks it opened, and accepts the answer only after every section was opened', async () => {
    const d = await fileDecision();
    await fileSections();
    const page = await req(`/review/${d.id}`);
    expect(page.status).toBe(200);
    const html = await page.text();
    expect(html).toContain('data-key="pr-review"');
    expect(html).toContain('data-key="summary"');
    expect(html).toContain('brak recenzji tego commitu');
    const tok = /name="token" value="([^"]+)"/.exec(html)?.[1] ?? '';
    const seen = await pool.query('SELECT reviewed_at FROM public.decisions WHERE id = $1', [d.id]);
    expect(seen.rows[0].reviewed_at).not.toBeNull();

    expect((await postForm(`/review/${d.id}`, { option: 'yes', token: '', opened: 'pr-review,summary' })).status).toBe(
      409,
    );
    const partial = await postForm(`/review/${d.id}`, { option: 'yes', token: tok, opened: 'pr-review' });
    expect(partial.status).toBe(409);
    expect(await partial.text()).toContain('Nierozwinięte sekcje: summary');
    expect((await postForm(`/review/${d.id}`, { option: 'no', token: tok, opened: 'pr-review,summary' })).status).toBe(
      400,
    );

    const ok = await postForm(`/review/${d.id}`, { option: 'yes', token: tok, opened: 'pr-review,summary' });
    expect(ok.status).toBe(200);
    const row = await pool.query('SELECT answer, answered_via FROM public.decisions WHERE id = $1', [d.id]);
    expect(row.rows[0]).toEqual({ answer: 'yes', answered_via: 'review' });
  });

  it('rejects a token issued for another commit — the PR moved after the page was opened', async () => {
    const d = await fileDecision();
    const stale = issue(secret, Number(d.id), 'f'.repeat(40), versionOf([]));
    const r = await postForm(`/review/${d.id}`, { option: 'yes', token: stale, opened: 'pr-review' });
    expect(r.status).toBe(409);
    expect(await r.text()).toContain('nie pasuje do tego commitu');
  });

  it('a section filed after the page loaded must be opened too', async () => {
    const d = await fileDecision();
    const tok = issue(secret, Number(d.id), SHA, versionOf([]));
    await fileSections();
    const r = await postForm(`/review/${d.id}`, { option: 'yes', token: tok, opened: 'pr-review' });
    expect(r.status).toBe(409);
  });

  it('shows the pr-review verdict and findings for the same commit', async () => {
    const d = await fileDecision();
    await pool.query(
      `INSERT INTO public.pr_reviews (repo, number, head_sha, verdict, summary, findings)
       VALUES ('strummy', 1079, $1, 'zmiany', 'Brak testu.', $2::jsonb)`,
      [SHA, JSON.stringify([{ severity: 'ważne', file: 'app/x.ts', line: 5, problem: 'Brak <testu>' }])],
    );
    const html = await (await req(`/review/${d.id}`)).text();
    expect(html).toContain('verdict zmiany');
    expect(html).toContain('app/x.ts:5');
    expect(html).toContain('Brak &lt;testu&gt;');
  });
});
