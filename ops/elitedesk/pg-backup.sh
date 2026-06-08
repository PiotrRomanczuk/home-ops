#!/usr/bin/env bash
# pg-backup.sh — nightly logical backup of the home_ops database.
#
# - Runs `pg_dump -Fc` inside the home-ops-postgres-1 container (no Postgres
#   client install needed on the host).
# - Writes a date-stamped .dump file to $BACKUP_DIR.
# - Prunes files older than $RETENTION_DAYS.
#
# Designed to be invoked by ops/elitedesk/pg-backup.timer at 04:30 daily, 30 min
# after Kuma's 04:00 backup so they don't fight for the SMB mount.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/mnt/nas/monitoring-backup/home-ops}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
CONTAINER="${CONTAINER:-home-ops-postgres-1}"
DB="${DB:-home_ops}"
DB_USER="${DB_USER:-postgres}"

if [[ ! -d "$BACKUP_DIR" ]]; then
  printf 'BACKUP_DIR does not exist: %s\n' "$BACKUP_DIR" >&2
  printf 'Mount the NAS share first — see ops/elitedesk/README.md for the fstab entry.\n' >&2
  exit 1
fi

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  printf 'container %s is not running\n' "$CONTAINER" >&2
  exit 1
fi

ts=$(date -u +%Y%m%dT%H%M%SZ)
dest="${BACKUP_DIR}/home_ops_${ts}.dump"

docker exec "$CONTAINER" pg_dump -U "$DB_USER" -Fc "$DB" > "$dest.tmp"
mv "$dest.tmp" "$dest"

# Prune old dumps. -mtime +N keeps the file if mtime is <= N days; +14 means
# "older than 14 full 24h windows" → on day-15 the first one disappears.
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'home_ops_*.dump' -mtime "+${RETENTION_DAYS}" -delete

bytes=$(stat -c%s "$dest" 2>/dev/null || stat -f%z "$dest")
printf 'wrote %s (%s bytes); pruned dumps older than %d days from %s\n' \
  "$dest" "$bytes" "$RETENTION_DAYS" "$BACKUP_DIR"
