/* Integration test for claude_sessions / claude_events (032): upsert, project
 * resolution from git remote / folder / vault path, live status, and the
 * Postęp signals recomputed (not added) per touched day. Skips when
 * DATABASE_URL is unset. Needs migrations 005, 016, 027, 032.
 */
import type { Hono } from 'hono';
import type pg from 'pg';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';

const dbUrl = process.env.DATABASE_URL;
const token = process.env.INGEST_TOKEN || 'ci-token';
const skip = !dbUrl;
const tokenHdr = { 'X-Ingest-Token': token, 'Content-Type': 'application/json' };
// biome-ignore lint/suspicious/noExplicitAny: test fixtures read loosely-typed JSON bodies
type Json = Record<string, any>;

let pool: pg.Pool;
let app: Hono;

beforeAll(async () => {
  if (skip) return;
  process.env.INGEST_TOKEN = token;
  process.env.LOGS_PASSWORD = 'ci-password';
  const pgMod = await import('pg');
  pool = new pgMod.default.Pool({ connectionString: dbUrl, max: 4 });
  const r = await pool.query(`SELECT to_regclass('public.claude_sessions') AS t`);
  if (!r.rows[0].t) throw new Error('apply migration 032 first');
  const { Hono: HonoCls } = await import('hono');
  app = new HonoCls();
  (await import('../claude.ts')).registerClaudeRoutes(app);
});

afterAll(async () => {
  if (!skip && pool) await pool.end();
});

beforeEach(async () => {
  if (skip) return;
  await pool.query('TRUNCATE public.claude_sessions, public.claude_events, public.project_signals, public.projects');
  await pool.query(`INSERT INTO public.projects (slug, title, status, path, raw_frontmatter) VALUES
    ('home-ops', 'home-ops', 'hot', NULL, '{"repo":"home-ops"}'),
    ('song2logic', 'song2logic', 'warm', NULL, '{"repo":"github.com/PiotrRomanczuk/song2logic (prywatne, od 2026-11-09)"}'),
    ('job-radar', 'job-radar', 'warm', '~/code/vector-digital/job-radar', '{}')`);
});

