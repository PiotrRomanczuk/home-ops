"""Template helpers without a database: file order and names, the plan, the generated SQL."""

import json
import tempfile
import unittest
from pathlib import Path

from db import load, migrate


def write(directory: Path, name: str, text: str = "select 1;") -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


class MigrationFilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())

    def test_files_in_numeric_order(self) -> None:
        write(self.dir, "002_b.sql")
        write(self.dir, "001_a.sql")
        self.assertEqual([p.name for p in migrate.files(self.dir)], ["001_a.sql", "002_b.sql"])

    def test_bad_name_is_refused(self) -> None:
        write(self.dir, "1_a.sql")
        with self.assertRaises(migrate.MigrationError):
            migrate.files(self.dir)

    def test_repeated_number_is_refused(self) -> None:
        write(self.dir, "001_a.sql")
        write(self.dir, "001_b.sql")
        with self.assertRaises(migrate.MigrationError):
            migrate.files(self.dir)

    def test_plan_splits_pending_and_changed(self) -> None:
        a = write(self.dir, "001_a.sql", "create table a ();")
        b = write(self.dir, "002_b.sql")
        applied = {"001_a.sql": "not-the-checksum"}
        pending, changed = migrate.plan(applied, [a, b])
        self.assertEqual([p.name for p in pending], ["002_b.sql"])
        self.assertEqual(changed, ["001_a.sql"])

    def test_unchanged_applied_file_is_neither(self) -> None:
        a = write(self.dir, "001_a.sql")
        self.assertEqual(migrate.plan({"001_a.sql": migrate.checksum(a)}, [a]), ([], []))

    def test_bad_schema_name_is_refused_before_psql(self) -> None:
        with self.assertRaises(migrate.MigrationError):
            migrate.migrate("Drop table;", self.dir, ["false"])


class LoadScriptTest(unittest.TestCase):
    def test_copy_block_is_one_line_per_document(self) -> None:
        block = load.copy_block("incoming_items", [{"name": "Ser żółty | 400 g"}, {"name": "b"}])
        lines = block.splitlines()
        self.assertTrue(lines[0].startswith("copy incoming_items (doc) from stdin"))
        self.assertEqual(json.loads(lines[1])["name"], "Ser żółty | 400 g")
        self.assertEqual(lines[-1], "\\.")
        self.assertEqual(len(lines), 4)

    def test_guard_names_every_table(self) -> None:
        sql = load.guard_sql({"s.items": 10, "s.runs": 2})
        self.assertIn("(select count(*) from s.items) < 10", sql)
        self.assertIn("(select count(*) from s.runs) < 2", sql)

    def test_dry_run_rolls_back(self) -> None:
        script = load.build_script({"items": []}, "select 1;", {"s.items": 0}, dry_run=True)
        self.assertTrue(script.rstrip().endswith("rollback;"))
        self.assertIn("create temp table incoming_items (doc jsonb) on commit drop;", script)

    def test_read_jsonl_skips_blank_lines_and_missing_files(self) -> None:
        path = Path(tempfile.mkdtemp()) / "x.jsonl"
        self.assertEqual(load.read_jsonl(path), [])
        path.write_text('{"a": 1}\n\n{"a": 2}\n', encoding="utf-8")
        self.assertEqual(load.read_jsonl(path), [{"a": 1}, {"a": 2}])


if __name__ == "__main__":
    unittest.main()
