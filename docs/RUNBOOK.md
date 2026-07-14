---
created: 2026-07-14
updated: 2026-07-14
---

# home-ops — operations runbook

Day-to-day operational procedures: deploy, migrations, verification, retention,
backups, and monitoring. For *what the system is* and *why*, read
[`CONTEXT.md`](CONTEXT.md); for the component map, [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Deploy (elitedesk)

```bash
# Initial setup (once)
ssh elitedesk
git clone git@github.com:PiotrRomanczuk/home-ops.git ~/logs-stack
cd ~/logs-stack
./scripts/generate-env.sh        # generates ./.env with strong secrets, prompts for LOGS_PASSWORD
docker compose up -d

# Subsequent deploys (after `git push`)
ssh elitedesk "cd ~/logs-stack && git pull && docker compose up -d --build"
```

Per-host agents run as systemd `--user` services (Linux) or WinSW services
(Windows). They run from a deployed copy, not the repo checkout — pulling the
repo does not update a running agent; copy the updated file into place and
restart the service.

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
`CREATE OR REPLACE FUNCTION`, `cron.schedule(jobname, …)`), so re-running is safe.

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

See `postgres/migrations/001_init.sql` for the base tables (`host_logs`,
`gpu_jobs`) and `002_pg_cron.sql` for the scheduled prunes. `host_logs` is
indexed by `ts`, `host`, `source`, and alarm level. `gpu_jobs` is indexed by
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
timer, with 14-day retention.

> **Current state:** dumps land in a **local** directory on elitedesk
> (`~/backups/home-ops/`), not the NAS. The unit is written to target the NAS
> `monitoring-backup` SMB share (`BACKUP_DIR=/mnt/nas/monitoring-backup/home-ops`)
> — installing the NAS mount is a pending hardening step so backups survive
> loss of the host. See `ops/elitedesk/README.md` for the fstab entry.

```bash
# On elitedesk
systemctl --user list-timers --all | grep pg-backup
ls -lh ~/backups/home-ops/          # current (local) destination
```

## Monitoring

Uptime Kuma on the Pi probes `/api/health` and alerts on repeated failure. To
configure a monitor:

1. Open Kuma → **Add New Monitor**.
2. Type: HTTP(s). Friendly name: `home-ops ingest`.
3. URL: `http://elitedesk.<tailnet>.ts.net:64421/api/health`.
4. Heartbeat interval: `60`. Retries: `2`. Heartbeat retry interval: `30`.
5. Method: GET. Body / headers: blank.
6. Accepted status codes: `200-299`.
7. Keyword search (under HTTP Options): `"ok":true`.
8. Notifications: attach the existing channel.
