"""Tests for ops/ci/flow_paths.py — which PRs into `test` may merge on their own.

Run:
    python3 -m unittest discover -s ops/ci/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flow_paths import is_test_path, tests_only  # noqa: E402


class FlowPathsTest(unittest.TestCase):
    def test_test_paths(self):
        for p in ('ingest/src/routes/__tests__/claude.test.ts', 'agents/tests/test_redact.py', 'e2e/login.spec.ts',
                  'ingest/web/src/lib/journal.test.ts', 'ops/elitedesk/tests/fixtures/sample.json', 'test_x.py'):
            self.assertTrue(is_test_path(p), p)

    def test_code_paths(self):
        for p in ('ingest/src/routes/claude.ts', 'agents/redact.py', '.github/workflows/check.yml',
                  'postgres/migrations/032_mac_journal.sql', 'ingest/src/testing.ts', 'docs/tests.md', 'contest.py'):
            self.assertFalse(is_test_path(p), p)

    def test_tests_only_needs_every_file_to_be_a_test(self):
        self.assertTrue(tests_only(['a/tests/test_a.py', 'b/__tests__/b.test.ts', '']))
        self.assertFalse(tests_only(['a/tests/test_a.py', 'a/code.py']))
        self.assertFalse(tests_only([]))


if __name__ == '__main__':
    unittest.main()
