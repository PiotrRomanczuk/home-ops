// Contract for POST /api/queue/sync — the vault's QUEUE.md mirrored by
// planner-sync (agents/elitedesk/queue_md.py). Pure validation, no DB, so it
// is unit-testable without Postgres. See docs/adr/2026-10-20-queue-state.md.

export const QUEUE_SECTIONS = ['in_progress', 'queue', 'local', 'waiting', 'done'] as const;
export type QueueSection = (typeof QUEUE_SECTIONS)[number];

const CLASSES = new Set(['risk', 'money', 'focus', 'clean', 'idea']);
const SIZES = new Set(['S', 'M', 'L', 'XL']);
const FLAGS = new Set(['unblocks', 'local', 'paused', 'experiment']);
const MAX_TICKETS = 50;
const MAX_TEXT = 600;
const MAX_BRIEF = 2000;
const MAX_HEADER = 300;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export interface QueueTicket {
  done: boolean;
  cls: string | null;
  size: string | null;
  flags: string[];
  project: string | null;
  id: string | null;
  text: string;
  model: string | null;
  meta: string | null;
  brief: string | null;
  hours: number | null;
  date: string | null;
}

export interface QueueInput {
  window_from: string | null;
  window_to: string | null;
  capacity_hours: number | null;
  focus: string | null;
  rules: string | null;
  sections: Partial<Record<QueueSection, QueueTicket[]>>;
  summary: Record<string, number>;
  source_hash: string | null;
}

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);

function optText(v: unknown, max: number): string | null | undefined {
  if (v === undefined || v === null) return null;
  if (typeof v !== 'string' || v.length > max) return undefined;
  return v.trim() || null;
}

function isRealDate(s: string): boolean {
  return DATE_RE.test(s) && new Date(`${s}T00:00:00Z`).toISOString().slice(0, 10) === s;
}

function optDate(v: unknown): string | null | undefined {
  if (v === undefined || v === null) return null;
  return typeof v === 'string' && isRealDate(v) ? v : undefined;
}

function optNumber(v: unknown, max: number): number | null | undefined {
  if (v === undefined || v === null) return null;
  return typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= max ? v : undefined;
}

/** One ticket; returns the clean ticket or a reason string. */
export function parseTicket(v: unknown): QueueTicket | string {
  if (!isObj(v)) return 'ticket must be an object';
  const text = optText(v.text, MAX_TEXT);
  if (text === undefined) return `text too long (max ${MAX_TEXT})`;
  const cls = v.cls === null || v.cls === undefined ? null : v.cls;
  if (cls !== null && !(typeof cls === 'string' && CLASSES.has(cls))) return 'cls must be risk|money|focus|clean|idea';
  const size = v.size === null || v.size === undefined ? null : v.size;
  if (size !== null && !(typeof size === 'string' && SIZES.has(size))) return 'size must be S|M|L|XL';
  const flags = v.flags === undefined ? [] : v.flags;
  if (!Array.isArray(flags) || flags.length > 5 || !flags.every((f) => typeof f === 'string' && FLAGS.has(f)))
    return 'flags must be a short list of unblocks|local|paused|experiment';
  const fields = {
    project: optText(v.project, 80),
    id: optText(v.id, 20),
    model: optText(v.model, 80),
    meta: optText(v.meta, MAX_TEXT),
    brief: optText(v.brief, MAX_BRIEF),
  };
  for (const [k, val] of Object.entries(fields)) if (val === undefined) return `${k} too long`;
  const hours = optNumber(v.hours, 1000);
  if (hours === undefined) return 'hours must be a non-negative number';
  const date = optDate(v.date);
  if (date === undefined) return 'date must be YYYY-MM-DD';
  return {
    done: v.done === true,
    cls: cls as string | null,
    size: size as string | null,
    flags: flags as string[],
    text: text ?? '',
    hours,
    date,
    ...(fields as {
      project: string | null;
      id: string | null;
      model: string | null;
      meta: string | null;
      brief: string | null;
    }),
  };
}

/** Whole POST body; returns the clean queue or an error message. */
export function parseQueue(body: unknown): QueueInput | string {
  if (!isObj(body)) return 'object body required';
  const windowFrom = optDate(body.window_from);
  const windowTo = optDate(body.window_to);
  if (windowFrom === undefined || windowTo === undefined) return 'window_from/window_to must be YYYY-MM-DD';
  const capacity = optNumber(body.capacity_hours, 1000);
  if (capacity === undefined) return 'capacity_hours must be a non-negative number';
  const focus = optText(body.focus, MAX_HEADER);
  const rules = optText(body.rules, MAX_HEADER);
  const hash = optText(body.source_hash, 64);
  if (focus === undefined || rules === undefined || hash === undefined) return 'focus/rules/source_hash too long';
  if (!isObj(body.sections)) return 'sections object required';
  const sections: QueueInput['sections'] = {};
  for (const key of QUEUE_SECTIONS) {
    const raw = body.sections[key];
    if (raw === undefined) continue;
    if (!Array.isArray(raw) || raw.length > MAX_TICKETS) return `sections.${key}: array of at most ${MAX_TICKETS}`;
    const tickets: QueueTicket[] = [];
    for (const [i, t] of raw.entries()) {
      const parsed = parseTicket(t);
      if (typeof parsed === 'string') return `sections.${key}[${i}]: ${parsed}`;
      tickets.push(parsed);
    }
    sections[key] = tickets;
  }
  const summary: Record<string, number> = {};
  if (isObj(body.summary))
    for (const [k, val] of Object.entries(body.summary))
      if (typeof val === 'number' && Number.isFinite(val) && k.length <= 40) summary[k] = val;
  return {
    window_from: windowFrom,
    window_to: windowTo,
    capacity_hours: capacity,
    focus,
    rules,
    sections,
    summary,
    source_hash: hash,
  };
}
