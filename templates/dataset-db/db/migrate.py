"""Numbered SQL migrations with a ledger, applied through psql (see psql.py).

Files `migrations/NNN_name.sql` run in order, each inside one transaction together with its row in
`<schema>.schema_migrations (filename, checksum, applied_at)`. A file is never applied twice. A file
whose content changed after it was applied stops the run before anything else is applied: write a
new migration instead (files are immutable once applied; expand first, contract later)."""

import argparse
import hashlib
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from . import psql as pg

NAME = re.compile(r"^\d{3}_[a-z0-9_]+\.sql$")
SCHEMA = re.compile(r"^[a-z_][a-z0-9_]*$")


class MigrationError(RuntimeError):
    """The migrations directory or the ledger is not in a state we can safely apply."""


def files(directory: Path) -> list[Path]:
    """Migration files in order; a stray .sql name or a repeated number is an error."""
    paths = sorted(directory.glob("*.sql"))
    bad = [p.name for p in paths if not NAME.match(p.name)]
    if bad:
        raise MigrationError(f"not NNN_name.sql: {', '.join(bad)}")
    numbers = [p.name[:3] for p in paths]
    if len(numbers) != len(set(numbers)):
        raise MigrationError("two migrations share a number")
    return paths


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan(applied: Mapping[str, str], paths: Sequence[Path]) -> tuple[list[Path], list[str]]:
    """(files still to apply, applied files whose content changed since)."""
    pending = [p for p in paths if p.name not in applied]
    changed = [p.name for p in paths if p.name in applied and applied[p.name] != checksum(p)]
    return pending, changed


def ledger_sql(schema: str) -> str:
    return (
        f"create schema if not exists {schema};\n"
        f"create table if not exists {schema}.schema_migrations ("
        "filename text primary key, checksum text not null, applied_at timestamptz not null default now());\n"
    )


def migrate(schema: str, directory: Path, psql: Sequence[str], dry_run: bool = False) -> list[str]:
    """Apply pending migrations; return their file names (with dry_run: only list them)."""
    if not SCHEMA.match(schema):
        raise MigrationError(f"bad schema name: {schema!r}")
    lines = pg.run(ledger_sql(schema) + f"select filename, checksum from {schema}.schema_migrations;", psql)
    applied = dict(line.split("|", 1) for line in lines)
    pending, changed = plan(applied, files(directory))
    if changed:
        raise MigrationError(f"changed after being applied: {', '.join(changed)}")
    for path in [] if dry_run else pending:
        ledger = f"insert into {schema}.schema_migrations values ('{path.name}', '{checksum(path)}');"
        pg.run(f"set lock_timeout = '5s';\nbegin;\n{path.read_text(encoding='utf-8')}\n{ledger}\ncommit;\n", psql)
    return [p.name for p in pending]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply numbered SQL migrations of one schema.")
    parser.add_argument("--schema", required=True)
    parser.add_argument("--dir", type=Path, default=Path("migrations"))
    parser.add_argument("--psql", help=f"psql command (default $DATASET_PSQL or: {pg.DEFAULT})")
    parser.add_argument("--dry-run", action="store_true", help="only list what would be applied")
    args = parser.parse_args(argv)
    try:
        names = migrate(args.schema, args.dir, pg.command(args.psql), args.dry_run)
    except (MigrationError, pg.PsqlError, OSError) as error:
        print(f"✗ {error}", file=sys.stderr)
        return 1
    verb = "would apply" if args.dry_run else "applied"
    print(f"✓ {args.schema}: {verb} {len(names)}" + "".join(f"\n  {n}" for n in names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
