---
created: 2026-06-07
updated: 2026-06-07
---

# home-ops — project context

> Read this file first when starting any work on home-ops. It's the
> single source of truth for what the project *is*. Operational TODOs
> live in `ROADMAP.md`. UI-design specifics live in `DESIGN_BRIEF.md`.
> Architectural decisions live in `docs/adr/`.

---

## What home-ops is

A personal observability + automation stack running on a 3-host home
network behind Tailscale. Three pillars, all sitting on a shared
Postgres on `uwh`:

1. **Centralized structured logs** (`host_logs`) — every host runs a
   small Python agent that tails journald, docker, app, and system
   logs, normalizes them to a single JSON shape, and POSTs them to
   the ingest API. Single timeline across all hosts, with structured
   `data` jsonb for cross-event correlation.
2. **GPU job queue** (`gpu_jobs`) — Postgres-backed work queue for
   GPU-bound tasks. A scheduler on the Windows host claims jobs,
   pauses automatically when gaming is detected, resumes when idle
   returns. First production workload: embedding Polish-language
   Pracuj job offers with `bge-m3` for semantic search.
3. **Host metrics + attribution** (`host_metrics`) — periodic samples
   of CPU/mem/disk/network/GPU per host, with process-level
   attribution in `data` jsonb. The "what's eating my resources, and
   when does utilization spike?" layer, joinable with logs for
   correlation that no single existing tool provides.

All three live in the same Postgres database (`home_ops`) on uwh.
This is deliberate — the cross-pillar joins are the project's reason
to exist.

## The three hosts

| Host | Role | Hardware | Always-on? |
| --- | --- | --- | --- |
| **uwh** (`piotr-hp-elitedesk`) | The server. Ingest API + Postgres + log-shipping agent + (eventually) pg-backup timer | HP EliteDesk, i7-6700K, 31 GB RAM, no dGPU | Yes |
| **wfh** (`windows-pc`) | The GPU box. Ollama backend + Ollama-log watcher + GPU job scheduler | i7-6700K, 67 GB RAM, AMD Radeon RX 7700 XT (12 GB VRAM) | Yes |
| **rpi** (`pi`) | Monitoring + low-power services. Kuma + Beszel today; (planned) log-shipping agent, Telegram notification bot | Pi 5, 8 GB RAM, 29 GB SD | Yes, lowest power |
| **mac** | Workstation, dev environment, launchd-scheduled producers (e.g. Pracuj embedding queue producer) | M-series, varies | No (sleeps overnight) |

Network: `192.168.1.0/24`, Tailscale tailnet
`p.romanczuk@gmail.com` (`*.tail266853.ts.net`). Pi advertises NAS
(`192.168.1.25/32`) for off-LAN access.

Full inventory: `~/Desktop/MainCV/infrastructure/HOSTS.md` (also
`github.com/PiotrRomanczuk/home-infra-docs`).

## The user

Single user — solo developer. Technical, prefers terminal aesthetics,
monospace everything. Uses the stack in three modes:

- **Desktop (Mac, 1440+)** during deep work. Wants extreme density —
  see 30+ events without scrolling.
- **iPhone (390px)** during commute / glance-checks. Wants
  glanceable state + drill-down without losing columns.
- **Pinned home-screen tab** for ambient awareness. "Anything red?"

No teams, no permissions, no audit/compliance. The whole stack is
behind Tailscale identity. The viewer adds a `LOGS_PASSWORD` cookie
gate on top.

## Data model — `host_logs`

```ts
{
  id:           number;     // monotonic
  ts:           string;     // ISO 8601 — source timestamp
  ingested_at:  string;     // when home-ops received it. lag = ingested_at - ts
  host:         string;     // 'uwh' | 'wfh' | 'rpi' | 'mac' | future hosts
  source:       string;     // see "source naming" below
  level:        'debug'|'info'|'warn'|'error'|'fatal';
  message:      string;     // single-line, up to ~8000 chars
  data:         Record<string, unknown>;  // see "well-known data keys" below
}
```

**Source naming** — convention is `<facility>:<name>`:
- `journald:<unit>` — systemd journal (e.g. `journald:cloudflared`, `journald:ssh`)
- `docker:<container-name>` — container stdout/stderr (e.g. `docker:home-ops-ingest-1`)
- `agent:<name>` — agent self-logging (e.g. `agent:uwh-watcher`, `agent:gpu-scheduler`)
- `app:<service>` — first-party app dual-writes (e.g. `app:stano-scraper`, `app:cv-generator`)

**Well-known `data` keys** — agents normalize their source's fields
into these names so cross-source queries work:

