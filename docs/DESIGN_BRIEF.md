---
created: 2026-06-07
updated: 2026-06-07
---

# home-ops — UI design brief

> Paste this into a fresh Claude Code session (ideally one that has access
> to the `frontend-design` or `interface-design` skill) and ask it to
> deliver the design. The brief below is the prompt — read everything,
> then produce the deliverables enumerated at the bottom.

---

## Role

You're a senior frontend designer + engineer. You're going to design a
**high-density, terminal-aesthetic observability UI** for a personal-scale
log-stream + job-queue tool. The output is HTML+CSS mockups (no framework
required; Tailwind via CDN is fine) plus a short rationale per screen.

Do NOT produce generic admin-panel-with-sidebars-and-stat-cards work.
This is a tool for one technical user who reads logs all day; the design
should reflect that.

---

## What home-ops is

home-ops is a centralized observability stack running on a 3-host home
network behind Tailscale:

- **uwh** — Linux server (Ubuntu 25.10, HP EliteDesk, 31 GB RAM). Runs the
  ingest API + Postgres + a log-shipping agent.
- **wfh** — Windows desktop with the GPU (Radeon RX 7700 XT, 12 GB VRAM).
  Runs Ollama, an Ollama-log watcher, and the GPU job scheduler.
- **rpi** — Raspberry Pi 5 (always-on, low-power). Runs Kuma + Beszel
  monitoring, will eventually run a log watcher and (planned) a Telegram
  notification bot.

It does two things:

1. **Centralized structured logs** — every host runs a small Python agent
   that tails journald / docker / Ollama / app logs, normalizes them to a
   single JSON shape, and POSTs them to the ingest API. They land in a
   Postgres table with full structured metadata.
2. **GPU job queue** — a `gpu_jobs` table on Postgres holds work for the
   Windows GPU. A scheduler on wfh claims jobs, runs them, pauses
   automatically when the user starts gaming, resumes when idle returns.
   First real workload (deferred): embedding Polish-language Pracuj job
   offers using `bge-m3` for semantic search.

The viewer you're designing is the only UI surface for both.

**Future-facing**: home-ops is intended to grow into a personal-life
coordinator — cross-project domain events ("application submitted",
"deploy succeeded"), recurring AI-assisted background tasks, personal
embeddings. The UI should not foreclose this — but only the logs + jobs
views need to ship now.

---

## The user

Solo developer (Piotr). Technical, prefers terminal aesthetics, has been
using a custom-built monospace dark viewer until now. Uses the tool in
three modes:

- **Desktop** (Mac, Safari/Chrome, 1440×900+ window). Primary mode during
  deep work. Wants extreme information density — see 30+ events without
  scrolling.
- **iPhone** (portrait Safari, 390×844). Secondary mode during commute /
  between meetings. Wants glanceable state + ability to drill down without
  the desktop columns disappearing.
- **Pinned-to-home-screen tab**. Glanced at periodically just to know
  "anything red?".

Single user. No teams, no permission system. The whole tool sits behind
Tailscale identity already.

---

## Data model

### `host_logs` — the event stream

```ts
{
  id:           number;          // monotonic
  ts:           string;          // ISO 8601 — source timestamp (when the host emitted it)
  ingested_at:  string;          // when home-ops received it. ingested_at - ts = "agent lag"
  host:         string;          // 'uwh' | 'wfh' | 'rpi' | 'mac' | future hosts
  source:       string;          // 'journald:<unit>' | 'docker:<container>' | 'agent:<name>' | 'app:<service>'
  level:        'debug'|'info'|'warn'|'error'|'fatal';
  message:      string;          // up to ~8000 chars, usually single-line
  data:         Record<string, unknown>;  // structured context — see "well-known keys" below
}
```

**Well-known `data` keys** (convention — agents normalize their source's
fields into these names):

