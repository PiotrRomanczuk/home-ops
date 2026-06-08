---
created: 2026-06-07
updated: 2026-06-07
---

# home-ops — UI design brief

> **Read `CONTEXT.md` first.** It defines what home-ops is, who uses
> it, the data model, the use cases, and the future-facing direction.
> Everything below assumes that context.
>
> This brief covers the UI-specific layer only: aesthetic constraints,
> anti-patterns, deliverable format, and stretch ideas.

---

## What you're designing

A complete UI for home-ops covering its **three pillars** (per
`CONTEXT.md`): `host_logs`, `gpu_jobs`, `host_metrics`. Three views,
each with a desktop (1440×900+) and mobile (390×844 portrait) variant:

1. **Logs view** — the keystone. Filter bar + dense table + status footer + per-row drawer/detail.
2. **Jobs view** — `gpu_jobs` dashboard: kind / status / priority / created / attempts / `last_error` preview, click for full record.
3. **Hosts view** — `host_metrics` per-host sparklines (last 1h / 6h / 24h) + top-process tables + per-host drill page with recent `level >= warn` events inline (correlation surface).

Plus a persistent **status indicator** visible from any view: ingest
API health dot, per-host last-event-lag (so dead agents are visible),
disk pct, queue depth at a glance.

## Hard constraints (non-negotiable)

1. **Dark theme by default.** Light mode optional; same component shapes recolored.
2. **Monospace everything** — body, table cells, labels, buttons, numbers (tabular numerals).
3. **Information density** — desktop fits ~40 rows above the fold at 1440×900. No card wrappers per row. No oversized padding.
4. **Filter state is a URL fragment** — every state combination shareable + reloadable. Existing contract: `#host=elitedesk&source=docker:foo&level_min=warn&since_min=60&grep=oom&tail=0` — extend it for the Jobs / Hosts views as needed.
5. **Mobile parity** — every operation possible on desktop is possible on a 390-wide phone. Slower OK, absent not.
6. **Live tail must not jank** — every 2s, append new rows in-place without layout-thrash. Virtualized list optional below 2000 rows.
7. **No new HTTP API** — read `CONTEXT.md` for the existing API. If you need a query that isn't there, propose it but don't redesign the API.
8. **Single binary deploy** — fits the existing Hono server serving the static Vite SPA build from `ingest/public/`. No separate Node process for the UI.

## Aesthetic direction

Take the existing minimal dark-monospace aesthetic and **make it distinct**.

**Reference points** (don't copy):
- `lnav`, `dozzle`, `clog`, `vector top`, `lsof`
- Pulsar/Atom, older Sublime default, GitHub Dark "high contrast"

**Anti-references**:
- Datadog, Grafana, Material-themed anything, generic enterprise admin panels

**Specific moves to consider:**
- **Tabular numerals** with column alignment. Timestamps, durations, counters.
- **Small-caps column headers** with subtle letter-spacing — differentiates header from data without making it heavy.
- **Color sparingly**: accent only for active state + interactive affordances. Severity colors only on the `level` column + maybe a thin left-border per row for `warn+`.
- **Time as primary axis**: toggle between absolute (`21:08:41`) and relative (`3m ago`). Mobile defaults to relative, desktop to absolute.
- **Status density in chrome**: e.g. footer showing `elitedesk: 2s ago • win10: 8s ago • rpi: 4m ago`, each segment green/yellow/red by lag.
- **Microinteractions**: tail pause/resume on `f`, level threshold via `1-5`, search focus on `/`, row navigation via `j/k`. Hint via small `kbd` badges in tooltips.

## Anti-patterns to avoid

- ❌ Left sidebar / nav rail. Three tabs (Logs, Jobs, Hosts); a top tab strip suffices.
- ❌ Hero "summary" cards (total events, error rate sparkline). This is a tail, not a dashboard.
- ❌ Heavy iconography. Maybe one icon per nav item + level dots. No feature-icon explosion.
- ❌ Modal-on-modal patterns. Detail = expand-inline or right-side drawer, not centered dialog.
- ❌ Animated transitions over 200ms. Operator tool — speed > polish.
- ❌ Generic Material/Tailwind defaults. The aesthetic must read as "this person built this tool for themselves."

## Deliverables

For each of {Desktop Logs, Desktop Jobs, Desktop Hosts, Desktop Detail,
Mobile Logs, Mobile Jobs, Mobile Hosts, Mobile Detail}:

- A **self-contained HTML file** with inline CSS (Tailwind via CDN OK). Realistic baked-in data: 5–10 log rows covering all 5 levels and all 4 hosts; 4–6 jobs covering all 7 statuses; 3 hosts of metrics with sparklines (use SVG or canvas, your call — uPlot is the planned library for production).
- **2–4 sentences of rationale** per screen: what you optimized for, what tradeoff you made.

Plus one cross-cutting document (≤300 words):

- **Color + typography system** — named tokens (`--bg`, `--bg-elevated`, etc.), font sizes, line heights, your specific monospace stack.
- **Interaction model** — keyboard shortcuts, hover behaviors, click/cmd-click/right-click semantics.
- **Empty / loading / error states** — what shows when no rows match, ingest unreachable, user filtered to nothing.

## Stretch (optional — pick what excites you, name what you'd defer)

- **Saved deep-link chips** — pre-defined filter sets above the filter bar: "warn+ 1h", "elitedesk errors", "active jobs", "win10 idle GPU". Customizable via `localStorage`.
- **Correlation chips in row data** — clicking `pid: 31254` in any row's data filters all logs by that pid across hosts. Hover: "▷ 12 events with pid=31254" affordance.
- **Tail direction toggle** — some operators read bottom-up (terminal-style), others top-down (browser-style). Make it a setting, surface the active mode.
- **Scratch filter DSL** — small text input accepting `host=elitedesk source~docker level≥warn 1h` and parsing into the existing filter state. Pairs with the URL-fragment story.
- **Live host-status sparkline in the footer** — a tiny inline 60-min-rolling sparkline per host, color-tinted by current CPU%. Makes the footer carry signal, not just text.

## Out of scope

- Login page styling — already done.
- API shape changes — read-only contract.
- Internationalization — single user, English.
- Theming customization beyond dark/light.

## Closing instruction

Don't ask clarifying questions before producing the design — make
opinionated calls and explain them in the per-screen rationale. If
you'd like to propose alternatives for any screen (e.g. expand-inline
vs right-drawer for detail view), produce **both** so they can be
compared side-by-side.

Order of attack: **Desktop Logs first** (the keystone). Then Desktop
Hosts (where new value lives). Then Mobile Logs. Then everything else.
