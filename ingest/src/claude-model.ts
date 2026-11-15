// Contract for POST /api/claude/sessions and /api/claude/events — what
// agents/claude-collector.py sends. Pure validation (no DB) so it is
// unit-testable. Per-record parsing: claude-record.ts. Tables: migration 032.

import { type EventInput, isRec, parseEvent, parseSession, type SessionInput, text } from './claude-record.ts';

export {
  EVENT_KINDS,
  type EventInput,
  parseEvent,
  parseSession,
  type SessionInput,
  SURFACES,
} from './claude-record.ts';

const MAX_SESSIONS = 200;
const MAX_EVENTS = 500;

interface Batch<T> {
  host: string;
  items: T[];
  rejected: { index: number; reason: string }[];
}

function batch<T>(body: unknown, key: string, max: number, parse: (v: unknown) => T | string): Batch<T> | string {
  if (!isRec(body)) return 'body must be an object';
  const host = text(body.host, 63);
  if (!host) return 'invalid host';
  const list = body[key];
  if (!Array.isArray(list)) return `${key} must be an array`;
  if (list.length > max) return `at most ${max} ${key} per request`;
  const items: T[] = [];
  const rejected: Batch<T>['rejected'] = [];
  list.forEach((v, index) => {
    const parsed = parse(v);
    if (typeof parsed === 'string') rejected.push({ index, reason: parsed });
    else items.push(parsed);
  });
  return { host, items, rejected };
}

export interface LiveSession {
  session_id: string;
  status: string;
}

export function parseSessionsBody(body: unknown): (Batch<SessionInput> & { live: LiveSession[] | null }) | string {
  const b = batch(body, 'sessions', MAX_SESSIONS, parseSession);
  if (typeof b === 'string') return b;
  const raw = isRec(body) ? body.live : undefined;
  const live = Array.isArray(raw)
    ? raw.flatMap((l) => {
        const id = isRec(l) ? text(l.session_id, 64) : null;
        return id ? [{ session_id: id, status: (isRec(l) && text(l.status, 20)) || 'running' }] : [];
      })
    : null;
  // Last write wins inside one batch — ON CONFLICT can't touch a row twice.
  const byId = new Map(b.items.map((s) => [s.session_id, s]));
  return { ...b, items: [...byId.values()], live };
}

export function parseEventsBody(body: unknown): Batch<EventInput> | string {
  return batch(body, 'events', MAX_EVENTS, parseEvent);
}

const WARSAW = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Warsaw' });

/** Distinct Warsaw calendar days touched by these timestamps (for signal recompute). */
export function warsawDays(stamps: string[]): string[] {
  return [...new Set(stamps.filter((s) => !Number.isNaN(Date.parse(s))).map((s) => WARSAW.format(new Date(s))))].sort();
}
