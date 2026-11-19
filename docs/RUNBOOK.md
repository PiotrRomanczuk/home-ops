---
created: 2026-07-14
updated: 2026-11-15
---

# home-ops — operations runbook

Day-to-day operational procedures: deploy, migrations, verification, retention,
backups, and monitoring. For *what the system is* and *why*, read
[`CONTEXT.md`](CONTEXT.md); for the component map, [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Branches (since 2026-11-14)

`dev` (default, PRs land here) → `test` (automatic, integration and end-to-end tests) → `main` (deployed).
Automation: `.github/workflows/flow.yml` (steps in `ops/ci/flow_cli.py`); decision:
`docs/adr/2026-11-14-three-branches.md`. Deploy steps below still pull `main`. Labels: `back-to-dev` = the
test stage failed, fix through `dev`.

- **Stacked PRs**: a PR whose base is another feature branch gets CI too. When the lower PR merges, retarget
  the next one to `dev` (`gh pr edit <n> --base dev`), never to `main`.
- **`FLOW_TOKEN`** (repo secret, optional but needed for a flow without manual steps): a fine-grained PAT
  (or GitHub App) for this repository only, permissions *Contents*, *Pull requests*, *Issues* and
  *Workflows*: read and write. With it the flow's pushes start `check` themselves and may carry changes to
  `.github/workflows/`. Without it the flow uses `GITHUB_TOKEN`: it dispatches `check` after each push, a
  promotion that changes `.github/workflows/` is refused and files one issue
  "flow: dev → test wymaga ręcznego pushu (zmiana w workflows)" — push by hand from the Mac
  (`git fetch origin && git push origin origin/dev:test`), then close the issue. If Actions may not open
  pull requests (Settings → Actions → General), the release step files one issue
  "release: test → main: otwórz PR ręcznie" with the compare link, refreshed on every green `test`.
- **Concurrency**: `promote`, `tester-pr` and `sync` share the group `flow-write`. GitHub keeps one pending
  job per group, so with three writers queued at once the middle one is dropped; every job works from the
  branch state, so the next green run repeats it (a dropped `tester-pr` needs a re-run of its `check`).

### First release `test` → `main` (once, after the three-branch PR lands on `dev`)

`pr-decide` on uwh runs `pr_gate.py` from `~/code/logs-stack` (a `main` checkout). Until `main` has the
version that merges promotions with a merge commit, a "Scal" on "Dziś" would squash `test` into `main` and
delete the `test` branch. So the first release is merged by hand, once:

1. Protect `dev` and `test` first (ruleset: *Restrict deletions* + *Block force pushes*, nothing else, so the
   flow can still push).
2. Wait for the PR "release: test → main" (or open it from the compare link in the release issue) and
   for `pr-review` on its head.
3. Merge it yourself with a merge commit, keeping the branch:
   `! gh pr merge <n> --repo PiotrRomanczuk/home-ops --merge` (no `--squash`, no `--delete-branch`).
4. Pull on uwh: `ssh uwh "cd ~/code/logs-stack && git checkout main && git pull --ff-only"`. From now on "Dziś"
   merges promotions with a merge commit and keeps the branch.
5. `flow / sync` merges `main` back into `dev`; check that `test` still exists.

## Deploy (elitedesk)

```bash
# Initial setup (once)
ssh elitedesk
git clone -b main git@github.com:PiotrRomanczuk/home-ops.git ~/code/logs-stack   # default branch is dev
cd ~/code/logs-stack
./scripts/generate-env.sh        # generates ./.env with strong secrets, prompts for LOGS_PASSWORD
docker compose up -d

# Subsequent deploys (after `git push`)
ssh elitedesk "cd ~/code/logs-stack && git pull && docker compose up -d --build"
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

> **Current state (2026-10-21):** dumps go straight to the NAS over scp
> (`admin@192.168.1.25:/share/MD0_DATA/Backups/home-ops/`), 14 days kept there;
> nothing stays on elitedesk. See `ops/elitedesk/README.md`.

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
