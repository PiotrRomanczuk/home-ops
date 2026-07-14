---
created: 2026-06-07
updated: 2026-06-07
---

# home-ops

Centralised structured logs + GPU job queue for the home network. Runs on `elitedesk` as a docker-compose stack. Independent of any project.

## Stack

| Service | Port (elitedesk) | What |
| --- | --- | --- |
| postgres | `127.0.0.1:64422` | DB `home_ops`. Tables: `host_logs`, `gpu_jobs`. |
| ingest | `0.0.0.0:64421` | Hono HTTP API. `POST /api/ingest`, `GET/POST /api/jobs`. |
| viewer | (served by ingest on :64421) | Static Vite (React) log viewer SPA, served by the ingest API from `ingest/public/`. |

Auth on ingest = `X-Ingest-Token` header. Auth on viewer = `LOGS_PASSWORD`. Tailnet-only reachability via `tailscale serve`.

## Per-host agents

| Host | Agent | Captures |
| --- | --- | --- |
| `win10` | `agents/win10/ollama-watcher.py` (WinSW service) | Ollama GIN + server logs from `C:\ProgramData\Ollama-Service\Ollama.err.log` |
| `win10` | `scheduler/gpu-scheduler.py` (WinSW service) | Gaming-detect state + GPU job consumer |
| `elitedesk` | `agents/elitedesk/elitedesk-watcher.py` (systemd user) | journald (cloudflared, docker, ssh, kernel) + named docker container logs |
| `rpi` | `agents/rpi/rpi-watcher.py` (systemd user) | Kuma + Beszel container logs, syslog errors |

## Deploy (elitedesk)

```bash
# Initial setup (once)
ssh elitedesk
git clone git@github.com:PiotrRomanczuk/home-ops.git ~/logs-stack
cd ~/logs-stack
./scripts/generate-env.sh        # generates ./.env with strong secrets, prompts for LOGS_PASSWORD
docker compose up -d

# Subsequent deploys (after `git push` from Mac)
ssh elitedesk "cd ~/logs-stack && git pull && docker compose up -d --build"
```

### Applying new migrations on an existing deploy

The `postgres/migrations/` directory mounts read-only into the container at
`/docker-entrypoint-initdb.d/`, but those scripts only auto-run on a fresh
initdb (empty `pgdata`). On an existing deploy, run new migrations by hand:

```bash
# Replace 002_pg_cron.sql with whichever new migration you're applying.
ssh elitedesk "docker exec home-ops-postgres-1 psql -U postgres -d home_ops \
  -f /docker-entrypoint-initdb.d/002_pg_cron.sql"
```

All shipped migrations are idempotent (`CREATE … IF NOT EXISTS`,
`CREATE OR REPLACE FUNCTION`, `cron.schedule(jobname, …)`), so re-running is
safe.

## Verify

```bash
# ingest is up
curl -s http://localhost:64421/ | jq .

# health (public, no auth) — also wired into the docker healthcheck
curl -s http://localhost:64421/api/health | jq .

# manual event
curl -s -X POST http://localhost:64421/api/ingest \
  -H "X-Ingest-Token: $INGEST_TOKEN" -H "content-type: application/json" \
  -d '{"host":"test","source":"manual","level":"info","message":"hello"}' | jq .

# read it back
docker exec home-ops-postgres-1 psql -U postgres -d home_ops \
  -c "select id, ts, host, source, message from host_logs order by id desc limit 5;"

# both containers healthy?
docker compose ps    # ingest + postgres should both show (healthy)
```

## Schema

See `postgres/migrations/001_init.sql` for the tables (`host_logs`, `gpu_jobs`)
and `002_pg_cron.sql` for the scheduled prunes. `host_logs` is indexed by
`ts`, `host`, `source`, alarm-level. `gpu_jobs` is indexed by
`(priority DESC, created_at ASC) WHERE status='queued'` so `claim_job` is O(1).

## Retention

pg_cron runs nightly inside the postgres container (no host-level cron):

- `prune_host_logs(30)` — drops `host_logs` rows older than 30 days. Daily at 04:00 UTC.
- `prune_done_gpu_jobs(30)` — drops `gpu_jobs` rows with `status='done'` older than 30 days. Daily at 04:15 UTC. Failed/cancelled jobs are kept forever for postmortem.

```bash
# Inspect the schedule
docker exec home-ops-postgres-1 psql -U postgres -d home_ops -c \
  'SELECT jobid, schedule, jobname, command FROM cron.job;'
```

## Backups

`pg_dump -Fc` runs nightly at 04:30 (elitedesk local time) via a systemd `--user`
timer, writing to the NAS `monitoring-backup` SMB share with 14-day retention.
See `ops/elitedesk/README.md` for installation and the NAS mount prerequisite.

```bash
# On elitedesk, after installing the timer
systemctl --user list-timers --all | grep pg-backup
ls -lh /mnt/nas/monitoring-backup/home-ops/
```

## Monitoring

Kuma on the Pi probes `http://elitedesk.<tailnet>.ts.net:64421/api/health`
every 60 s; alerts on 2 consecutive failures. To configure:

1. Open Kuma → **Add New Monitor**.
2. Type: HTTP(s). Friendly name: `home-ops ingest`.
3. URL: `http://elitedesk.<tailnet>.ts.net:64421/api/health`.
4. Heartbeat interval: `60`. Retries: `2`. Heartbeat retry interval: `30`.
5. Method: GET. Body / headers: blank.
6. Accepted status codes: `200-299`.
7. Keyword search (under HTTP Options): `"ok":true`.
8. Notifications: attach the existing channel (same as other monitors).

## Related

- `mcp/README.md` — MCP server for Claude Desktop / Claude Code. Lets an LLM client read home-ops state and submit jobs to the local qwen3 queue via MCP tools.
- `docs/ARCHITECTURE.md` — high-level diagram of what runs where and how the pieces wire together. Renders on GitHub.
- `docs/CONTEXT.md` — **read this first** when starting any work on home-ops. Project identity, data model, well-known `data` keys, use cases, future direction.
- `docs/DESIGN_BRIEF.md` — UI design brief (for Phase C standalone viewer).
- `docs/adr/` — formal architectural decision records.
- `ROADMAP.md` — working TODO list across all sessions.
- `~/Desktop/MainCV/infrastructure/HOSTS.md` — host inventory.
- `~/Desktop/MainCV/infrastructure/home-ops-logger-plan.md` — original architecture plan + Phase B-F status (will be archived once Phase F is green).
- `~/.claude/CLAUDE.md` — SSH persistence rule (any long-running remote process must be detached).
- `~/.claude/plans/i-have-few-computers-fluttering-abelson.md` — explicit "no Loki/Grafana" decision this design respects.
- `~/.claude/plans/analyze-this-folder-and-curious-shamir.md` — improvement plan (decisions log).
