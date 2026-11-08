// Contract for POST /api/activity/runs and /api/activity/now — what
// agents/elitedesk/activity-watcher.py sends. Pure validation, no DB, so it is
// unit-testable without Postgres. Tables: migration 026.

export const RUN_KINDS = ['timer', 'service', 'gha'] as const;
export const RUN_RESULTS = ['running', 'ok', 'failed'] as const;

const MAX_RUNS = 500;
const MAX_TEXT = 300;
const MAX_LOG_LINES = 40;
const MAX_LOG_LINE = 500;
const MAX_SNAPSHOT_BYTES = 64_000;

export interface RunInput {
  kind: (typeof RUN_KINDS)[number];
  unit: string;
  invocation_id: string;
  project_slug: string | null;
  started_at: string;
  finished_at: string | null;
  result: (typeof RUN_RESULTS)[number];
  exit_code: number | null;
  cpu_ms: number | null;
  mem_peak_mb: number | null;
  repeat_count: number;
  url: string | null;
  detail: string | null;
  log_tail: string[];
}

type Rec = Record<string, unknown>;

function isRec(v: unknown): v is Rec {
  return !!v && typeof v === 'object' && !Array.isArray(v);
}

function text(v: unknown, max = MAX_TEXT): string | null {
  return typeof v === 'string' && v.trim() ? v.trim().slice(0, max) : null;
}

function int(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? Math.round(v) : null;
}

function ts(v: unknown): string | null {
  if (typeof v !== 'string' || Number.isNaN(Date.parse(v))) return null;
  return v;
}

function oneOf<T extends string>(v: unknown, allowed: readonly T[]): T | null {
  return typeof v === 'string' && (allowed as readonly string[]).includes(v) ? (v as T) : null;
}

/** One run, or a short reason why it was rejected. */
export function parseRun(v: unknown): RunInput | string {
  if (!isRec(v)) return 'not an object';
  const kind = oneOf(v.kind, RUN_KINDS);
  if (!kind) return 'invalid kind';
  const unit = text(v.unit);
  if (!unit) return 'invalid unit';
  const invocation = text(v.invocation_id, 128);
  if (!invocation) return 'invalid invocation_id';
  const started = ts(v.started_at);
  if (!started) return 'invalid started_at';
  const result = oneOf(v.result, RUN_RESULTS);
  if (!result) return 'invalid result';
  const logs = Array.isArray(v.log_tail) ? v.log_tail : [];
  return {
    kind,
    unit,
    invocation_id: invocation,
    project_slug: text(v.project_slug, 64),
    started_at: started,
    finished_at: ts(v.finished_at),
    result,
    exit_code: int(v.exit_code),
    cpu_ms: int(v.cpu_ms),
    mem_peak_mb: int(v.mem_peak_mb),
    repeat_count: Math.max(1, int(v.repeat_count) ?? 1),
    url: text(v.url, 500),
    detail: text(v.detail),
    log_tail: logs
      .filter((l): l is string => typeof l === 'string')
      .slice(-MAX_LOG_LINES)
      .map((l) => l.slice(0, MAX_LOG_LINE)),
  };
}

export interface RunsBatch {
  host: string;
  runs: RunInput[];
  rejected: { index: number; reason: string }[];
}

export function parseRunsBatch(body: unknown): RunsBatch | string {
  if (!isRec(body)) return 'body must be an object';
  const host = text(body.host, 63);
  if (!host) return 'invalid host';
  if (!Array.isArray(body.runs)) return 'runs must be an array';
  if (body.runs.length > MAX_RUNS) return `at most ${MAX_RUNS} runs per request`;
  const runs: RunInput[] = [];
  const rejected: RunsBatch['rejected'] = [];
  body.runs.forEach((r, index) => {
    const parsed = parseRun(r);
    if (typeof parsed === 'string') rejected.push({ index, reason: parsed });
    else runs.push(parsed);
  });
  return { host, runs, rejected };
}

/** Last write wins inside one batch — ON CONFLICT can't touch a row twice. */
export function dedupeRuns(runs: RunInput[]): RunInput[] {
  const byId = new Map<string, RunInput>();
  for (const r of runs) byId.set(r.invocation_id, r);
  return [...byId.values()];
}

export function parseSnapshot(body: unknown): { host: string; snapshot: Rec } | string {
  if (!isRec(body)) return 'body must be an object';
  const host = text(body.host, 63);
  if (!host) return 'invalid host';
  if (!isRec(body.snapshot)) return 'snapshot must be an object';
  if (JSON.stringify(body.snapshot).length > MAX_SNAPSHOT_BYTES) return 'snapshot too large';
  return { host, snapshot: body.snapshot };
}
