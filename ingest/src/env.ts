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
} as const;
