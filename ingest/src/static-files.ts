import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { env } from './env.ts';

const MIME: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
};

export async function serveStatic(name: string): Promise<Response> {
  const safe = name.replace(/[^\w.-]/g, '');
  const ext = path.extname(safe).toLowerCase();
  const mime = MIME[ext] ?? 'application/octet-stream';
  try {
    const body = await readFile(path.join(env.PUBLIC_DIR, safe));
    return new Response(body, { headers: { 'content-type': mime, 'cache-control': 'no-cache' } });
  } catch {
    return new Response('not found', { status: 404 });
  }
}
