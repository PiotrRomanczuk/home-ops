---
created: 2026-06-07
updated: 2026-06-07
---

> Tip: search for "Session N" to jump between sessions. "Done" is at the bottom.

# home-ops ROADMAP

Working list. WIP-marking pattern: change `- [ ]` to `- [ ] WIP (@agent-name)` before starting, back to `- [x]` when done. See `~/Desktop/MainCV/CLAUDE.md` ("Working on TODO Tasks") for the full protocol.

Foundational reference: `docs/CONTEXT.md` — read this first when starting any work on home-ops.
Architectural decisions: `docs/adr/` — e.g. `2026-06-07-no-grafana.md`.
Original architecture plan: `~/Desktop/MainCV/infrastructure/home-ops-logger-plan.md` — will be archived once Phase F is green.
Improvement plan: `~/.claude/plans/analyze-this-folder-and-curious-shamir.md` (decisions log).

## Active

### Session 2 — Docs hygiene
Moved to Done.

### Session 3 — Ops hardening
Moved to Done.

### Session 4 — uwh-watcher refactor (the pattern, ~2 hours)

Session 4 now absorbs everything decided in functional-grilling round 2 that
touches the uwh-watcher codebase. See
`~/.claude/plans/analyze-this-folder-and-curious-shamir.md` "Functional
decisions log" for the why on each.

Agent code changes:
- [ ] **Two-layer payload validation** — TS at /api/jobs + Python at job-claim (item 1.4)
- [ ] **SIGTERM/SIGINT soft-drain** with 5s cap (item 1.5)
- [ ] **SQLite spool** per agent at `/var/lib/uwh-watcher/spool.db` (item 2.4)
- [ ] **Narrow `except Exception`** to specific types (URLError, OperationalError, OSError, sqlite3.OperationalError)
- [ ] **Docker `-t` flag + parse source timestamp** so docker events get `ts` from source, not ingest-time (Q2)
- [ ] **journald cursor-based backfill**, capped at 1h. Cursor stored in the same SQLite as the spool (Q4)
- [ ] **Always-on home-ops containers** in default `WATCH_CONTAINERS`: prepend `home-ops-postgres-1,home-ops-ingest-1` even if env says otherwise (Q5)
- [ ] **Handle `{inserted, rejected}` response shape**; emit one warn-level row per rejected event (Q9)
- [ ] **Self-logging via `post_log`** — copy gpu-scheduler.py pattern; lifecycle/errors → direct synchronous POST; routine events → batched queue (Q22)
- [ ] **Rename journald keys at extraction**: `_pid` → `pid`, `_exe` → `cmd`, `_cmdline` → `cmd_args`, etc., per the well-known keys convention (Q21)
- [ ] **Smarter docker level parser**: `\b5\d\d\b` → error; `\b4\d\d\b` near method-verb → warn; `panic|FATAL` → fatal; current keyword fallback for everything else (Q12)
- [ ] **Disk-monitor thread**: every 60s, query `pg_database_size('home_ops')` and `df` of pgdata volume; post warn at 75% disk used, error at 90% (Q23)
- [ ] **Self-source rename**: any place that emits as bare name should emit as `agent:uwh-watcher` (Q10)

Documentation:
- [ ] **EVENT_SCHEMA.md** (or section in README) — well-known `data` keys table + level conventions rule + source naming convention
- [ ] Update the "Verify" section with the new probe pattern (POST event with `data: {pid: 12345}`, query back filtered by `data->>'pid'='12345'`)

### Session 4b — Server-side companion to session 4 (~1.5 hours)

Parts of the round-2 decisions live on the ingest server, not the agent.
Either bundle into session 4 or split.

