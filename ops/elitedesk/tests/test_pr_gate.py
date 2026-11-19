"""Tests for pr_gate.merge_reviewed — feature PRs squash, promotions keep history and the branch."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pr_gate  # noqa: E402


def runner(head: str, calls: list[list[str]], owner: str = 'o'):
    def run(args: list[str]) -> str:
        calls.append(args)
        return json.dumps({'headRefOid': 'abc1234', 'headRefName': head, 'headRepositoryOwner': {'login': owner},
                           'mergeable': 'MERGEABLE', 'statusCheckRollup': []})
    return run


class MergeReviewedTest(unittest.TestCase):
    def merge(self, head: str, sha: str = 'abc1234', head_owner: str = 'o') -> list[str]:
        calls: list[list[str]] = []
        pr_gate.merge_reviewed(runner(head, calls, head_owner), 'o', 'r', '7', sha, lambda _m: None)
        return calls[-1]

    def test_feature_branch_is_squashed_and_deleted(self):
        cmd = self.merge('feat/x')
        self.assertIn('--squash', cmd)
        self.assertIn('--delete-branch', cmd)

    def test_promotion_keeps_history_and_branch(self):
        for head in ('test', 'dev', 'main'):
            cmd = self.merge(head)
            self.assertIn('--merge', cmd)
            self.assertNotIn('--squash', cmd)
            self.assertNotIn('--delete-branch', cmd)

    def test_fork_branch_named_main_is_squashed(self):
        cmd = self.merge('main', head_owner='someone-else')
        self.assertIn('--squash', cmd)
        self.assertNotIn('--merge', cmd)

    def test_owner_match_ignores_case(self):
        self.assertIn('--merge', self.merge('test', head_owner='O'))

    def test_moved_head_is_not_merged(self):
        self.assertEqual(self.merge('feat/x', sha='other99')[:2], ['pr', 'view'])


if __name__ == '__main__':
    unittest.main()
