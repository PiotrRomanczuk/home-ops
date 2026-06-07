# ADR 001 — No Grafana, no Loki, no Prometheus

**Date**: 2026-06-07
**Status**: Accepted
**Deciders**: Piotr (solo)

## Context

home-ops is growing from "centralized logs + GPU queue" toward a
broader observability and personal-automation substrate. The newly-added
`host_metrics` table (Phase G) raises a natural question: should we
bring in Grafana to visualize CPU/mem/GPU sparklines and dashboards,
rather than rendering them inline in the custom viewer?

The original `home-ops-logger-plan.md` (2026-06-07) had an explicit
"no Loki/Grafana/Prometheus/ELK" constraint at line 20, justified by
"3-host scale; matches Kuma+Beszel ruling." That decision was made
when the project was scoped to logs+jobs only. Adding metrics is a
genuine scope expansion, so the constraint deserves a fresh look.

Two specific Grafana variants were considered:

1. **Grafana for everything** — replace the custom viewer entirely;
   use Loki-driven log panels for `host_logs`, native PostgreSQL
   datasource for metrics and jobs.
2. **Grafana for metrics only** — keep the custom viewer for logs and
   jobs; bring in Grafana solely for time-series visualization of
   `host_metrics`, reading directly from Postgres (no Prometheus needed).

## Decision

**Don't bring in Grafana for either case.** Render metrics in the
existing custom viewer using a lightweight chart library (e.g. uPlot,
~40 KB). Keep Beszel running unchanged for casual time-series glances.

## Reasoning

1. **It solves the wrong problem.** The stated analytical goal is to
   *discover* infrastructure-usage patterns ("is uwh underutilized?",
   "what's eating GPU when I'm not gaming?"). Grafana's strength is
   *monitoring* (panels you stare at to confirm a state), not querying.
   Discovery is better served by SQL via `psql` for ad-hoc work and
   small custom inline panels in the viewer for recurring questions.

2. **It dilutes the project's identity.** home-ops is, by deliberate
   design, a hand-built, terminal-aesthetic, monospace, dense, one-user
   tool. Grafana is the opposite — corporate, dashboard-aesthetic,
   multi-tenant. Theming dark doesn't change the bones. Adding it
   means the answer to "where do I look at metrics?" is "different UI,
   different conventions, different login" — fragmentation that the
   original "no Grafana" decision was meant to prevent.

3. **Beszel already covers the casual-glance case.** Per `HOSTS.md:46`,
   the Pi runs Beszel hub on `:8090` with agents on each host
   reporting CPU/mem/disk/net/temperature. Time-series sparklines and a
   trend UI exist. The thing Beszel doesn't have is **process-level
   attribution** and **log correlation**, and Grafana wouldn't give us
   either without bespoke per-dashboard work.

4. **Operational cost is non-trivial.** A new container, a new auth
   surface, a new `tailscale serve` entry, a new upgrade cadence,
   another set of dashboards-that-drift-from-intent. Plus the cognitive
   cost: now four UIs to keep mental models of (viewer + Kuma + Beszel
   + Grafana). Each new UI dilutes the others.

5. **The "Grafana for queries" idea is a trap.** Grafana's Explore mode
   is supposed to support ad-hoc querying, but in practice users
   either save the query as a panel (polluting the dashboard) or
   retype it next time. SQL via `psql` / Datasette / DBeaver is the
   correct tool for ad-hoc analytical work, and we already have
   Postgres.

## Consequences

**Positive:**
- Single UI to operate, theme, and evolve.
- Beszel keeps its role; no overlap, no duplicated effort.
- All analytical work lives in SQL — versionable, scriptable, reviewable.
- The viewer's design language extends cleanly to a Hosts tab with
  sparklines (uPlot in dark monospace fits).

**Negative:**
- We must build a chart layer in the viewer for `host_metrics`. ~Half
  a day of work with uPlot. Continued maintenance.
- We lose Grafana's alerting features (Kuma already covers HTTP-level
  alerting; future metric-threshold alerts will need a custom path,
  but pg_cron + Telegram bot covers it).
- Sharing a graph with someone outside the tailnet is awkward (the
  custom viewer isn't public-internet exposed). Acceptable for solo use.

## Reconsider if any of these become true

- We onboard multiple GPU hosts and want per-cluster aggregation.
- We want a 7-day SLA dashboard to show someone else.
- We need alerting smarter than Kuma+threshold-pg_cron.
- We start writing OpenMetrics/OTLP exporters and want a standard
  ecosystem to consume them.

None of these is true now or in the next 3-6 months of the roadmap.

## What we'll do instead (linked to ROADMAP Phase G)

1. **Layer 1 — schema**: `postgres/migrations/003_host_metrics.sql`
   adds the `host_metrics` table + `prune_host_metrics(keep_days)` +
   pg_cron schedule.
2. **Layer 2 — agent sampling**: each watcher agent gets a
   `metric_sampler_loop` thread (every 30s), using `psutil` for
   CPU/mem/net/disk + platform-specific GPU queries. Process
   attribution included in `data` jsonb.
3. **Layer 3 — viewer Hosts tab**: new tab alongside Logs and Jobs.
   Sparklines via uPlot for last 1h/6h/24h. Per-host drill page with
   top-process tables, recent events of `level >= warn` inline for
   correlation.
4. **Layer 4 (stretch) — saved analytical queries**: a small JSON
   manifest (`docs/saved-queries.json` or `localStorage`) defining
   named queries that the viewer runs and renders inline. The
   lightweight equivalent of Grafana dashboards without Grafana.

Beszel keeps running as-is throughout.