- [ ] **Partial-batch acceptance** — `/api/ingest` returns `{inserted: N, rejected: [{index, reason}]}` instead of all-or-nothing 400 (Q9). server.ts:158-167.
- [ ] **`status='cancelling'` enum value** — `003_cancelling_status.sql` migration: `ALTER TYPE job_status ADD VALUE 'cancelling';`. `/api/jobs/:id/cancel` accepts running jobs and sets to `cancelling`. Scheduler polls per iteration (Q11).
- [ ] **Per-kind default priority** — `KIND_DEFAULT_PRIORITY` lookup in `/api/jobs` POST handler: embed=0, summarise=5, generate=10 (Q17).
- [ ] **`apply-migrations.sh`** + `schema_migrations` table + remove `./postgres/migrations:/docker-entrypoint-initdb.d:ro` mount from compose (Q20). Backfill existing rows on first apply.
- [ ] **Hourly prune schedule** — change `002_pg_cron.sql` `cron.schedule` calls from `'0 4 * * *'` to `'0 * * * *'` (Q23 carryover).

### Session 5 — Phase B (~2 hours)
- [ ] Deploy wfh ollama-watcher.py + WinSW (already written, needs the session-4 patterns retrofitted before deploy)
- [ ] Stano backend logger.ts dual-write into home-ops

### Session 6 — Phase D (~2 hours)
- [ ] Deploy gpu-scheduler.py + WinSW. Add: `displacers.txt` (renamed from games.txt) + `/api/scheduler/pause` manual switch (Q8), startup-requeue-my-own-running-jobs at boot (Q6), 5-requeue cap inside the reaper (Q7), poll for `status='cancelling'` per handler iteration (Q11).

### Session 7 — Phase E (~1 hour)
- [ ] Build agents/rpi/rpi-watcher.py + systemd --user unit
- [ ] Deploy on rpi

### Session 8 — Phase F (~1 hour)
- [ ] Run the 12 probes in home-ops-logger-plan.md:130-141
- [ ] Update Written/Deployed status table (item 1.1)

### Session 9 — Doc split (~30 min)
- [ ] Move living parts to README.md; archive home-ops-logger-plan.md as 2026-XX-XX-home-ops-rollout.md (item 3.5)

### Session 10 — Phase C (~4 hours)
- [ ] Standalone Next.js viewer at home-ops/viewer/ following `docs/DESIGN_BRIEF.md`
- [ ] Move tailscale serve from :64421 to :64420

### Session 11 — Phase G (host metrics + attribution) — server + agent ✅ landed 2026-06-07

Already partially shipped this session:
- [x] `postgres/migrations/003_host_metrics.sql` — schema + `prune_host_metrics` + pg_cron schedule at `30 * * * *`
- [x] `ingest/src/server.ts` — `POST /api/metrics` (token-gated) + `GET /api/metrics` (viewer-or-token); validators, batch insert (max 500)
- [x] `agents/uwh/uwh-watcher.py` — `metric_sampler_loop` thread (30s interval, top-10 CPU + RSS attribution); psutil-dependent, gracefully disables if missing
- [x] `docs/adr/2026-06-07-no-grafana.md` — formal ADR documenting why metrics live in home-ops Postgres rather than Grafana/Prometheus