const req = (method: string, path: string, body?: unknown, headers: Record<string, string> = tokenHdr) =>
  app.fetch(new Request(`http://x${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined }));
const json = async (r: Response) => (await r.json()) as Json;
const sess = (id: string, extra: Json = {}) => ({
  session_id: id,
  surface: 'cli',
  started_at: '2026-11-14T09:00:00Z',
  last_at: '2026-11-14T10:00:00Z',
  ...extra,
});
const ev = (sid: string, uuid: string, kind: string, ts = '2026-11-14T09:30:00Z') => ({
  session_id: sid,
  uuid,
  ts,
  kind,
  text: kind,
});
const signals = async () =>
  (
    await pool.query(`SELECT project_slug, to_char(day, 'YYYY-MM-DD') AS day, signal, n FROM public.project_signals
                       ORDER BY 1, 2, 3`)
  ).rows;

describe.skipIf(skip)('claude routes', () => {
  it('requires the ingest token to write', async () => {
    expect((await req('POST', '/api/claude/sessions', { host: 'mac', sessions: [] }, {})).status).toBe(401);
  });

  it('resolves projects from remote, repo URL remark, and vault path', async () => {
    const r = await req('POST', '/api/claude/sessions', {
      host: 'mac',
      sessions: [
        sess('a', { git_remote: 'PiotrRomanczuk/home-ops', cwd: '/Users/p/code/homelab/home-ops/.claude/worktrees/x' }),
        sess('b', { git_remote: 'PiotrRomanczuk/song2logic', cwd: '/Users/p/code/produkty/song2logic' }),
        sess('c', { cwd: '/Users/p/code/vector-digital/job-radar/ops' }),
        sess('d', { cwd: '/Users/p', files_edited: ['/Users/p/Obsidian/Vault/inbox.md'] }),
        // Started from ~, but edited mostly job-radar files (grouped ~/code/<group>/<slug>/ layout).
        sess('e', {
          cwd: '/Users/p',
          files_edited: [
            '/Users/p/code/vector-digital/job-radar/a.py',
            '/Users/p/code/vector-digital/job-radar/b.py',
            '/Users/p/code/homelab/home-ops/c.ts',
          ],
        }),
      ],
    });
    expect(await json(r)).toEqual({ upserted: 5, rejected: [] });
    const rows = (await pool.query(`SELECT session_id, project_slug FROM public.claude_sessions ORDER BY 1`)).rows;
    expect(rows.map((x) => x.project_slug)).toEqual(['home-ops', 'song2logic', 'job-radar', null, 'job-radar']);
  });

  it('an exact repo match beats a parent note without `repo:` (NULL must not sort first)', async () => {
    await pool.query(`INSERT INTO public.projects (slug, title, status, path, raw_frontmatter) VALUES
      ('marszal', 'marszal', 'warm', '~/code/klienci/marszal', '{"repo":""}'),
      ('instagram-stories-webhook', 'instagram-stories-webhook', 'warm',
       '~/code/klienci/marszal/instagram-stories-webhook', '{"repo":"instagram-stories-webhook"}')`);
    await req('POST', '/api/claude/sessions', {
      host: 'mac',
      sessions: [
        sess('n', {
          git_remote: 'PiotrRomanczuk/instagram-stories-webhook',
          cwd: '/Users/p/code/klienci/marszal/instagram-stories-webhook',
        }),
        sess('m', { cwd: '/Users/p/code/klienci/marszal/notes' }),
      ],
    });
    const rows = (await pool.query(`SELECT session_id, project_slug FROM public.claude_sessions ORDER BY 1`)).rows;
    expect(rows.map((x) => x.project_slug)).toEqual(['marszal', 'instagram-stories-webhook']);
  });

  it('events recompute signals per day; re-sending does not double count', async () => {
    await req('POST', '/api/claude/sessions', { host: 'mac', sessions: [sess('a', { git_remote: 'x/home-ops' })] });
    const events = [ev('a', 'p1', 'prompt'), ev('a', 'p2', 'prompt'), ev('a', 'b1', 'bash')];
    expect(await json(await req('POST', '/api/claude/events', { host: 'mac', events }))).toEqual({
      inserted: 3,
      rejected: [],
    });
    await req('POST', '/api/claude/events', { host: 'mac', events });
    expect(await signals()).toEqual([
      { project_slug: 'home-ops', day: '2026-11-14', signal: 'claude_prompts', n: 2 },
      { project_slug: 'home-ops', day: '2026-11-14', signal: 'claude_sessions', n: 1 },
    ]);
  });

  it('a session mapped later moves its earlier prompts into Postęp', async () => {
    await req('POST', '/api/claude/sessions', { host: 'mac', sessions: [sess('z', { cwd: '/tmp/x' })] });
    await req('POST', '/api/claude/events', { host: 'mac', events: [ev('z', 'p1', 'prompt')] });
    expect(await signals()).toEqual([]);
    await req('POST', '/api/claude/sessions', { host: 'mac', sessions: [sess('z', { git_remote: 'o/home-ops' })] });
    expect((await signals()).map((s) => s.signal)).toEqual(['claude_prompts', 'claude_sessions']);
  });

  it('live list sets status and clears sessions that ended', async () => {
    await req('POST', '/api/claude/sessions', { host: 'mac', sessions: [sess('a'), sess('b')] });
    await req('POST', '/api/claude/sessions', {
      host: 'mac',
      sessions: [],
      live: [{ session_id: 'a', status: 'busy' }],
    });
    await req('POST', '/api/claude/sessions', {
      host: 'mac',
      sessions: [],
      live: [{ session_id: 'b', status: 'idle' }],
    });
    const rows = (await pool.query(`SELECT session_id, live_status FROM public.claude_sessions ORDER BY 1`)).rows;
    expect(rows).toEqual([
      { session_id: 'a', live_status: null },
      { session_id: 'b', live_status: 'idle' },
    ]);
  });

  it('GET sessions of a day with that day’s prompt count, and a session’s events', async () => {
    await req('POST', '/api/claude/sessions', { host: 'mac', sessions: [sess('a', { title: 'Dziennik' })] });
    await req('POST', '/api/claude/events', {
      host: 'mac',
      events: [ev('a', 'p1', 'prompt'), ev('a', 'p0', 'prompt', '2026-11-13T09:00:00Z')],
    });
    const day = await json(await req('GET', '/api/claude/sessions?day=2026-11-14'));
    expect(day.sessions.map((s: Json) => [s.title, s.prompts_day])).toEqual([['Dziennik', 1]]);
    const evs = await json(await req('GET', '/api/claude/events?session=a&kind=prompt'));
    expect(evs.events.map((e: Json) => e.uuid)).toEqual(['p0', 'p1']);
    expect((await req('GET', '/api/claude/events')).status).toBe(400);
  });
});
