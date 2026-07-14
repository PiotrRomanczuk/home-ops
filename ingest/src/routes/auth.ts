import type { Hono } from 'hono';
import { clearAuthCookie, hasViewerAuth, setAuthCookie } from '../auth.ts';
import { env } from '../env.ts';
import { serveStatic } from '../static-files.ts';

export function registerAuthRoutes(app: Hono): void {
  app.post('/api/auth/login', async (c) => {
    const body = (await c.req.json().catch(() => ({}))) as { password?: string };
    if (body.password !== env.LOGS_PASSWORD) return c.json({ error: 'invalid password' }, 401);
    setAuthCookie(c);
    return c.json({ ok: true });
  });

  app.post('/api/auth/logout', async (c) => {
    clearAuthCookie(c);
    return c.json({ ok: true });
  });

  app.get('/login', () => serveStatic('login.html'));
  app.get('/static/:name', async (c) => serveStatic(c.req.param('name')));

  app.get('/', (c) => {
    // AUTH_PUBLIC opens the console with no viewer login. The API viewer-guard
    // already honors it (auth.ts); the root page must too, else it bounces to
    // /login even in public mode. Worker/token endpoints stay protected.
    if (!env.AUTH_PUBLIC && !hasViewerAuth(c)) return c.redirect('/login');
    return serveStatic('index.html');
  });
}