Still to do:
- [x] 2026-06-07 **uwh deploy** — psutil 7.0.0 already present (no apt needed); `~/bin/uwh-watcher.py` updated from repo + `systemctl --user restart`. `metrics=on`, samples landing every 30s.
- [x] 2026-06-07 **wfh metric sampling** — written as `agents/wfh/wfh-watcher.py` (new sibling of ollama-watcher.py, not bolted into gpu-scheduler.py to preserve scope). GPU sampling via `agents/wfh/sample-gpu.ps1` using Windows built-in Get-Counter (no AMD CLI install — investigation showed Adrenalin/ADLX don't write log files; ADLX SDK + Python bindings is the future temp path). Ollama models-loaded via `GET /api/ps`. Deployed to `C:\ProgramData\WfhWatcher\` as `WfhWatcher` WinSW service. 30s sampling verified. **Temperature not captured** — `gpu_temp_c` stays NULL on wfh until amdgpu_top.exe or AMDuProfCLI install.
- [x] 2026-06-07 **rpi metric sampling** — wrote `agents/rpi/{rpi-watcher.py, rpi-watcher.service}` ahead of formal Phase E. Deployed via scp to `~/bin/` + `~/.config/systemd/user/` on rpi, linger enabled. CPU/SoC temp lands in `data.cpu_temp_c` (jsonb), NOT in the `gpu_temp_c` column — the column is semantically GPU-specific. First row verified: cpu 29.7%, load 1.33, mem 10.8%, disk 45.6%, temp 71.6°C. Phase G is now **live across all 3 hosts** (uwh + wfh + rpi all stream every 30s).
- [ ] **Viewer Hosts tab** — Phase C deliverable (per DESIGN_BRIEF.md); sparklines via uPlot, per-host drill page with top-process tables and recent-warn-events sidebar for correlation
- [ ] **Status footer in viewer** — per-host last-event lag + last-metric lag, color-coded by staleness
- [ ] **Saved analytical queries** (stretch) — `docs/saved-queries.json` + a "Queries" tab that runs them and renders as table-or-chart based on shape

## Deferred / open questions

- Off-site backup via rclone → Google Drive (when value clears setup cost — see 2.3)
- /api/stats endpoint (dropped from plan, revisit if pool saturation surfaces — 2.6)
- Cloudflare tunnel config migration from dashboard to file (don't do unless ingress starts churning — 3.3)

## Future direction — home-ops as life-OS substrate

home-ops is currently scoped to centralized logs + GPU job queue. The
medium-term aspiration is to use the same substrate (Postgres + ingest API
+ idle-time worker) to coordinate cross-project work and personal
information at home — a single timeline + queue across everything that
matters.

Concrete shape (all deferred — none are session work yet):

- **Cross-project domain events**: each project (Stano, guitar-crm, Pracuj
  scraper, CV generator) dual-writes lifecycle events (`scrape_started`,
  `deploy_succeeded`, `application_submitted`, `lesson_recorded`) with
  source prefix `app:*`. The viewer becomes a single grep across "what was
  I doing on day X."
- **Stano embeddings (first real workload for the queue)** — `bge-m3`
  embeddings of Twitter/YouTube/weszlo content into a Stano-owned
  embeddings table, similarity search via pgvector. Powers Stano's
  hybrid retrieval RAG. Currently runs in-process inside Stano's own
  backend; migration to home-ops `gpu_jobs` is the planned next step
  so embedding work gets gaming-aware pausing and decouples from
  Stano's request path. See `~/Obsidian/MainCV-Planner/projects/stano.md`
  and improvement plan's "Functional decisions" Q12-r2 through Q18-r2
  (note: the plan-file question labels say "Pracuj" — that was a
  transcription error on my part; the actual workload is Stano).
- **AI-assisted background tasks**: queue kinds like `summarise_emails`,
  `transcribe_voicenote`, `score_offer_against_cv`. Each is a new
  `kind` + handler file; inherits gaming-pause, retries, priority.
- **Recurring obligations via pg_cron**: not just retention. Friday
  morning generates a weekly review from the week's `host_logs` events;
  Sunday queues a batch summarise of new Stano content;
  Monday auto-cleans expired branches per `~/.claude/rules/branch-hygiene.md`.
- **Personal embeddings**: same `stano_embeddings`-style pattern
  (planned) but for notes, ideas, lesson plans. Semantic search across
  "everything I've thought about" becomes a SQL query.

Design implication for sessions 4-8: **don't paint into a corner that
forecloses any of the above.** Specifically: keep the `data` jsonb
schema-less (Q21 well-known keys, not column splits), keep embeddings
in `home_ops` Postgres (Q13-r2 A, not a separate DB), keep `gpu_jobs`
generic (any `kind` + payload, not workload-specific). Those are already
the chosen paths — just don't drift.

When implementation queue runs dry, the next sub-roadmap to draft would
start: "(1) which projects start dual-writing domain events first?
(2) what's the v1 query / report that uses them?"

## Done

- [x] 2026-06-07 Foundation: git init, .gitignore, generate-env.sh, biome+tsconfig, GHA, README pointer fix, ROADMAP
- [x] 2026-06-07 Session 2 — docs hygiene: HOSTS.md uwh ports added, viewer Quick Link added, Cloudflare TBD resolved (remotely-managed via Zero Trust), uph/upo SSH aliases retired, stale-entries sections removed.
- [x] 2026-06-07 Session 3 — ops hardening: ingest healthcheck (wget against /api/health), postgres image switched to debian + pg_cron, 002_pg_cron.sql with 30d host_logs prune + 30d done gpu_jobs prune (failed kept forever), ops/uwh/pg-backup.{sh,service,timer} + NAS-mount docs, Kuma probe recipe in README.
- [x] 2026-06-07 Functional grilling (round 2): 23 functional decisions captured in `~/.claude/plans/analyze-this-folder-and-curious-shamir.md` "Functional decisions log". Sessions 4 and 4b updated to absorb the actionable ones. Future-direction note added below.
- [x] 2026-06-07 Doc split: `docs/CONTEXT.md` becomes the foundational project doc (read-first); `docs/DESIGN_BRIEF.md` slimmed to UI-only and references CONTEXT.md; `docs/adr/` introduced with `2026-06-07-no-grafana.md` as the first formal decision record.
- [x] 2026-06-07 Phase G partial: `host_metrics` schema (003 migration), `/api/metrics` POST+GET routes, `uwh-watcher` metric_sampler_loop with per-process attribution. Awaits uwh deploy (`apt install python3-psutil`) + viewer Hosts tab (Phase C).

**Carryover** (UI / shell actions on the actual hosts — not file edits):
- [ ] Tailscale admin console: delete `desktop-t0jdc7e`, `iphone182`, `piotrs-macbook-air`, `piotr-ubuntu` at https://login.tailscale.com/admin/machines (from session 2)
- [x] 2026-06-07 uwh: deployed session 3 changes — `cd ~/logs-stack && git pull && docker compose down && docker compose up -d --build`. Postgres switched alpine→debian 17.10 with pg_cron, pgdata preserved, ingest rebuilt with /api/metrics.
- [x] 2026-06-07 uwh: applied 002_pg_cron.sql + 003_host_metrics.sql against the running DB. 3 cron jobs scheduled (host_logs daily 04:00, gpu_jobs daily 04:15, host_metrics hourly :30).
- [x] 2026-06-07 uwh: Phase G deployed — psutil 7.0.0 already present (apt install unnecessary), `~/bin/uwh-watcher.py` overwritten from `~/logs-stack/agents/uwh/uwh-watcher.py`, `systemctl --user restart uwh-watcher.service`, journal confirms `metrics=on`, first samples landed in `host_metrics` with cpu/mem/disk/net + top_cpu/top_mem attribution.
- [ ] uwh: mount the NAS share + install the pg-backup timer per `ops/uwh/README.md`.
- [ ] Pi (Kuma): add the HTTP monitor per README → "Monitoring" section.

**Deploy mechanism note (uwh-watcher)**: there is no deploy script. The watcher runs from `~/bin/uwh-watcher.py` (NOT from the cloned repo) as a user-scope systemd service (`~/.config/systemd/user/uwh-watcher.service`, enabled). Pulling the repo does not update the running code — you must `cp ~/logs-stack/agents/uwh/uwh-watcher.py ~/bin/uwh-watcher.py && systemctl --user restart uwh-watcher.service`. Same pattern will apply to wfh (via WinSW) and rpi when those agents land — consider writing a small `scripts/deploy-agent.sh` to formalize this.

**Minor follow-up** (low-priority):
- [ ] `.github/workflows/check.yml`: bump `actions/checkout` and `actions/setup-node` to v5 when stable, to avoid Node 20 deprecation warning (deadline Sep 2026).
