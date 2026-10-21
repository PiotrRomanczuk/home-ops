---
created: 2026-07-12
author: Claude (read-only analysis)
scope: home-ops @ branch feature/daily-status-email (HEAD d20ed8a), reconciled against ROADMAP.md
---

# home-ops — Status Reconciliation & Mission Control Fit

## 1. Executive summary

home-ops is a **personal observability + automation stack** on a 3-host home network
(elitedesk / win10 / rpi) behind Tailscale, built on one Postgres + a Hono ingest API.
Three pillars: centralized structured logs (`host_logs`), a gaming-aware GPU job queue
(`gpu_jobs`), and — grown since the original plan — a **projects board, daily briefing
email, and an LLM-eval harness**.

**Verdict: healthy and further along than its own roadmap says.** The headline finding
is *documentation drift*, not missing work. `ROADMAP.md` (frontmatter `updated: 2026-06-07`)
predates roughly a month of shipped features: migrations are at **012** (the roadmap only
documents through 003), the Session 4 agent-hardening refactor largely landed via a shared
`agents/_common.py` runtime, and three whole subsystems (evals, projects board, planner-sync)
aren't in the roadmap's session list at all. The genuinely-unfinished set is small and
well-defined. The biggest real gap is **agent offline-resilience (a local SQLite spool)** —
today, if the ingest API or Postgres is down, in-flight log/metric events are lost.

## 2. What's DONE (verified in code)

**Core stack** — Postgres (`001_init`), pg_cron retention (`002`), host metrics (`003`),
docker-compose (postgres + ingest), health check, Tailscale-only reachability. Phase G
(host metrics + per-process attribution) is **live across all 3 hosts**.

**Migrations 004–012 — all shipped** (roadmap only documents ≤003):
`004_cancelling_status`, `005_projects`, `006_task_toggles`, `007_schema_migrations`
(the `apply-migrations.sh` mechanism + `schema_migrations` table the roadmap wanted),
`008_weekly_review_cron` (a *future-direction* item already built), `009_eval`,
`010_dead_agent_sentinel`, `011_unclaimed_job_sentinel`, `012_eval_tasks`.

**Agents — all three hosts written** (`agents/`): `elitedesk-watcher.py`, `rpi-watcher.py`,
`win10-watcher.py` + `ollama-watcher.py` + `sample-gpu.ps1` + WinSW service XMLs,
`gpu-scheduler.py`, and a new `planner-sync.py` (vault/planner → projects board). A shared
`_common.py` runtime now backs every agent.

**Session 4 refactor — largely landed** (via `_common.py`, which my first pass missed):
cross-thread **soft-drain shutdown** (signal install, SIGINT/SIGTERM), **self-logging**
(`post_log`), **`agent:<name>` source convention**, **narrowed exception types**,
**journald cursor backfill**, and 3-retry batched POST semantics.

**Session 4b server companion — mostly done**: `004_cancelling_status` ✓,
`007_schema_migrations` + `apply-migrations.sh` ✓, and **partial-batch acceptance**
(`/api/ingest` returns `{inserted, rejected[]}`) ✓.

**ingest API routes**: `ingest`, `jobs`, `logs`, `metrics`, `projects`, `reports` (daily
email), `evals`, `status`, `health`, `auth`.

**Viewer** (vanilla-JS SPA served from `ingest/public/`, not a separate Vite app): tabs for
**Logs, Jobs, Hosts, Evals, Chat** — the Phase C/G "Hosts tab" the roadmap lists as pending
is in fact present.

**Ops & automation**: `pg-backup` systemd timer, `daily-report` timer (06:30 briefing email,
Gmail SMTP), the **LLM-eval harness** (`ops/llm-eval/` — Dockerized coding tasks:
balanced-brackets, parse-duration, reverse-words, rle-encode, plus a Strummy-specific eval;
`eval-tick` service/timer, `eval_tasks` board + Evals tab), `scripts/deploy-agent.sh`
(the roadmap only *suggested* writing this), and an **MCP server** (`mcp/server.py`) so an
LLM client can read home-ops state and submit jobs.

**Tests**: `test_planner_sync.py`, ingest `report.test.ts`, `jobs-state-machine.test.ts`,
plus the eval task solution tests.

## 3. What's SUPPOSED to be finished but ISN'T (verified gaps, ranked)

1. **Agent SQLite spool — not implemented** (Session 4, item 2.4). No local buffer at
   `/var/lib/*/spool.db`. If ingest/Postgres is unreachable, events are dropped. This is the
   one real reliability gap in the data pipeline and the highest-value remaining item.
2. **Disk-monitor thread — not implemented** (Q23). No `pg_database_size` / disk-usage watch
   emitting warn@75% / error@90%. The DB can fill silently.