| Key | Meaning |
| --- | --- |
| `pid` | Process ID |
| `cmd` | Process binary / command name |
| `unit` | systemd unit (when source isn't `journald:*`) |
| `container` | docker container name (when source isn't `docker:*`) |
| `trace_id` | Cross-service request trace |
| `request_id` | Single-HTTP-request lifecycle |
| `job_id` | Reference to `gpu_jobs.id` |
| `model` | Ollama / embedding model name |
| `peer` | Remote IP for HTTP-receiving events |
| `status` | HTTP status code / exit code |
| `duration_ms` | Operation latency (integer ms) |

Any other keys are fine but only the above are "filterable" semantically
in the UI.

### Example rows

```
2026-06-07 21:08:41Z | uwh | docker:home-ops-ingest-1 | INFO  | --> GET /api/logs?level_min=info&since_min=60        | {duration_ms: 1, status: 200, request_id: 'abc'}
2026-06-07 21:08:39Z | wfh | agent:gpu-scheduler      | INFO  | gaming detected → workload paused                     | {reason: 'game-exe (eldenring.exe)', avg_gpu_util: 78.3}
2026-06-07 21:07:12Z | uwh | journald:cloudflared     | ERROR | Connection terminated error="accept stream listener"  | {pid: 31254, connection: '222a5e24-…'}
2026-06-07 21:05:33Z | wfh | app:ollama-server        | WARN  | model load failed, retrying                           | {model: 'qwen3:14b', attempt: 2, peer: '127.0.0.1'}
2026-06-07 21:04:11Z | rpi | docker:uptime-kuma       | INFO  | Heartbeat ping ok                                     | {monitor_id: 12, duration_ms: 240}
2026-06-07 21:03:55Z | wfh | agent:gpu-scheduler      | INFO  | job 47 done                                           | {job_id: 47, kind: 'embed', duration_ms: 8230}
```

**Volume**: 50k–500k rows/day across all hosts. Retention 30 days, prune
hourly. At any time the table has ~1–15M rows.

### `gpu_jobs` — the queue

```ts
{
  id:           number;
  kind:         'embed' | 'generate' | 'summarise' | string;
  status:       'queued' | 'running' | 'paused' | 'cancelling' | 'cancelled' | 'done' | 'failed';
  priority:     number;          // higher = sooner; defaults: embed=0, summarise=5, generate=10
  created_at:   string;
  started_at:   string | null;
  finished_at:  string | null;
  attempts:     number;
  worker_host:  string | null;   // e.g. 'wfh'
  last_error:   string | null;
  result:       unknown | null;
  payload:      Record<string, unknown>;
}
```

Status semantics:
- `queued` — waiting for a worker
- `running` — claimed, in progress (worker emits heartbeat events to `host_logs`)
- `paused` — was running, gaming was detected, will resume when idle
- `cancelling` — user requested cancel via UI; worker will honor on next iteration
- `cancelled` — terminal: user-cancelled, won't run again
- `done` — terminal: successful
- `failed` — terminal: worker called `/fail` explicitly; kept forever for postmortem

---

## Core use cases (priority order)

1. **"Did anything break in the last hour?"** — Open viewer → filter `level ≥ warn` across all hosts, last 60 min → skim for red rows. Done multiple times a day, often from phone. Should take <5 seconds end-to-end.
2. **"Tail this container's logs."** — Pick a single source → enable tail → watch new events stream in at the top (or bottom — pick a side and commit). Done during deploys + debugging.
3. **"What was happening when X broke at 14:32?"** — Time-range picker → narrow → expand a row to see full `data` → use a correlation key (`pid`, `trace_id`, `request_id`) to find related events across other sources.
4. **"What's the queue doing?"** — Switch to Jobs view → see queued / running / paused / done / failed counts + a list. Inspect a `failed` job's `last_error` and `payload`. Optionally requeue or cancel.
5. **"Is the stack itself healthy?"** — A persistent indicator visible from any view: ingest API health, last-event-from-each-host timestamps (so you know an agent died if its lag exceeds threshold), pgdata disk usage percentile.

Anti-use-cases (deliberately NOT designing for):
- Multi-user permissions, sharing, comments
- Charting / dashboards of "events per minute over time"
- Export to CSV / report generation
- Saved views / personal favorites (URL hash is already shareable)

---

## What exists today (baseline you're replacing)

A working but ugly minimal viewer served by the Hono ingest API:

- Dark theme: bg `#0e1116`, fg `#d0d7de`, accent `#58a6ff`. Level colors:
  debug=gray, info=blue, warn=yellow, error=red, fatal=red-bright.
- Monospace font stack (`JetBrains Mono`, fallback `ui-monospace`).
- Single page: filter bar at the top (host single-select, source
  single-select, level threshold, time window, grep input, tail toggle,
  refresh button, status text, logout).
- Below the bar: a table with columns `[ts, host, source, lvl, message]`.
  Rows are clickable → expands a detail row showing `data` jsonb pretty-printed.
- Live tail: polls `/api/logs?after=<last_id>` every 2 s, prepends new rows.
- DOM cap at 1500 rows.
- URL hash persists filter state (`#host=uwh&source=...`).

What's wrong with it:
- Visually plain; reads like a 2008 phpMyAdmin clone.
- No Jobs view at all (only the Logs side is built).
- No health indicator. Can't tell if an agent is silent because nothing's
  happening or because the agent is dead.
- No correlation affordances — clicking a `pid` in the data jsonb does
  nothing.
- No clear separation of "routine info noise" vs "this is what matters
  right now". The eye has to do all the triage work.
- Mobile is functional but unloved — selects don't render natively well,
  table columns are cramped.
- The 5-column table at desktop density is fine but isn't *distinctive* —
  no graphic identity, no rhythm, no clear hierarchy beyond color.

---

## Hard constraints (non-negotiable)

1. **Dark theme by default**. Light mode optional; same component shapes.
2. **Monospace everything** — body, table cells, labels, buttons, numbers.
   The tool reads like a terminal because that's what it is.
3. **Information density** — desktop view fits ~40 log rows above the
   fold at 1440×900. No card wrappers per row. No oversized padding.
4. **Filter state is a URL fragment** — every state combination
   shareable + reloadable. Current contract: `#host=uwh&source=docker:foo&level_min=warn&since_min=60&grep=oom&tail=0`.
5. **Mobile works for filtering** — every operation that's possible on
   desktop must be possible on a 390-wide phone screen. Slower is OK;
   absent is not. (The current viewer hides filters under 800px width —
   that's already been fixed but the redesign must preserve it.)
6. **Live tail must not jank** — every 2s, append new rows without
   re-layout-thrashing. Virtualized list is fine but not required at
   <2000 rows. Don't fight the browser.
7. **Auth is out of scope** — there's a `/login` page elsewhere with
   `LOGS_PASSWORD`. Your designs assume the user is logged in.
8. **Single binary deliverable** — the existing setup is a Hono server
   serving static files from `ingest/public/`. The redesign should fit
   that or be implementable in a separate Next.js app (Phase C plan)
   without rewriting the data API.

---

## Aesthetic direction

Take the existing minimal dark-monospace aesthetic and **make it
distinct** without abandoning it. Reference points (not to copy):

- **Logs-tool DNA**: `lnav`, `dozzle`, `clog`, `vector top`, `lsof`.
- **Editor DNA**: Pulsar/Atom, the older Sublime Text default, GitHub
  Dark "high contrast" variant.
- **Anti-references**: Datadog, Grafana, anything Material-themed,
  generic "enterprise SaaS" admin panels.

Specific design moves I want to see at least considered:

- **Tabular numerals** with consistent column alignment. Timestamps,
  durations, counters all use them.
- **Small-caps column headers** with subtle letter-spacing. Differentiates
  header from data without making the header heavy.
- **Color sparingly** — accent (~`#58a6ff` or your evolution of it) only
  for active state + interactive affordances. Severity colors only on the
  `level` column + maybe a 4-pixel left border per row for warn+.
- **Time as the primary axis** — toggle between `21:08:41` (HH:MM:SS) and
  `3m ago` (relative). Phone defaults to relative, desktop to absolute.
- **Status density** in the chrome — e.g., a status footer showing
  "uwh: 2s ago • wfh: 8s ago • rpi: 4m ago" with each segment colored
  green/yellow/red by staleness. Always visible. Cheap signal-to-noise.
- **Microinteractions**: pause/resume tail with a single keypress, jump
  level thresholds with `1-5`, focus search with `/`. Keyboard-first feels
  right for this tool. Hint at it (small kbd badges in tooltips).

What NOT to do:
- ❌ Left sidebar / nav rail. There are 2 tabs. A top-tab strip is enough.
- ❌ Hero "summary" cards (total events, error rate sparkline). This is
   a tail, not a dashboard.
- ❌ Heavy iconography. Maybe one icon per nav item + level dots. No
   feature-icon explosion.
- ❌ Modal-on-modal patterns. Detail view should be expand-inline or a
   right-side drawer, not a centered dialog you have to dismiss.
- ❌ Animated transitions over 200ms. This is an operator tool — speed
   matters more than polish.

---

## Deliverables

For each of:

1. **Desktop / Logs (default view)** — filter bar + table + status footer + selected-row drawer/detail.
2. **Desktop / Jobs** — table of `gpu_jobs` with kind/status/priority/created/attempts/last_error + a way to click into a job's full record.
3. **Desktop / Detail view** — what happens when you click a row in Logs. Should include the `data` jsonb pretty-printed with correlation keys (`pid`, `trace_id`, etc.) rendered as clickable chips that re-filter to that value across all sources.
4. **Mobile / Logs** (390×844 portrait) — same use cases, phone-fitted.
5. **Mobile / Jobs** (390×844 portrait).
6. **Mobile / Detail view**.

Produce, for each:
- A **self-contained HTML file** with inline CSS (or CDN Tailwind). Realistic example data baked in (5–10 log rows showing all 5 levels, all 4 hosts; 4–6 jobs showing all 7 statuses).
- **2–4 sentences of rationale** explaining what you optimized for and what tradeoff you made.

Plus one cross-cutting document (max 300 words) covering:

- **The color + typography system you settled on** — named tokens
  (`--bg`, `--bg-elevated`, etc.), font sizes, line-heights, the
  specific monospace stack you picked.
- **The interaction model** — keyboard shortcuts, hover behaviors,
  click vs cmd-click vs right-click semantics.
- **Empty/loading/error states** — what shows when no rows match, when
  ingest is unreachable, when the user has filtered to nothing.

---

## Stretch (optional — but mention which you'd add and why)

- **Saved deep-links as quick chips** — a row of pre-defined filter
  chips above the bar: "warn+ 1h", "uwh errors", "active jobs", "last
  deploy". Click → apply that filter set. Customizable via a small JSON
  in `localStorage`.
- **Correlation chips in row data** — clicking `pid: 31254` in any row's
  data anywhere filters all logs by that pid across hosts. Shows a small
  "▷ 12 events with pid=31254" affordance on hover.
- **Tail direction toggle** — some operators read tail bottom-up
  (terminal-style), others top-down (browser-style). Make it a setting,
  surface the active mode visibly.
- **A "scratch" filter input** that accepts a small DSL:
  `host=uwh source~docker level≥warn 1h` → parses into the existing
  filter state. Optional, but pairs nicely with the URL-fragment story.

---

## Out of scope

- Login page styling. Already done.
- The `/api/*` shape. Read-only contract; if a query you want isn't
  there, propose it but don't redesign the API.
- Internationalization. Single user, English (and his own pidgin).
- Theming customization beyond dark/light. One opinionated dark is fine.

---

## Closing instruction

Don't ask clarifying questions before producing the design — make
opinionated calls and explain them in the per-screen rationale. If you'd
like alternative directions for any screen (e.g., expand-inline vs
right-drawer for detail view), produce **both** and let me compare.

Make the desktop logs view first; it's the keystone. Phone follows.
Jobs view comes last (less ambiguity than logs anyway).
