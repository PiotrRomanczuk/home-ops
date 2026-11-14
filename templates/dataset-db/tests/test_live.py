"""The template against a real, throwaway Postgres. Skipped unless $DATASET_TEST_PSQL is set, e.g.

    docker run -d --name dataset-db-test -e POSTGRES_PASSWORD=x postgres:17-alpine
    DATASET_TEST_PSQL="docker exec -i dataset-db-test psql -U postgres -d postgres" \\
      python3 -m unittest discover -s tests -t .

Each test works in its own schema (and read-only role), dropped afterwards."""

import os
import secrets
import shutil
import tempfile
import unittest
from pathlib import Path

from db import load, migrate
from db import psql as pg

TEMPLATE = Path(__file__).resolve().parent.parent
SPEC = os.environ.get("DATASET_TEST_PSQL")


def named_copy(schema: str) -> Path:
    """The template's migrations/ and sql/ in a temp dir, with the schema named (like new-dataset.sh)."""
    target = Path(tempfile.mkdtemp())
    for sub in ("migrations", "sql"):
        shutil.copytree(TEMPLATE / sub, target / sub)
        for path in (target / sub).glob("*.sql"):
            text = path.read_text(encoding="utf-8").replace("__SCHEMA__", schema).replace("__DATE__", "2026-11-14")
            path.write_text(text, encoding="utf-8")
    return target


def item(external_id: str, name: str, fetched_at: str = "2026-11-14T10:00:00+01:00") -> dict[str, object]:
    return {"source": "test", "external_id": external_id, "name": name, "fetched_at": fetched_at}


@unittest.skipUnless(SPEC, "set DATASET_TEST_PSQL to run against a real Postgres")
class LiveTemplateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.psql = pg.command(SPEC)
        self.schema = f"t_{secrets.token_hex(4)}"
        self.dir = named_copy(self.schema)
        self.tables = [f"{self.schema}.items"]

    def tearDown(self) -> None:
        pg.run(f"drop schema if exists {self.schema} cascade; drop role if exists {self.schema}_ro;", self.psql)

    def migrate(self) -> list[str]:
        return migrate.migrate(self.schema, self.dir / "migrations", self.psql)

    def load(self, docs: list[dict[str, object]], dry_run: bool = False) -> tuple[dict[str, int], dict[str, int]]:
        return load.load({"items": docs}, self.dir / "sql/upsert.sql", self.tables, self.psql, dry_run)

    def test_migrations_apply_once(self) -> None:
        self.assertEqual(self.migrate(), ["001_init.sql"])
        self.assertEqual(self.migrate(), [])

    def test_dry_run_runs_no_ddl(self) -> None:
        self.assertEqual(
            migrate.migrate(self.schema, self.dir / "migrations", self.psql, dry_run=True), ["001_init.sql"]
        )
        gone = pg.run(f"select to_regnamespace('{self.schema}') is null;", self.psql)
        self.assertEqual(gone, ["t"])
        self.migrate()
        self.assertEqual(migrate.migrate(self.schema, self.dir / "migrations", self.psql, dry_run=True), [])

    def test_foreign_schema_without_ledger_is_refused(self) -> None:
        pg.run(f"create schema {self.schema}; create table {self.schema}.items (id int);", self.psql)
        for dry_run in (True, False):
            with self.assertRaises(migrate.MigrationError):
                migrate.migrate(self.schema, self.dir / "migrations", self.psql, dry_run)
        tables = pg.run(
            f"select count(*) from information_schema.tables where table_schema = '{self.schema}';", self.psql
        )
        self.assertEqual(tables, ["1"])

    def test_changed_migration_stops_the_run(self) -> None:
        self.migrate()
        path = self.dir / "migrations/001_init.sql"
        path.write_text(path.read_text(encoding="utf-8") + "\n-- edited\n", encoding="utf-8")
        with self.assertRaises(migrate.MigrationError):
            self.migrate()

    def test_load_is_idempotent_and_keeps_first_seen(self) -> None:
        self.migrate()
        before, after = self.load([item("1", "Masło"), item("2", "Ser")])
        self.assertEqual((before[self.tables[0]], after[self.tables[0]]), (0, 2))
        first = pg.query(f"select first_seen_at from {self.schema}.items where external_id = '1'", self.psql)
        _, again = self.load([item("1", "Masło extra", "2026-11-15T10:00:00+01:00")])
        self.assertEqual(again[self.tables[0]], 2)
        rows = pg.query(f"select name, first_seen_at from {self.schema}.items where external_id = '1'", self.psql)
        self.assertEqual(rows[0]["name"], "Masło extra")
        self.assertEqual(rows[0]["first_seen_at"], first[0]["first_seen_at"])

    def test_older_document_never_overwrites_newer(self) -> None:
        self.migrate()
        self.load([item("1", "new", "2026-11-14T11:00:00Z")])
        self.load([item("1", "old", "2026-11-14T10:00:00Z")])
        rows = pg.query(f"select name, raw->>'name' as raw_name, fetched_at from {self.schema}.items", self.psql)
        self.assertEqual([(r["name"], r["raw_name"]) for r in rows], [("new", "new")])
        self.assertTrue(str(rows[0]["fetched_at"]).startswith("2026-11-14T11:00:00"))

    def test_duplicate_key_in_one_batch_keeps_newest(self) -> None:
        self.migrate()
        self.load([item("1", "old", "2026-11-14T10:00:00Z"), item("1", "new", "2026-11-14T11:00:00Z")])
        rows = pg.query(f"select name from {self.schema}.items", self.psql)
        self.assertEqual(rows, [{"name": "new"}])

    def test_dry_run_writes_nothing(self) -> None:
        self.migrate()
        _, would = self.load([item("1", "a")], dry_run=True)
        self.assertEqual(would[self.tables[0]], 1)
        self.assertEqual(load.counts(self.tables, self.psql)[self.tables[0]], 0)

    def test_shrinking_table_aborts_the_load(self) -> None:
        self.migrate()
        self.load([item("1", "a")])
        upsert = self.dir / "sql/upsert.sql"
        upsert.write_text(f"delete from {self.schema}.items;", encoding="utf-8")
        with self.assertRaises(pg.PsqlError):
            self.load([])
        self.assertEqual(load.counts(self.tables, self.psql)[self.tables[0]], 1)

    def test_read_only_role_can_read_views(self) -> None:
        self.migrate()
        rows = pg.query(
            f"select has_table_privilege('{self.schema}_ro', '{self.schema}.items_recent', 'select') as ok", self.psql
        )
        self.assertEqual(rows, [{"ok": True}])


if __name__ == "__main__":
    unittest.main()
