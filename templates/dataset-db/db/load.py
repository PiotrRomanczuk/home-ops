"""Load JSON documents into the schema in one transaction, through psql (see psql.py).

Each input becomes the temp table `incoming_<name> (doc jsonb)`, filled with COPY; the project's
upsert SQL then moves the documents into its tables. Before committing, the row count of every
watched table is compared with the count before the load: a table that shrank aborts the whole
load (rows are never deleted). With dry_run the transaction is rolled back, so the counts printed
are what the load would leave behind."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from . import psql as pg

# CSV mode with quote and delimiter characters json.dumps never emits: each line arrives as one value.
COPY = "copy {table} (doc) from stdin with (format csv, quote e'\\x01', delimiter e'\\x02');"


def read_jsonl(path: Path) -> list[dict[str, object]]:
    """Every JSON object line of `path` (blank lines skipped); a missing file gives nothing."""
    if not path.is_file():
        return []
    rows = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return [row for row in rows if isinstance(row, dict)]


def copy_block(table: str, docs: Sequence[Mapping[str, object]]) -> str:
    lines = "".join(json.dumps(doc) + "\n" for doc in docs)  # ASCII-only JSON, one line each
    return f"{COPY.format(table=table)}\n{lines}\\.\n"


def counts_sql(tables: Sequence[str]) -> str:
    return "select " + ", ".join(f"(select count(*) from {t})" for t in tables) + ";"


def guard_sql(before: Mapping[str, int]) -> str:
    """A DO block that raises when any table holds fewer rows than `before`."""
    checks = "".join(
        f"  if (select count(*) from {t}) < {n} then raise exception 'rows disappeared from {t}'; end if;\n"
        for t, n in before.items()
    )
    return f"do $$ begin\n{checks}end $$;\n"


def build_script(
    incoming: Mapping[str, Sequence[Mapping[str, object]]], upsert: str, before: Mapping[str, int], dry_run: bool
) -> str:
    temp = [f"create temp table incoming_{name} (doc jsonb) on commit drop;" for name in incoming]
    copies = [copy_block(f"incoming_{name}", docs) for name, docs in incoming.items()]
    end = "rollback;" if dry_run else "commit;"
    return "\n".join(["begin;", *temp, *copies, upsert, guard_sql(before), counts_sql(list(before)), end, ""])


def counts(tables: Sequence[str], psql: Sequence[str]) -> dict[str, int]:
    values = pg.run(counts_sql(tables), psql)[-1].split("|")
    return dict(zip(tables, map(int, values), strict=True))


def load(
    incoming: Mapping[str, Sequence[Mapping[str, object]]],
    upsert_path: Path,
    tables: Sequence[str],
    psql: Sequence[str],
    dry_run: bool = False,
) -> tuple[dict[str, int], dict[str, int]]:
    """Run the load; return (row counts before, row counts after) of the watched tables."""
    before = counts(tables, psql)
    out = pg.run(build_script(incoming, upsert_path.read_text(encoding="utf-8"), before, dry_run), psql)
    after = dict(zip(tables, map(int, out[-1].split("|")), strict=True))
    return before, after
