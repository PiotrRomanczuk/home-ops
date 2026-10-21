#!/usr/bin/env bash
# pg-backup.sh — nightly logical backup of the home_ops database -> QNAP NAS.
#
# - Runs `pg_dump -Fc` inside the home-ops-postgres-1 container (no Postgres
#   client install needed on the host).
# - Ships the dump to the NAS over SSH/SCP (same key-auth mechanism already
#   proven by strummy-prod-backup.sh) instead of a CIFS mount — no NAS
#   credentials needed on this host at all.
# - Prunes remote (and local staging) files older than $RETENTION_DAYS.
#
# Designed to be invoked by ops/elitedesk/pg-backup.timer at 04:30 daily, well
# clear of the 02:30-03:00 window used by strummy-prod/studentmanager/stano
# backups so nobody fights over the NAS SSH session.

set -euo pipefail

DEST_HOST="${DEST_HOST:-admin@192.168.1.25}"
NAS_BASE="${NAS_BASE:-/share/MD0_DATA/Backups/home-ops}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
CONTAINER="${CONTAINER:-home-ops-postgres-1}"
DB="${DB:-home_ops}"
DB_USER="${DB_USER:-postgres}"

log() { echo "$(date -Is) $*"; }

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  printf 'container %s is not running\n' "$CONTAINER" >&2
  exit 1
fi

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
ts=$(date -u +%Y%m%dT%H%M%SZ)
DUMP="$WORK/home_ops_${ts}.dump"

docker exec "$CONTAINER" pg_dump -U "$DB_USER" -Fc "$DB" > "$DUMP"
bytes=$(stat -c%s "$DUMP" 2>/dev/null || stat -f%z "$DUMP")
log "dump OK: ${DUMP} (${bytes} bytes)"

ssh -o BatchMode=yes -o ConnectTimeout=15 "$DEST_HOST" "mkdir -p '$NAS_BASE'"
scp -O -q -o BatchMode=yes -o ConnectTimeout=30 "$DUMP" "$DEST_HOST:$NAS_BASE/"

# Prune remote dumps older than RETENTION_DAYS. The QNAP's `find` is BusyBox
# and doesn't support -mtime/-delete, so pull the filename list back to this
# host (GNU date/grep) and issue individual deletes instead — same approach
# as kuma-backup.sh/beszel-backup.sh use for their SMB-based retention.
CUTOFF_EPOCH=$(date -d "-${RETENTION_DAYS} days" +%s)
ssh -o BatchMode=yes -o ConnectTimeout=15 "$DEST_HOST" "ls -1 '$NAS_BASE'" 2>/dev/null \
  | grep -oE 'home_ops_[0-9]{8}T[0-9]{6}Z\.dump' \
  | while read -r fname; do
      fdate=$(echo "$fname" | grep -oE '[0-9]{8}' | head -1)
      fepoch=$(date -d "$fdate" +%s)
      if [ "$fepoch" -lt "$CUTOFF_EPOCH" ]; then
        ssh -o BatchMode=yes -o ConnectTimeout=15 "$DEST_HOST" "rm -f '$NAS_BASE/$fname'"
        log "  pruned remote: $fname"
      fi
    done || log "WARN: NAS retention pass had a non-fatal error"

log "NAS OK: ${DEST_HOST}:${NAS_BASE}/$(basename "$DUMP"); pruned dumps older than ${RETENTION_DAYS} days"
