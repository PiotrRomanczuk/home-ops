import path from 'node:path';
import { serveStatic } from '@hono/node-server/serve-static';
import type { Hono, MiddlewareHandler } from 'hono';
import { hasViewerAuth } from '../auth.ts';
import { env } from '../env.ts';

// The Mapa tab: a React SPA built from ingest/web into public/mapa (Vite
// base /mapa/). Same viewer login as the console; hashed assets are cached
// for good, index.html never, and unknown paths fall back to the app.

const viewerPage: MiddlewareHandler = async (c, next) =>
  env.AUTH_PUBLIC || hasViewerAuth(c) ? next() : c.redirect('/login');

// Set on 200s only, after serveStatic answered (a missing asset must not be cached).
const cacheOnHit =
  (value: string): MiddlewareHandler =>
  async (c, next) => {
    await next();
    if (c.res.status === 200) c.res.headers.set('Cache-Control', value);
  };

export function registerMapaRoutes(app: Hono): void {
  // serveStatic resolves `root` against the working directory.
  const root = path.relative(process.cwd(), env.PUBLIC_DIR) || '.';

  app.get('/mapa', (c) => c.redirect('/mapa/'));
  app.use('/mapa/*', viewerPage);
  app.use('/mapa/assets/*', cacheOnHit('public, max-age=31536000, immutable'), serveStatic({ root }));
  app.get('/mapa/assets/*', (c) => c.text('not found', 404));
  app.get('/mapa/*', cacheOnHit('no-cache'), serveStatic({ path: path.join(root, 'mapa', 'index.html') }));
}
