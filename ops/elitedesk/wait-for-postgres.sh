#!/usr/bin/env bash
# wait-for-postgres.sh — ExecStartPre for units that need the compose Postgres.
#
# After a reboot or power cut, docker starts the container but Postgres needs a
# while before it accepts connections; timers with Persistent=true fire at the
# same moment. 2026-10-19: seo-improve ran 10:43 right after uwh came back and
# died on "connection refused" — the weekly PR silently never happened.
# Waits up to WAIT_PG_SECONDS (default 600) for pg_isready inside the container.
set -euo pipefail

CONTAINER="${CONTAINER:-home-ops-postgres-1}"
DB_USER="${DB_USER:-postgres}"
LIMIT="${WAIT_PG_SECONDS:-600}"

for ((waited = 0; waited < LIMIT; waited += 5)); do
  if docker exec "$CONTAINER" pg_isready -U "$DB_USER" -q 2>/dev/null; then
    ((waited > 0)) && printf 'wait-for-postgres: ready after %ss\n' "$waited" >&2
    exit 0
  fi
  sleep 5
done
printf 'wait-for-postgres: %s not ready after %ss\n' "$CONTAINER" "$LIMIT" >&2
exit 1
