// Shapes of GET /api/journal/day and GET /api/claude/events
// (ingest/src/journal-model.ts, claude-sql.ts, migration 032).

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

export interface Lane {
  project: string;
  activeMin: number;
  segments: { session: JournalSession; from: number; to: number }[];
}