3. **Session 4b leftovers**: **hourly prune** not applied (`002_pg_cron` still schedules
   `'0 4 * * *'`, not `'0 * * * *'`); **per-kind default priority** (`embed=0/summarise=5/
   generate=10`) not found in `routes/jobs.ts`.
4. **`EVENT_SCHEMA.md` missing** — the well-known `data` keys table + level-conventions doc
   the roadmap calls for was never written. (Real cost: agents and the viewer rely on an
   undocumented `data` jsonb contract.)
5. **`feature/daily-status-email` is unmerged** — 2 commits ahead of `main` (daily briefing
   email + planner-sync fix), 0 behind. Finished in code, not shipped to `main`.
6. **Viewer polish**: staleness **status footer** (per-host last-event / last-metric lag) and
   the stretch **saved-queries tab** are still open.
7. **Manual host carryover** (can't be verified from the repo — they're on the machines):
   Tailscale admin cleanup of 4 stale devices; NAS share mount + `pg-backup` timer install on
   elitedesk; Kuma HTTP monitor on the Pi.
8. **ROADMAP.md is stale** — frontmatter `2026-06-07`, no mention of migrations 004–012, the
   eval subsystem, the projects board, or planner-sync. It should be reconciled to reality.
9. **Minor**: bump `.github/workflows/check.yml` `actions/checkout` + `setup-node` to v5
   (Node 20 deprecation, deadline Sep 2026).

## 4. Can Mission Control help? Yes — and here's the honest split

home-ops is an unusually **good fit** for Mission Control: the roadmap is already broken into
1–2 hour, single-purpose tasks, and the repo runs a clean branch-per-feature + PR flow
(PRs #21–25). That maps almost 1:1 onto MC's "one session per task, worktree-isolated" model.

**Where MC + Claude Code directly helps (code/docs/tests — do these in MC sessions):**

- **Reconcile the roadmap.** One session: audit code vs `ROADMAP.md`, rewrite it to reality,
  and fold the eval/projects/planner-sync work into the session list. (This document is a
  starting point.)
- **Close the real gaps.** One focused session each: the **SQLite spool** (highest value),
  the **disk-monitor thread**, the **hourly-prune** migration, **per-kind priority**, and
  **`EVENT_SCHEMA.md`**. Each is small, testable, and independent — ideal for parallel
  worktrees.
- **Ship the stranded branch.** MC's **Ship** button + **Create pull request** flow can
  commit, push, and open the PR for `feature/daily-status-email` into `main`.
- **Extend tests** around the ingest routes and the new eval/projects surfaces.
- **The `/audit` skill** (now installed) can run a whole-repo tech-debt sweep like it did for
  guitar-crm.

**Where MC does NOT reach (be realistic):** a chunk of "unfinished" work is *on the hosts*,
not in the repo — SSH deploys to elitedesk/win10/rpi, installing systemd `--user` timers,
the Kuma web UI, Tailscale admin console, the NAS mount. MC runs Claude Code locally in the
repo; a session's terminal *can* run SSH commands (mind the repo's SSH-persistence rule:
detach long-running remote processes), and it can write/verify **deploy scripts**, but the
physical host verification (is the timer firing? is psutil present? did the container
restart?) stays a manual/SSH loop outside MC's inner cycle. Note also the deploy gotcha the
roadmap flags: agents run from `~/bin/…`, *not* the cloned repo, so `git pull` alone doesn't
update running code — `scripts/deploy-agent.sh` exists to formalize this.

**Meta-fit:** home-ops's own "life-OS substrate" vision (a GPU job queue for
`summarise_emails`, embeddings, weekly reviews) and MC overlap in spirit but occupy different
layers — home-ops is the *runtime* for background AI work; MC is the *dev cockpit* that
builds it. They complement rather than compete.

## 5. Suggested first three Mission Control sessions

1. **`docs: reconcile ROADMAP.md with shipped state`** — low-risk, high-clarity; unblocks
   everything else by making the TODO trustworthy again.
2. **`feat(agent): SQLite spool for offline resilience`** — the one genuine reliability gap;
   scoped to `_common.py` + the watchers, with a test.
3. **`chore: ship daily-status-email`** — merge the stranded branch to `main` via MC's PR flow.

Then fan out the small items (disk-monitor, hourly prune, per-kind priority, EVENT_SCHEMA.md)
across parallel worktree sessions.

---

_Method: static read-only analysis — file reads and `grep`/`git` scans over `agents/`,
`ingest/`, `postgres/migrations/`, `ops/`, `scripts/`, `docs/`, cross-checked against
`ROADMAP.md` and `docs/CONTEXT.md`. No code executed, no live host or DB inspected._
