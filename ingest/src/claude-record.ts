// One session / one event as agents/claude-collector.py sends them: shapes and
// per-record validation. Pure (no DB). Batches: claude-model.ts. Tables: migration 032.

export const SURFACES = ['cli', 'desktop', 'remote', 'phone', 'headless', 'unknown'] as const;
export const EVENT_KINDS = [
  'prompt',
  'bash',
  'edit',
  'agent',
  'skill',
  'mcp',
  'git',
  'pr',
  'compact',
  'summary',
  'error',
] as const;

const MAX_TEXT = 4000;
const MAX_FILES = 200;
const MAX_JSON = 32_000;

export interface SessionInput {
  session_id: string;
  surface: (typeof SURFACES)[number];
  cwd: string | null;
  git_remote: string | null;
  git_branch: string | null;
  title: string | null;
  started_at: string;
  last_at: string;
  active_ms: number;
  prompts_n: number;
  tool_calls_n: number;
  tool_errors_n: number;
  compactions_n: number;
  tools: Record<string, number>;
  skills: Record<string, number>;
  subagents: Record<string, number>;
  mcp: Record<string, number>;
  tokens: Record<string, unknown>;
  cost_usd: number | null;
  lines_added: number | null;
  lines_removed: number | null;
  prs: unknown[];
  pushes: string[];
  files_edited: string[];
  entrypoint: string | null;
  version: string | null;
}

export interface EventInput {
  session_id: string;
  uuid: string;
  ts: string;
  kind: (typeof EVENT_KINDS)[number];
  text: string;
  detail: Record<string, unknown>;
}

type Rec = Record<string, unknown>;
export const isRec = (v: unknown): v is Rec => !!v && typeof v === 'object' && !Array.isArray(v);
export const text = (v: unknown, max = 300): string | null =>
  typeof v === 'string' && v.trim() ? v.trim().slice(0, max) : null;
const count = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? Math.round(v) : 0);
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const ts = (v: unknown): string | null => (typeof v === 'string' && !Number.isNaN(Date.parse(v)) ? v : null);
const small = <T>(v: T): T | null => (JSON.stringify(v).length <= MAX_JSON ? v : null);

function counters(v: unknown): Record<string, number> {
  if (!isRec(v)) return {};
  return Object.fromEntries(
    Object.entries(v)
      .filter(([k]) => k.length <= 200)
      .map(([k, n]) => [k, count(n)]),
  );
}

function strings(v: unknown, max: number, len = 500): string[] {
  return Array.isArray(v)
    ? v
        .filter((s): s is string => typeof s === 'string')
        .slice(-max)
        .map((s) => s.slice(0, len))
    : [];
}

export function parseSession(v: unknown): SessionInput | string {
  if (!isRec(v)) return 'not an object';
  const id = text(v.session_id, 64);
  if (!id) return 'invalid session_id';
  const started = ts(v.started_at);
  const last = ts(v.last_at);
  if (!started || !last) return 'invalid started_at/last_at';
  const surface = SURFACES.find((s) => s === v.surface) ?? 'unknown';
  return {
    session_id: id,
    surface,
    cwd: text(v.cwd, 500),
    git_remote: text(v.git_remote, 200),
    git_branch: text(v.git_branch, 200),
    title: text(v.title, 300),
    started_at: started,
    last_at: last,
    active_ms: count(v.active_ms),
    prompts_n: count(v.prompts_n),
    tool_calls_n: count(v.tool_calls_n),
    tool_errors_n: count(v.tool_errors_n),
    compactions_n: count(v.compactions_n),
    tools: counters(v.tools),
    skills: counters(v.skills),
    subagents: counters(v.subagents),
    mcp: counters(v.mcp),
    tokens: (isRec(v.tokens) && small(v.tokens)) || {},
    cost_usd: num(v.cost_usd),
    lines_added: num(v.lines_added),
    lines_removed: num(v.lines_removed),
    prs: (Array.isArray(v.prs) && small(v.prs.slice(0, 100))) || [],
    pushes: strings(v.pushes, 100, 200),
    files_edited: strings(v.files_edited, MAX_FILES),
    entrypoint: text(v.entrypoint, 40),
    version: text(v.version, 40),
  };
}

export function parseEvent(v: unknown): EventInput | string {
  if (!isRec(v)) return 'not an object';
  const sid = text(v.session_id, 64);
  const uuid = text(v.uuid, 300);
  const at = ts(v.ts);
  const kind = EVENT_KINDS.find((k) => k === v.kind);
  if (!sid || !uuid || !at) return 'invalid session_id/uuid/ts';
  if (!kind) return 'invalid kind';
  return {
    session_id: sid,
    uuid,
    ts: at,
    kind,
    text: typeof v.text === 'string' ? v.text.slice(0, MAX_TEXT) : '',
    detail: (isRec(v.detail) && small(v.detail)) || {},
  };
}
