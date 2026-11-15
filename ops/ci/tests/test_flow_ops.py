"""Tests for ops/ci/flow_ops.py — merge, push (retry, refused workflow change) and deduplicated issues.

Run:
    python3 -m unittest discover -s ops/ci/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from flow_fake import NON_FF, OK, REFUSED, FakeRun, Res, flow, issues, moved_head  # noqa: E402


class AdvanceTest(unittest.TestCase):
    def test_push_then_dispatch_without_token(self):
        run = FakeRun({('git', 'rev-parse'): moved_head('a', 'b')})
        self.assertEqual(flow(run).advance('dev', 'test'), 0)
        self.assertEqual(run.ran('git', 'push')[0][-1], 'HEAD:test')
        self.assertEqual(run.ran('gh', 'workflow', 'run'), [['gh', 'workflow', 'run', 'check.yml', '--ref', 'test']])

    def test_token_push_starts_check_itself(self):
        run = FakeRun({('git', 'rev-parse'): moved_head('a', 'b')})
        self.assertEqual(flow(run, has_token=True).advance('dev', 'test'), 0)
        self.assertEqual(run.ran('gh', 'workflow'), [])

    def test_nothing_new_pushes_nothing(self):
        run = FakeRun({('git', 'rev-parse'): moved_head('a', 'a')})
        self.assertEqual(flow(run).advance('dev', 'test'), 0)
        self.assertEqual(run.ran('git', 'push'), [])

    def test_conflict_files_one_issue(self):
        run = FakeRun({('git', 'merge', '--no-edit'): Res(1, '', 'CONFLICT'),
                       ('gh', 'issue', 'list'): [issues(), issues('flow: dev nie wchodzi czysto na test')]})
        self.assertEqual(flow(run).advance('dev', 'test'), 1)
        self.assertEqual(flow(run).advance('dev', 'test'), 1)
        self.assertEqual(len(run.ran('gh', 'issue', 'create')), 1)
        self.assertIn('back-to-dev', run.ran('gh', 'issue', 'create')[0])
        self.assertEqual(len(run.ran('git', 'merge', '--abort')), 2)

    def test_moved_target_is_merged_and_pushed_again(self):
        run = FakeRun({('git', 'rev-parse'): moved_head('a', 'b'), ('git', 'push'): [NON_FF, OK]})
        self.assertEqual(flow(run).advance('dev', 'test'), 0)
        self.assertEqual(len(run.ran('git', 'push')), 2)
        self.assertIn(['git', 'merge', '--no-edit', 'origin/test'], run.calls)

    def test_gives_up_after_one_retry(self):
        run = FakeRun({('git', 'rev-parse'): moved_head('a', 'b'), ('git', 'push'): NON_FF})
        self.assertEqual(flow(run).advance('dev', 'test'), 1)
        self.assertEqual(len(run.ran('git', 'push')), 2)
        self.assertEqual(run.ran('gh', 'workflow'), [])

    def test_workflow_change_without_token_files_one_issue_with_manual_push(self):
        title = 'flow: dev → test wymaga ręcznego pushu (zmiana w workflows)'
        run = FakeRun({('git', 'rev-parse'): moved_head('a', 'b', 'a', 'b'), ('git', 'push'): REFUSED,
                       ('gh', 'issue', 'list'): [issues(), issues(title)]})
        self.assertEqual(flow(run).advance('dev', 'test'), 1)
        self.assertEqual(flow(run).advance('dev', 'test'), 1)
        created = run.ran('gh', 'issue', 'create')
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0][4], title)
        self.assertIn('git push origin origin/dev:test', created[0][6])
        self.assertEqual(len(run.ran('git', 'push')), 2)  # no retry on a refusal
        self.assertEqual(run.ran('gh', 'workflow'), [])

    def test_promote_merges_the_green_sha_not_the_dev_tip(self):
        run = FakeRun({('git', 'rev-parse'): moved_head('a', 'b')})
        self.assertEqual(flow(run).advance('dev', 'test', sha='green1'), 0)
        self.assertEqual(run.ran('git', 'merge')[0], ['git', 'merge', '--no-edit', 'green1'])
        self.assertNotIn(['git', 'merge', '--no-edit', 'origin/dev'], run.calls)

    def test_green_sha_missing_from_the_clone_promotes_nothing(self):
        run = FakeRun({('git', 'cat-file'): Res(1, '', 'bad object'), ('git', 'rev-parse'): moved_head('a', 'b')})
        self.assertEqual(flow(run).advance('dev', 'test', sha='gone'), 0)
        self.assertEqual(run.ran('git', 'merge'), [])
        self.assertEqual(run.ran('git', 'push'), [])

    def test_refused_push_names_the_sha_in_the_manual_command(self):
        run = FakeRun({('git', 'rev-parse'): moved_head('a', 'b'), ('git', 'push'): REFUSED})
        self.assertEqual(flow(run).advance('dev', 'test', sha='green1'), 1)
        self.assertIn('git push origin green1:test', run.ran('gh', 'issue', 'create')[0][6])


if __name__ == '__main__':
    unittest.main()
