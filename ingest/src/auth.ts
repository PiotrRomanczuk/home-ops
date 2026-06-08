import { createHash } from 'node:crypto';
import type { Context, MiddlewareHandler } from 'hono';
import { deleteCookie, getCookie, setCookie } from 'hono/cookie';
import { env } from './env.ts';

const COOKIE_NAME = 'logs_auth';
const COOKIE_VALUE = createHash('sha256').update(env.LOGS_PASSWORD).digest('hex');

export function hasViewerAuth(c: Context): boolean {
  return getCookie(c, COOKIE_NAME) === COOKIE_VALUE;
}

export function hasIngestToken(c: Context): boolean {
  return c.req.header('X-Ingest-Token') === env.INGEST_TOKEN;
}

export const tokenOnly: MiddlewareHandler = async (c, next) =>
  hasIngestToken(c) ? next() : c.json({ error: 'unauthorized' }, 401);

export const viewerOrToken: MiddlewareHandler = async (c, next) =>
  hasViewerAuth(c) || hasIngestToken(c) ? next() : c.json({ error: 'unauthorized' }, 401);

export function setAuthCookie(c: Context): void {
  setCookie(c, COOKIE_NAME, COOKIE_VALUE, {
    httpOnly: true,
    sameSite: 'Lax',
    path: '/',
    maxAge: 60 * 60 * 24 * 30,
  });
}

export function clearAuthCookie(c: Context): void {
  deleteCookie(c, COOKIE_NAME);
}
