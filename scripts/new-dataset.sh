#!/usr/bin/env bash
# new-dataset.sh — copy templates/dataset-db into a project package and name its schema.
#
# usage: scripts/new-dataset.sh <schema> <package-dir>
#   <schema>       lower-case Postgres schema name in home_ops (e.g. zakupy)
#   <package-dir>  the project's Python package; gets db/, migrations/, sql/
#
# A copy, not a library: the project owns it afterwards. See templates/dataset-db/README.md.

set -euo pipefail

die() { echo "✗ $*" >&2; exit 1; }

[ $# -eq 2 ] || die "usage: $0 <schema> <package-dir>"
schema="$1"
target="$2"
[[ "$schema" =~ ^[a-z_][a-z0-9_]*$ ]] || die "schema must match ^[a-z_][a-z0-9_]*$: $schema"

src="$(cd "$(dirname "$0")/.." && pwd)/templates/dataset-db"
for sub in db migrations sql; do
  [ -e "$target/$sub" ] && die "$target/$sub already exists — not overwriting"
done

mkdir -p "$target"
cp -R "$src/db" "$src/migrations" "$src/sql" "$target/"
find "$target/db" -name '__pycache__' -type d -prune -exec rm -rf {} +

today="$(date +%F)"
for f in "$target"/migrations/*.sql "$target"/sql/*.sql; do
  sed -e "s/__SCHEMA__/$schema/g" -e "s/__DATE__/$today/g" "$f" > "$f.tmp" && mv "$f.tmp" "$f"
done

echo "✓ dataset-db copied into $target (schema $schema)"
echo "  next: replace the example table in migrations/001_init.sql + sql/upsert.sql,"
echo "  call db.migrate.migrate() and db.load.load() from your sync command,"
echo "  add a vault place note for home_ops.$schema"
