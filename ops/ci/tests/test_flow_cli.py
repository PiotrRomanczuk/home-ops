"""Tests for ops/ci/flow_cli.py — the tester PR into test and the release PR test → main.

Run:
    python3 -m unittest discover -s ops/ci/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flow_cli import release, tester  # noqa: E402
from flow_fake import NO_PR, OK, FakeRun, Res, flow, issues, moved_head  # noqa: E402


class TesterTest(unittest.TestCase):
    def answers(self, files: str) -> dict:
        return {('gh', 'pr', 'list'): Res(0, json.dumps([{'number': 5, 'headRefOid': 'other'},
                                                        {'number': 7, 'headRefOid': 'abc'}]), ''),
                ('gh', 'pr', 'view'): Res(0, files, ''), ('git', 'rev-parse'): moved_head('a', 'b')}

    def test_tests_only_pr_merges_and_flows_back_to_dev(self):
        run = FakeRun(self.answers('ops/ci/tests/test_x.py\n'))
        self.assertEqual(tester(flow(run), 'abc'), 0)
        verbs = [c[:3] for c in run.calls if c[0] in ('git', 'gh') and c[1] in ('checkout', 'pr', 'push', 'merge')]
        self.assertEqual(verbs, [['gh', 'pr', 'list'], ['gh', 'pr', 'view'], ['git', 'checkout', '-B'],
                                 ['gh', 'pr', 'merge'], ['git', 'merge', '--no-edit'], ['git', 'push', 'origin']])
        self.assertIn('--match-head-commit', run.ran('gh', 'pr', 'merge')[0])
        self.assertEqual(run.ran('git', 'push')[0][-1], 'HEAD:dev')

    def test_code_pr_waits_for_a_human(self):
        run = FakeRun(self.answers('ops/ci/flow_ops.py\nops/ci/tests/test_x.py\n'))
        self.assertEqual(tester(flow(run), 'abc'), 0)
        self.assertEqual(run.ran('gh', 'pr', 'merge'), [])

    def test_unknown_sha_is_ignored(self):
        run = FakeRun(self.answers('ops/ci/tests/test_x.py\n'))
        self.assertEqual(tester(flow(run), 'zzz'), 0)
        self.assertEqual(run.ran('gh', 'pr', 'view'), [])


class ReleaseTest(unittest.TestCase):
    def answers(self, **over: Res | list[Res]) -> dict:
        base = {('git', 'rev-list', '--count', 'origin/main..HEAD'): Res(0, '3\n', ''),
                ('git', 'rev-list', '--count', '--no-merges'): Res(0, '2\n', ''),
                ('git', 'diff', '--quiet'): Res(1, '', ''),
                ('git', 'log'): Res(0, '- feat: a\n- fix: b\n', ''),
                ('gh', 'pr', 'list'): Res(0, '[]', '')}
        return {**base, **{tuple(k.split()): v for k, v in over.items()}}

    def test_opens_pr_with_stable_title(self):
        run = FakeRun(self.answers())
        self.assertEqual(release(flow(run)), 0)
        create = run.ran('gh', 'pr', 'create')[0]
        self.assertEqual(create[create.index('--title') + 1], 'release: test → main')
        self.assertIn('2 commitów', create[create.index('--body') + 1])

    def test_open_pr_is_refreshed_not_duplicated(self):
        run = FakeRun(self.answers(**{'gh pr list': Res(0, '[{"number": 9}]', '')}))
        self.assertEqual(release(flow(run)), 0)
        self.assertEqual(run.ran('gh', 'pr', 'create'), [])
        self.assertEqual(run.ran('gh', 'pr', 'edit')[0][:4], ['gh', 'pr', 'edit', '9'])

    def test_same_tree_as_main_opens_nothing(self):
        run = FakeRun(self.answers(**{'git diff --quiet': OK}))
        self.assertEqual(release(flow(run)), 0)
        self.assertEqual([c for c in run.calls if c[0] == 'gh'], [])

    def test_second_green_test_without_pr_rights_keeps_one_issue(self):
        title = 'release: test → main: otwórz PR ręcznie'
        run = FakeRun(self.answers(**{'gh pr create': NO_PR, 'gh issue list': [issues(), issues(title)]}))
        self.assertEqual(release(flow(run)), 0)
        self.assertEqual(release(flow(run)), 0)
        self.assertEqual(len(run.ran('gh', 'issue', 'create')), 1)
        self.assertEqual(run.ran('gh', 'issue', 'edit')[0][:4], ['gh', 'issue', 'edit', '1'])

    def test_other_create_error_fails_without_issue(self):
        run = FakeRun(self.answers(**{'gh pr create': Res(1, '', 'HTTP 502')}))
        self.assertEqual(release(flow(run)), 1)
        self.assertEqual(run.ran('gh', 'issue'), [])


if __name__ == '__main__':
    unittest.main()
