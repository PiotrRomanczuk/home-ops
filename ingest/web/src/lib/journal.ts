// "Dziennik" — one Warsaw day of the Mac: GET /api/journal/day (rollup) and
// GET /api/claude/events (one session's prompts, commands, edits). Shapes come
// from ingest/src/journal-model.ts and claude-sql.ts (migration 032). Pure
// helpers below are unit-tested; the components only render.

import { getJson } from './api';

export interface HourRow {
  hour: number;
  samples: number;
  seconds: number;
  cpu?: number | null;
  gpu?: number | null;
  mem_max?: number | null;
  rx_mb?: number | null;
  tx_mb?: number | null;
}

export interface JournalSession {
  host: string;
  session_id: string;
  title: string | null;
  project_slug: string | null;
  surface: string;
  cwd: string | null;
  git_branch: string | null;
  cost_usd: string | number | null;
  prs: { url: string; number: number | null }[];
  live_status: string | null;
  first_ts: string;
  last_ts: string;
  prompts_day: number;
  errors_day: number;
  actions_day: number;
  active_min: number;
}

export interface ProcRun {
  name: string;
  cmd: string;
  reason: 'claude' | 'cpu' | 'net' | string;
  session_id: string | null;
  session_name: string | null;
  started: string | null;
  ended: string | null;
  duration_s: number | null;
  cpu_s: number | null;
  net_mb: number;
}

export interface JournalDay {
  host: string;
  day: string;
  awake_min: number;
  hours: HourRow[];
  apps: {
    cpu: { name: string; cpu_s: number }[];
    net: { name: string; mb: number }[];
    mem: { name: string; rss_mb: number }[];
  };
  procs: ProcRun[];
  claude: {
    totals: { sessions: number; prompts: number; errors: number; active_min: number };
    by_project: { project_slug: string | null; sessions: number; prompts: number; active_min: number }[];
    sessions: JournalSession[];
    prs: string[];
  };
  journal: { summary_md: string | null; model: string | null; generated_at: string } | null;
}

export interface ClaudeEvent {
  uuid: string;
  ts: string;
  kind: string;
  text: string;
  detail: Record<string, unknown>;
}

export const fetchJournal = (day: string) => getJson<JournalDay>(`/api/journal/day?host=mac&day=${day}`);
export const fetchEvents = (host: string, session: string) =>
  getJson<{ events: ClaudeEvent[] }>(
    `/api/claude/events?host=${encodeURIComponent(host)}&session=${encodeURIComponent(session)}`,
  );

const WARSAW_DAY = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Warsaw' });
const WARSAW_HM = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Europe/Warsaw',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

export const today = (now = new Date()) => WARSAW_DAY.format(now);

export function shiftDay(day: string, by: number): string {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + by);
  return d.toISOString().slice(0, 10);
}

/** Minutes since Warsaw midnight (0–1440) of an instant. */
export function minuteOfDay(iso: string): number {
  const [h, m] = WARSAW_HM.format(new Date(iso)).split(':').map(Number);
  return (h ?? 0) * 60 + (m ?? 0);
}

export const clock = (iso: string | null) => (iso ? WARSAW_HM.format(new Date(iso)) : '—');

/** Clock time, prefixed with "dd.mm" when the instant falls on another Warsaw day than `day`. */
export function clockOn(iso: string | null, day: string): string {
  if (!iso) return '—';
  const d = WARSAW_DAY.format(new Date(iso));
  return d === day ? clock(iso) : `${d.slice(8, 10)}.${d.slice(5, 7)} ${clock(iso)}`;
}

/** Seconds as "45 s" / "12 min" / "1 h 05 min". */
export const fmtSec = (s: number) => (s < 60 ? `${Math.round(s)} s` : fmtMin(s / 60));

export function fmtMin(min: number): string {
  const m = Math.round(min);
  return m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min` : `${m} min`;
}

export interface Lane {
  project: string;
  activeMin: number;
  segments: { session: JournalSession; from: number; to: number }[];
}

/** Sessions grouped into one lane per project (busiest first), each a [from, to] span in minutes. */
export function lanes(sessions: JournalSession[]): Lane[] {
  const by = new Map<string, Lane>();
  for (const s of sessions) {
    const project = s.project_slug ?? '(bez projektu)';
    const lane = by.get(project) ?? { project, activeMin: 0, segments: [] };
    const from = minuteOfDay(s.first_ts);
    lane.segments.push({ session: s, from, to: Math.max(from + 5, minuteOfDay(s.last_ts)) });
    lane.activeMin += s.active_min;
    by.set(project, lane);
  }
  return [...by.values()].sort((a, b) => b.activeMin - a.activeMin || a.project.localeCompare(b.project));
}

/** Summary markdown → sections of plain lines ("## Dzień", "## Co dalej"). */
export function summarySections(md: string | null): { title: string; lines: string[] }[] {
  const out: { title: string; lines: string[] }[] = [];
  for (const raw of (md ?? '').split('\n')) {
    const line = raw.trim();
    if (line.startsWith('#')) out.push({ title: line.replace(/^#+\s*/, ''), lines: [] });
    else if (line) {
      if (!out.length) out.push({ title: 'Podsumowanie', lines: [] });
      out[out.length - 1]?.lines.push(line.replace(/^[-*]\s+/, '').replace(/\*\*/g, ''));
    }
  }
  return out;
}