| Key | Type | Meaning |
| --- | --- | --- |
| `pid` | int | Process ID |
| `cmd` | string | Process binary/command name |
| `unit` | string | systemd unit (when source isn't `journald:*`) |
| `container` | string | docker container (when source isn't `docker:*`) |
| `trace_id` | string | Cross-service request trace |
| `request_id` | string | Single-HTTP-request lifecycle |
| `job_id` | int | Reference to `gpu_jobs.id` |
| `model` | string | Ollama / embedding model name |
| `peer` | string | Remote IP for HTTP-receiving events |
| `status` | int | HTTP status / exit code |
| `duration_ms` | int | Operation latency, integer ms |

Other keys are fine but only the above are "filterable" semantically
in the viewer.

Volume: 50k–500k rows/day across all hosts. Retention 30 days,
pruned hourly via pg_cron.

## Data model — `gpu_jobs`

```ts
{
  id:           number;
  kind:         'embed' | 'generate' | 'summarise' | string;
  status:       'queued' | 'running' | 'paused' | 'cancelling' | 'cancelled' | 'done' | 'failed';
  priority:     number;     // higher = sooner. Defaults: embed=0, summarise=5, generate=10
  created_at:   string;
  started_at:   string | null;
  finished_at:  string | null;
  attempts:     number;
  worker_host:  string | null;
  last_error:   string | null;
  result:       unknown | null;
  payload:      Record<string, unknown>;
}
```

Status semantics:
- `queued` — waiting for a worker
- `running` — claimed, in progress (worker emits heartbeat events to `host_logs`)
- `paused` — was running, gaming detected, will resume on idle
- `cancelling` — user cancel requested; worker honors on next iteration
- `cancelled` — terminal: user-cancelled
- `done` — terminal: successful
- `failed` — terminal: worker called `/fail` explicitly. Kept forever for postmortem (the 30-day prune only touches `done` rows)

Retention: `done` jobs pruned at 30 days; `failed/cancelled` kept indefinitely.

## Data model — `host_metrics`

```ts
{
  id:            number;
  ts:            string;
  ingested_at:   string;
  host:          string;
  cpu_pct:       number;        // 0-100, across all cores
  cpu_load_1:    number;        // 1-min load average
  mem_pct:       number;        // 0-100
  mem_used_mb:   number;
  mem_total_mb:  number;
  swap_pct:      number;
  disk_pct:      number;        // root partition
  net_rx_kbps:   number;
  net_tx_kbps:   number;
  gpu_pct:       number | null; // null on hosts without GPU
  gpu_mem_pct:   number | null;
  gpu_temp_c:    number | null;
  data:          Record<string, unknown>;  // process attribution, container stats, model info
}
```

`data` jsonb holds the attribution — this is the key differentiator
from existing tools (Beszel has time-series but not attribution):

```json
{
  "top_cpu": [
    {"name": "ollama.exe", "pid": 1234, "pct": 45.2},
    {"name": "chrome.exe", "pid": 5678, "pct": 8.1}
  ],
  "top_mem": [
    {"name": "ollama.exe", "pid": 1234, "rss_mb": 9342}
  ],
  "gpu_models_loaded": [
    {"model": "qwen3:14b", "vram_mb": 9200}
  ],
  "docker_containers": [
    {"name": "home-ops-postgres-1", "cpu_pct": 2.1, "mem_mb": 145}
  ]
}
```

Sample rate: every 30 seconds. Volume: ~260k rows/month across 3
hosts. Tiny. Same 30-day retention + pg_cron prune as `host_logs`.

The point isn't pretty charts — Beszel already does that. The point
is **queryable correlation**:

```sql
-- "Errors correlated with resource pressure"
SELECT
  l.message, l.ts, m.cpu_pct, m.mem_pct,
  m.data->'top_cpu'->0 AS hottest_process
FROM host_logs l
JOIN LATERAL (
  SELECT * FROM host_metrics
  WHERE host = l.host AND ts BETWEEN l.ts - '30 sec' AND l.ts + '30 sec'
  ORDER BY abs(extract(epoch FROM ts - l.ts)) LIMIT 1
) m ON true
WHERE l.level IN ('error','fatal') AND l.ts > now() - '24 hours'::interval;
```

The above query is a multi-week setup in Grafana+Prometheus+Loki and
~30 seconds of SQL in home-ops because both streams are in the same DB.

## Core use cases (priority order)

Anything not on this list is **not** a current scope concern.

1. **"Did anything break in the last hour?"** → filter `level ≥ warn`, last 60min, skim red rows. Many times a day, often from phone. <5 seconds end-to-end.
2. **"Tail this container's logs."** → pick source, enable tail, watch the stream. Deploy/debug sessions.
3. **"What happened at 14:32 when X broke?"** → time-range + host filter → expand row → use correlation keys (`pid`, `trace_id`) to find related events across sources.
4. **"What's the queue doing?"** → Jobs view: queued/running/paused/done/failed counts + list. Inspect failed jobs' `last_error` and `payload`. Cancel mid-flight if needed.
5. **"Is the stack itself healthy?"** → persistent indicator: ingest API health, per-host last-event lag (so dead agents are visible), disk pct.
6. **"Are my hosts being used well?"** → metrics view: per-host CPU/mem/GPU over time, top-N process attribution, queries like "uwh weekly avg CPU" or "wfh idle-GPU hours when not gaming."

## Future-facing — what home-ops potentially is

The three pillars (logs, jobs, metrics) on a shared Postgres are the
substrate for a personal-life coordinator. None of these is current
scope, but the design must not foreclose them:

- **Cross-project domain events**: each project (Stano, guitar-crm,
  Pracuj scraper, CV generator) dual-writes lifecycle events
  (`scrape_started`, `deploy_succeeded`, `application_submitted`,
  `lesson_recorded`) with source prefix `app:*`. The viewer becomes a
  single timeline across "what was I doing on day X."
- **AI-assisted background tasks**: queue kinds like `summarise_emails`,
  `transcribe_voicenote`, `score_offer_against_cv`. Each is a new
  `kind` + handler file; inherits gaming-pause, retries, priority.
- **Recurring scheduled work via pg_cron**: not just retention. Friday
  morning generates a weekly review from the week's `host_logs`;
  Sunday queues "pick top 5 unapplied Pracuj offers" generate jobs;
  Monday auto-cleans branches per `~/.claude/rules/branch-hygiene.md`.
- **Personal embeddings**: `pracuj_offer_embeddings`-pattern but for
  notes, ideas, lesson plans. Semantic search across "everything I've
  thought about" becomes a SQL query.
- **Infrastructure optimization analytics**: `host_metrics` + `host_logs`
  joins answer "is uwh underutilized? could it host more workloads?"
  or "what's the actual cost of running Ollama always-loaded?".

Design implications:
- Keep `data` jsonb schema-less (well-known keys only as convention).
- Keep all three pillars in `home_ops` Postgres.
- Keep `gpu_jobs.kind` generic — any string + handler file.
- Don't bring in Loki/Prometheus/ELK/Grafana (see ADR
  `docs/adr/2026-06-07-no-grafana.md`). The custom viewer is the
  identity; don't dilute it.

## Aesthetic identity

- Dark theme, monospace everything (`JetBrains Mono` / `ui-monospace`).
- High density — desktop views fit ~40 rows above the fold at 1440×900.
- Color sparingly: accent `#58a6ff` for active state; severity colors
  for level column only.
- Look at `lnav`, `dozzle`, `vector top`, GitHub Dark for direction.
- Anti-references: Datadog, Grafana, Material Design, generic admin panels.
- Keyboard-first: `/` to focus search, `j/k` to navigate rows, `f` for
  follow toggle, `1-5` for level threshold.
- This is a tool for **one technical user**, not a dashboard for execs.

## Implementation constraints (current)

- **No Loki/Prometheus/ELK/Grafana.** See `docs/adr/2026-06-07-no-grafana.md`.
- **Auth model**: shared `INGEST_TOKEN` for machines, `LOGS_PASSWORD`
  cookie for the viewer. Per-host tokens explicitly rejected (see
  improvement plan Q16).
- **Stack survives Stano outages** — separate Postgres, separate
  process tree, separate UI. Only crossing point is `app:stano-scraper`
  events.
- **Deploy via `git pull`** on uwh; no CI-driven deploy yet
  (`~/.claude/plans/analyze-this-folder-and-curious-shamir.md` Q3).
- **All migrations idempotent and tracked** via `schema_migrations`
  table + `ops/uwh/apply-migrations.sh` (per Q20).
- **Mobile parity**: every desktop operation works on a 390-wide phone.

## Repos + canonical paths

- **Code**: `~/Desktop/MainCV/home-ops/` and `github.com/PiotrRomanczuk/home-ops` (private)
- **Infrastructure docs**: `~/Desktop/MainCV/infrastructure/` and `github.com/PiotrRomanczuk/home-infra-docs` (private)
- **Improvement plan + decisions**: `~/.claude/plans/analyze-this-folder-and-curious-shamir.md`
- **Operational TODO**: `~/Desktop/MainCV/home-ops/ROADMAP.md`
- **Architectural decisions**: `~/Desktop/MainCV/home-ops/docs/adr/`
- **UI design brief**: `~/Desktop/MainCV/home-ops/docs/DESIGN_BRIEF.md`
- **Host inventory**: `~/Desktop/MainCV/infrastructure/HOSTS.md`
