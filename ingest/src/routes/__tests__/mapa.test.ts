/* GET /mapa/* — the SPA behind the viewer login. No database needed: the
 * route only reads files from PUBLIC_DIR (a temp dir here). */
import { createHash } from 'node:crypto';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import type { Hono } from 'hono';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

const dir = mkdtempSync(path.join(tmpdir(), 'mapa-'));
let app: Hono;
const cookie = `logs_auth=${createHash('sha256').update('pw').digest('hex')}`;

beforeAll(async () => {
  mkdirSync(path.join(dir, 'mapa', 'assets'), { recursive: true });
  writeFileSync(path.join(dir, 'mapa', 'index.html'), '<div id="root"></div>');
  writeFileSync(path.join(dir, 'mapa', 'assets', 'index-abc.js'), 'console.log(1)');
  Object.assign(process.env, { DATABASE_URL: 'postgres://x@127.0.0.1:1/x', INGEST_TOKEN: 't', LOGS_PASSWORD: 'pw' });
  process.env.PUBLIC_DIR = dir;
  delete process.env.AUTH_PUBLIC;
  const { Hono: HonoCls } = await import('hono');
  app = new HonoCls();
  (await import('../mapa.ts')).registerMapaRoutes(app);
});

afterAll(() => rmSync(dir, { recursive: true, force: true }));

const get = (p: string, withCookie = true) =>
  app.fetch(new Request(`http://x${p}`, { headers: withCookie ? { cookie } : {} }));

describe('/mapa', () => {
  it('sends anonymous viewers to the console login', async () => {
    const r = await get('/mapa/', false);
    expect(r.status).toBe(302);
    expect(r.headers.get('location')).toBe('/login');
  });

  it('serves the app, and the app again for deep links', async () => {
    for (const p of ['/mapa/', '/mapa/presja']) {
      const r = await get(p);
      expect(r.status).toBe(200);
      expect(await r.text()).toContain('id="root"');
      expect(r.headers.get('cache-control')).toBe('no-cache');
    }
    expect((await get('/mapa')).headers.get('location')).toBe('/mapa/');
  });

  it('serves hashed assets as immutable and 404s missing ones', async () => {
    const r = await get('/mapa/assets/index-abc.js');
    expect(r.status).toBe(200);
    expect(r.headers.get('cache-control')).toContain('immutable');
    expect((await get('/mapa/assets/nope.js')).status).toBe(404);
  });
});
