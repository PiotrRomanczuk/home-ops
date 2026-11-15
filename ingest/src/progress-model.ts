// Contract for POST /api/progress/signals and the shape of GET /api/progress.
// Pure (no DB) so it is unit-testable. Table: migration 027; routine runs
// come from unit_runs (026).

export const SIGNALS = [
  'commits',
  'pr_opened',
  'pr_merged',
  'deploys',
  'ci_ok',
  'ci_failed',
  'tasks_done',
  'tasks_added',
] as const;
export type Signal = (typeof SIGNALS)[number];
/** What counts as the project actually moving (routines and CI don't). */
export const MOVEMENT: Signal[] = ['commits', 'pr_merged', 'deploys', 'tasks_done'];
export const STALL_DAYS = 14;

const MAX_ROWS = 20_000;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export interface SignalRow {
  project_slug: string;
  day: string;
  signal: Signal;
  n: number;
}

export interface SignalsBody {
  rows: SignalRow[];
  /** Present → replace this window for these projects × signals; absent → add. */
  replace: { from: string; to: string; projects: string[]; signals: Signal[] } | null;
}

type Rec = Record<string, unknown>;
const isRec = (v: unknown): v is Rec => !!v && typeof v === 'object' && !Array.isArray(v);
const isSignal = (v: unknown): v is Signal => typeof v === 'string' && (SIGNALS as readonly string[]).includes(v);
const slugOk = (v: unknown): v is string => typeof v === 'string' && v.length > 0 && v.length <= 64;

export function parseSignalsBody(body: unknown): SignalsBody | string {
  if (!isRec(body) || !Array.isArray(body.rows)) return 'rows must be an array';
  if (body.rows.length > MAX_ROWS) return `at most ${MAX_ROWS} rows`;
  const rows: SignalRow[] = [];
  for (const [i, r] of body.rows.entries()) {
    if (!isRec(r) || !slugOk(r.project_slug)) return `row ${i}: invalid project_slug`;
    if (typeof r.day !== 'string' || !DATE_RE.test(r.day)) return `row ${i}: invalid day`;
    if (!isSignal(r.signal)) return `row ${i}: invalid signal`;
    if (typeof r.n !== 'number' || !Number.isInteger(r.n) || r.n < 0) return `row ${i}: invalid n`;
    rows.push({ project_slug: r.project_slug, day: r.day, signal: r.signal, n: r.n });
  }
  if (body.replace == null) return { rows, replace: null };
  const rp = body.replace;
  if (!isRec(rp) || typeof rp.from !== 'string' || typeof rp.to !== 'string') return 'replace needs from/to';
  const from: string = rp.from;
  const to: string = rp.to;
  if (!DATE_RE.test(from) || !DATE_RE.test(to) || from > to) return 'replace: invalid window';
  if (!Array.isArray(rp.projects) || !rp.projects.every(slugOk)) return 'replace: invalid projects';
  if (!Array.isArray(rp.signals) || !rp.signals.length || !rp.signals.every(isSignal))
    return 'replace: invalid signals';
  const projects: string[] = rp.projects;
  const signals: Signal[] = rp.signals;
  const outside = rows.find((r) => r.day < from || r.day > to || !signals.includes(r.signal));
  if (outside) return 'replace: a row falls outside the replaced window/signals';
  return { rows, replace: { from, to, projects, signals } };
}

export type Series = Record<Signal | 'runs_ok' | 'runs_failed', number[]>;

export interface ProgressProject {
  slug: string;
  title: string;
  status: string | null;
  health: string | null;
  verdict: string | null;
  ci: unknown;
  last_deploy_at: string | null;
  last_moved: string | null;
  days_still: number | null;
  stalled: boolean;
  series: Series;
}

export interface ProgressInput {
  weeks: string[];
  today: string;
  projects: {
    slug: string;
    title: string | null;
    status: string | null;
    health: string | null;
    verdict: string | null;
    ci: unknown;
    last_deploy_at: string | null;
  }[];
  signals: { project_slug: string; week: string; signal: string; n: number }[];
  runs: { project_slug: string; week: string; ok: number; failed: number }[];
  lastMoved: { project_slug: string; last_moved: string }[];
}

const KEYS = [...SIGNALS, 'runs_ok', 'runs_failed'] as const;
const ACTIVE = new Set(['hot', 'warm']);
const STATUS_ORDER: Record<string, number> = { hot: 0, warm: 1, stalled: 2, dormant: 3 };

function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000);
}

/** Rows from SQL → one entry per project that is hot/warm or moved in the window. */
export function buildProgress(input: ProgressInput): { weeks: string[]; projects: ProgressProject[] } {
  const col = new Map(input.weeks.map((w, i) => [w, i]));
  const empty = (): Series => Object.fromEntries(KEYS.map((k) => [k, input.weeks.map(() => 0)])) as Series;
  const series = new Map<string, Series>();
  const bump = (slug: string, key: keyof Series, week: string, n: number) => {
    const i = col.get(week);
    if (i === undefined) return;
    const s = series.get(slug) ?? empty();
    series.set(slug, s);
    s[key][i] = (s[key][i] ?? 0) + Number(n);
  };
  for (const s of input.signals) if (isSignal(s.signal)) bump(s.project_slug, s.signal, s.week, s.n);
  for (const r of input.runs) {
    bump(r.project_slug, 'runs_ok', r.week, r.ok);
    bump(r.project_slug, 'runs_failed', r.week, r.failed);
  }
  const moved = new Map(input.lastMoved.map((m) => [m.project_slug, m.last_moved]));
  const projects = input.projects
    .filter((p) => ACTIVE.has(p.status ?? '') || series.has(p.slug))
    .map((p) => {
      const last = moved.get(p.slug) ?? null;
      const still = last ? daysBetween(last, input.today) : null;
      return {
        slug: p.slug,
        title: p.title || p.slug,
        status: p.status,
        health: p.health,
        verdict: p.verdict,
        ci: p.ci ?? null,
        last_deploy_at: p.last_deploy_at,
        last_moved: last,
        days_still: still,
        stalled: p.status === 'hot' && (still === null || still > STALL_DAYS),
        series: series.get(p.slug) ?? empty(),
      };
    });
  const activity = (p: ProgressProject) => MOVEMENT.reduce((n, k) => n + p.series[k].reduce((a, b) => a + b, 0), 0);
  projects.sort(
    (a, b) =>
      (STATUS_ORDER[a.status ?? ''] ?? 9) - (STATUS_ORDER[b.status ?? ''] ?? 9) ||
      activity(b) - activity(a) ||
      a.slug.localeCompare(b.slug),
  );
  return { weeks: input.weeks, projects };
}
