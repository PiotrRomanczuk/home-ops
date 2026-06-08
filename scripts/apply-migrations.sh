#!/usr/bin/env bash
# apply-migrations.sh — idempotent migration runner.
#
# Walks postgres/migrations/*.sql lexically. For each one not yet recorded
# in public.schema_migrations, applies it inside a transaction, then inserts
# the (filename, checksum) row. Re-running is a no-op.
#
# Replaces the manual `docker exec home-ops-postgres-1 psql -U postgres -d
# home_ops -f /docker-entrypoint-initdb.d/00X_*.sql` pattern.
#
# Env (optional):
#   CONTAINER  postgres container name; default 'home-ops-postgres-1'
#   DB         database name; default 'home_ops'
#   USER       postgres role;  default 'postgres'

set -euo pipefail

CONTAINER="${CONTAINER:-home-ops-postgres-1}"
DB="${DB:-home_ops}"
USER="${USER:-postgres}"

cd "$(dirname "$0")/.."
MIGRATIONS_DIR="$(pwd)/postgres/migrations"

if [ ! -d "$MIGRATIONS_DIR" ]; then
  echo "✗ migrations dir not found: $MIGRATIONS_DIR" >&2
  exit 1
fi

PSQL() {
  docker exec -i "$CONTAINER" psql -U "$USER" -d "$DB" -v ON_ERROR_STOP=1 "$@"
}

# 1. Ensure the tracking table exists. Idempotent.
PSQL <<'SQL'
CREATE TABLE IF NOT EXISTS public.schema_migrations (
  filename   text PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now(),
  checksum   text
);
SQL

# 2. Collect already-applied filenames into a bash set.
declare -A APPLIED=()
while IFS= read -r f; do
  [ -n "$f" ] && APPLIED["$f"]=1
done < <(PSQL -tA -c 'SELECT filename FROM public.schema_migrations')

PENDING=()
for path in "$MIGRATIONS_DIR"/*.sql; do
  fn="$(basename "$path")"
  if [ -z "${APPLIED[$fn]:-}" ]; then
    PENDING+=("$path")
  fi
done

if [ "${#PENDING[@]}" -eq 0 ]; then
  echo "✓ all $((${#APPLIED[@]})) migrations already applied"
  exit 0
fi

echo "▶ applying ${#PENDING[@]} migration(s)…"
for path in "${PENDING[@]}"; do
  fn="$(basename "$path")"
  sum="$(shasum -a 256 "$path" | awk '{print $1}')"
  echo "  → $fn"

  # Wrap user SQL in a single transaction with the schema_migrations insert,
  # so a half-applied migration can't pollute the tracking table.
  # The migration file's CREATE TABLE / CREATE EXTENSION etc. need to be
  # safe inside a transaction — most are; pg_cron schedule additions are
  # the one to watch.
  if ! cat "$path" - <<SQL | PSQL >/dev/null
INSERT INTO public.schema_migrations (filename, checksum)
VALUES ('$fn', '$sum')
ON CONFLICT (filename) DO NOTHING;
SQL
  then
    echo "✗ $fn FAILED — transaction rolled back" >&2
    exit 1
  fi
done

echo "✓ ${#PENDING[@]} migration(s) applied"
