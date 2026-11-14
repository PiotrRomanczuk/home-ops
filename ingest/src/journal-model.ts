// Shape of GET /api/journal/day and the contract of POST /api/journal. Pure
// (no DB): the route runs journal-sql.ts and hands the rows here. The same
// shape is what agents/mac/day_prompt.py reads and what day_journal.rollup keeps.

type Rec = Record<string, unknown>;
const isRec = (v: unknown): v is Rec => !!v && typeof v === 'object' && !Array.isArray(v);
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const MAX_ROLLUP = 256_000;
const MAX_SUMMARY = 20_000;

export interface HourRow {
  hour: number;
  samples: number;
  seconds: number;
  cpu: number | null;
  gpu: number | null;
  mem_max: number | null;
  rx_mb: number | null;
  tx_mb: number | null;
}

export interface JournalInput {
  host: string;
  day: string;
  hours: HourRow[];
  apps: { kind: string; name: string; value: number }[];
  procs: { ts: string | Date; data: Rec }[];
  sessions: Rec[];
  totals: Rec | undefined;
  byProject: Rec[];
  prs: { url: string }[];
  journal: Rec | undefined;
}

export interface ProcRun {
  name: unknown;
  cmd: unknown;
  reason: unknown;
  session_id: unknown;
  session_name: unknown;
  started: string | null;
  ended: string | null;
  duration_s: number | null;
  cpu_s: number | null;
  net_mb: number;
}

const iso = (epoch: unknown): string | null =>
  typeof epoch === 'number' && Number.isFinite(epoch) ? new Date(epoch * 1000).toISOString() : null;

/** "proc start" / "proc stop" rows → one entry per process run (still-running ones have ended null). */
export function mergeProcs(rows: { ts: string | Date; data: Rec }[]): ProcRun[] {
  const runs = new Map<string, ProcRun>();
  for (const { ts, data } of rows) {
    const at = ts instanceof Date ? ts.toISOString() : String(ts);
    const key = `${data.pid}:${data.started}`;
    const run = runs.get(key) ?? {
      name: data.name,
      cmd: data.cmd,
      reason: data.reason,
      session_id: data.session_id ?? null,
      session_name: data.session_name ?? null,
      started: iso(data.started) ?? at,
      ended: null,
      duration_s: null,
      cpu_s: null,
      net_mb: 0,
    };
    run.net_mb = Math.round((Number(data.net_bytes) || 0) / 104_857.6) / 10;
    run.cpu_s = typeof data.cpu_s === 'number' ? Math.round(data.cpu_s) : run.cpu_s;
    if (data.event === 'stop') {
      run.ended = at;
      run.duration_s = typeof data.duration_s === 'number' ? data.duration_s : null;
    }
    runs.set(key, run);
  }
  return [...runs.values()].sort((a, b) => String(a.started).localeCompare(String(b.started)));
}

export function buildJournal(input: JournalInput) {
  const byHour = new Map(input.hours.map((h) => [h.hour, h]));
  const hours = Array.from({ length: 24 }, (_, hour) => byHour.get(hour) ?? { hour, samples: 0, seconds: 0 });
  const apps = (kind: string, n = 10) =>
    input.apps
      .filter((a) => a.kind === kind && a.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, n);
  return {
    host: input.host,
    day: input.day,
    awake_min: Math.round(input.hours.reduce((s, h) => s + (h.seconds || 0), 0) / 60),
    hours,
    apps: {
      cpu: apps('cpu').map((a) => ({ name: a.name, cpu_s: a.value })),
      net: apps('net').map((a) => ({ name: a.name, mb: a.value })),
      mem: apps('mem').map((a) => ({ name: a.name, rss_mb: a.value })),
    },
    procs: mergeProcs(input.procs),
    claude: {
      totals: input.totals ?? { sessions: 0, prompts: 0, errors: 0, active_min: 0 },
      by_project: input.byProject,
      sessions: input.sessions,
      prs: input.prs.map((p) => p.url),
    },
    journal: input.journal ?? null,
  };
}

export interface JournalPost {
  host: string;
  day: string;
  rollup: Rec;
  summary_md: string | null;
  model: string | null;
}

export function parseJournalPost(body: unknown): JournalPost | string {
  if (!isRec(body)) return 'body must be an object';
  const host = typeof body.host === 'string' && body.host.trim() ? body.host.trim().slice(0, 63) : null;
  if (!host) return 'invalid host';
  if (typeof body.day !== 'string' || !DATE_RE.test(body.day)) return 'invalid day';
  if (!isRec(body.rollup)) return 'rollup must be an object';
  if (JSON.stringify(body.rollup).length > MAX_ROLLUP) return 'rollup too large';
  const summary = typeof body.summary_md === 'string' ? body.summary_md.slice(0, MAX_SUMMARY) : null;
  const model = typeof body.model === 'string' ? body.model.slice(0, 100) : null;
  return { host, day: body.day, rollup: body.rollup, summary_md: summary, model };
}
