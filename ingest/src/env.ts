import { createHash } from 'node:crypto';
import path from 'node:path';

const DATABASE_URL = process.env.DATABASE_URL;
const INGEST_TOKEN = process.env.INGEST_TOKEN;
const LOGS_PASSWORD = process.env.LOGS_PASSWORD;

if (!DATABASE_URL) throw new Error('DATABASE_URL required');
if (!INGEST_TOKEN) throw new Error('INGEST_TOKEN required');
if (!LOGS_PASSWORD) throw new Error('LOGS_PASSWORD required');

export const env = {
  DATABASE_URL,
  INGEST_TOKEN,
  LOGS_PASSWORD,
  PORT: Number(process.env.PORT ?? 8080),
  PUBLIC_DIR: process.env.PUBLIC_DIR ?? path.resolve(process.cwd(), 'public'),
  // When set, the viewer login is bypassed and the console is open to anyone
  // who can reach the port. Worker/token endpoints stay protected regardless.
  AUTH_PUBLIC: process.env.AUTH_PUBLIC === '1' || process.env.AUTH_PUBLIC === 'true',
  // Signs the one-tap decision links in the digest email. Falls back to a
  // hash of INGEST_TOKEN so a fresh deploy needs no extra secret; set it
  // explicitly to rotate links independently of the ingest token.
  DECISION_SECRET: process.env.DECISION_SECRET || createHash('sha256').update(`decision:${INGEST_TOKEN}`).digest('hex'),
  // Where the email's links point (LAN/Tailscale console URL). Without it the
  // digest still renders, with relative links that only work from the console.
  PUBLIC_BASE_URL: (process.env.PUBLIC_BASE_URL || '').replace(/\/$/, ''),
} as const;
