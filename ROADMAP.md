---
created: 2026-06-07
updated: 2026-06-07
---

> Tip: search for "Session N" to jump between sessions. "Done" is at the bottom.

# home-ops ROADMAP

Working list. WIP-marking pattern: change `- [ ]` to `- [ ] WIP (@agent-name)` before starting, back to `- [x]` when done. See `~/Desktop/MainCV/CLAUDE.md` ("Working on TODO Tasks") for the full protocol.

Architectural reference: `~/Desktop/MainCV/infrastructure/home-ops-logger-plan.md` — will be archived once Phase F is green.
Improvement plan: `~/.claude/plans/analyze-this-folder-and-curious-shamir.md` (decisions log).

## Active

### Session 2 — Docs hygiene
Moved to Done.

### Session 3 — Ops hardening (~1.5 hours)
- [ ] docker-compose.yml: ingest healthcheck via /api/health (item 2.1)
- [ ] Switch postgres image to debian; add 002_pg_cron.sql with 30d host_logs + 30d done gpu_jobs prunes (items 2.2, 13a, 13b)
- [ ] ops/uwh/pg-backup.{sh,service,timer} → NAS nightly (item 2.3)
- [ ] Kuma HTTP probe on /api/health (item 2.5)

### Session 4 — uwh-watcher refactor (the pattern, ~1 hour)
- [ ] Two-layer payload validation: TS at /api/jobs + Python at job-claim (item 1.4)
- [ ] SIGTERM/SIGINT soft-drain with 5s cap (item 1.5)
- [ ] SQLite spool per agent (item 2.4)
- [ ] Narrow `except Exception` to specific types

### Session 5 — Phase B (~2 hours)
- [ ] Deploy wfh ollama-watcher.py + WinSW (already written, needs deploy)
- [ ] Stano backend logger.ts dual-write into home-ops

### Session 6 — Phase D (~2 hours)
- [ ] Deploy gpu-scheduler.py + WinSW (already written, needs deploy)
- [ ] Inherits validation + signals from session 4

### Session 7 — Phase E (~1 hour)
- [ ] Build agents/rpi/rpi-watcher.py + systemd --user unit
- [ ] Deploy on rpi

### Session 8 — Phase F (~1 hour)
- [ ] Run the 12 probes in home-ops-logger-plan.md:130-141
- [ ] Update Written/Deployed status table (item 1.1)

### Session 9 — Doc split (~30 min)
- [ ] Move living parts to README.md; archive home-ops-logger-plan.md as 2026-XX-XX-home-ops-rollout.md (item 3.5)

### Session 10 — Phase C (~4 hours)
- [ ] Standalone Next.js viewer at home-ops/viewer/
- [ ] Move tailscale serve from :64421 to :64420

## Deferred / open questions

- Off-site backup via rclone → Google Drive (when value clears setup cost — see 2.3)
- /api/stats endpoint (dropped from plan, revisit if pool saturation surfaces — 2.6)
- Cloudflare tunnel config migration from dashboard to file (don't do unless ingress starts churning — 3.3)

## Done

- [x] 2026-06-07 Foundation: git init, .gitignore, generate-env.sh, biome+tsconfig, GHA, README pointer fix, ROADMAP
- [x] 2026-06-07 Session 2 — docs hygiene: HOSTS.md uwh ports added, viewer Quick Link added, Cloudflare TBD resolved (remotely-managed via Zero Trust), uph/upo SSH aliases retired, stale-entries sections removed.

**Carryover from session 2** (not file-edits, needs UI action by you):
- [ ] Tailscale admin console: delete `desktop-t0jdc7e`, `iphone182`, `piotrs-macbook-air`, `piotr-ubuntu` at https://login.tailscale.com/admin/machines
