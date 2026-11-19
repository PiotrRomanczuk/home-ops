#!/usr/bin/env python3
"""flow_paths.py — does a change touch only test files?

Used by .github/workflows/flow.yml: a PR into `test` that only adds or changes
tests (the tester's work) may merge on its own; anything else waits for a human.

    gh pr view 12 --json files --jq '.files[].path' | python3 ops/ci/flow_paths.py   # exit 0 = tests only
"""
from __future__ import annotations

import re
import sys

TEST_DIRS = {'tests', '__tests__', 'e2e', 'test', 'fixtures'}
TEST_FILE = re.compile(r'(^test_.+\.py$)|(\.(test|spec)\.[cm]?[jt]sx?$)')


def is_test_path(path: str) -> bool:
    parts = path.strip().split('/')
    return bool(set(parts[:-1]) & TEST_DIRS) or bool(TEST_FILE.search(parts[-1]))


def tests_only(paths: list[str]) -> bool:
    paths = [p for p in paths if p.strip()]
    return bool(paths) and all(is_test_path(p) for p in paths)


if __name__ == '__main__':
    sys.exit(0 if tests_only(sys.stdin.read().splitlines()) else 1)
