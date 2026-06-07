---
created: 2026-06-07
updated: 2026-06-07
---

# home-ops

Centralised structured logs + GPU job queue for the home network. Runs on `uwh` as a docker-compose stack. Independent of any project.

## Stack

| Service | Port (uwh) | What |
| --- | --- | --- |
| postgres | `127.0.0.1:64422` | DB `home_ops`. Tables: `host_logs`, `gpu_jobs`. |
| ingest | `0.0.0.0:64421` | Hono HTTP API. `POST /api/ingest`, `GET/POST /api/jobs`. |
| viewer | (served by ingest on :64421 until Phase C) | Standalone Next.js log viewer — Phase C will move it to its own service on :64420. |

Auth on ingest = `X-Ingest-Token` header. Auth on viewer = `LOGS_PASSWORD`. Tailnet-only reachability via `tailscale serve`.

## Per-host agents

| Host | Agent | Captures |
| --- | --- | --- |
| `wfh` | `agents/wfh/ollama-watcher.py` (WinSW service) | Ollama GIN + server logs from `C:\ProgramData\Ollama-Service\Ollama.err.log` |
| `wfh` | `scheduler/gpu-scheduler.py` (WinSW service) | Gaming-detect state + GPU job consumer |
| `uwh` | `agents/uwh/uwh-watcher.py` (systemd user) | journald (cloudflared, docker, ssh, kernel) + named docker container logs |
| `rpi` | `agents/rpi/rpi-watcher.py` (systemd user) | Kuma + Beszel container logs, syslog errors |

## Deploy (uwh)

```bash
# Initial setup (once)
ssh uwh
git clone git@github.com:PiotrRomanczuk/home-ops.git ~/logs-stack
cd ~/logs-stack
./scripts/generate-env.sh        # generates ./.env with strong secrets, prompts for LOGS_PASSWORD
docker compose up -d

# Subsequent deploys (after `git push` from Mac)
ssh uwh "cd ~/logs-stack && git pull && docker compose up -d --build"
```

## Verify

```bash
# ingest is up
curl -s http://localhost:64421/ | jq .

# health (auth required)
curl -s http://localhost:64421/api/health -H "X-Ingest-Token: $INGEST_TOKEN" | jq .

# manual event
curl -s -X POST http://localhost:64421/api/ingest \
  -H "X-Ingest-Token: $INGEST_TOKEN" -H "content-type: application/json" \
  -d '{"host":"test","source":"manual","level":"info","message":"hello"}' | jq .

# read it back
docker exec home-ops-postgres-1 psql -U postgres -d home_ops \
  -c "select id, ts, host, source, message from host_logs order by id desc limit 5;"
```

## Schema

See `postgres/migrations/001_init.sql`. `host_logs` is indexed by `ts`, `host`, `source`, alarm-level. `gpu_jobs` is indexed by `(priority DESC, created_at ASC) WHERE status='queued'` so `claim_job` is O(1).

## Retention

`SELECT prune_host_logs(30)` removes `host_logs` rows older than 30 days. Run via cron on uwh nightly.

## Related

- `ROADMAP.md` — working TODO list across all sessions.
- `~/Desktop/MainCV/infrastructure/HOSTS.md` — host inventory.
- `~/Desktop/MainCV/infrastructure/home-ops-logger-plan.md` — original architecture plan + Phase B-F status (will be archived once Phase F is green).
- `~/.claude/CLAUDE.md` — SSH persistence rule (any long-running remote process must be detached).
- `~/.claude/plans/i-have-few-computers-fluttering-abelson.md` — explicit "no Loki/Grafana" decision this design respects.
- `~/.claude/plans/analyze-this-folder-and-curious-shamir.md` — improvement plan (decisions log).
