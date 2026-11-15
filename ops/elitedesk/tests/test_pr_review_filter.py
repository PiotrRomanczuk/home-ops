"""Unit tests for the S1 fix (audit 2026-11-15): claude runs with user settings only, and
PRs from forks or unknown authors are skipped before checkout and never become questions.
No network, no DB, no claude."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pr_decide  # noqa: E402
import pr_review  # noqa: E402
import pr_review_filter  # noqa: E402
import pr_review_gh  # noqa: E402
import pr_review_llm  # noqa: E402
import review_db  # noqa: E402

OWNER = pr_review_filter.OWNER
OWN = {'author': {'login': OWNER}, 'isCrossRepository': False, 'headRepositoryOwner': {'login': OWNER}}
FORK = {'author': {'login': OWNER}, 'isCrossRepository': True, 'headRepositoryOwner': {'login': 'evil'}}
STRANGER = {'author': {'login': 'evil'}, 'isCrossRepository': False, 'headRepositoryOwner': {'login': OWNER}}
BOT = {'author': {'login': 'app/dependabot'}, 'isCrossRepository': False, 'headRepositoryOwner': {'login': OWNER}}


class FlagTest(unittest.TestCase):
    def test_claude_loads_user_settings_only(self):
        seen = []

        def runner(cmd, **kw):
            seen.append(cmd)
            out = {'structured_output': {'summary': 'S', 'findings': []}}
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(out), stderr='')

        pr_review_llm.call('review.md', 'review.json', 'msg', Path('.'), runner)
        cmd = seen[0]
        i = cmd.index('--strict-mcp-config')
        self.assertEqual(cmd[i + 1:i + 3], ['--setting-sources', 'user'])


class AllowedTest(unittest.TestCase):
    def check(self, meta):
        logs = []
        return pr_review_filter.allowed(meta, 'r', 5, logs.append), logs

    def test_owner_and_dependabot_pass(self):
        self.assertEqual(self.check(OWN), (True, []))
        self.assertEqual(self.check(BOT), (True, []))
        self.assertTrue(self.check({**BOT, 'author': {'login': 'dependabot[bot]'}})[0])

    def test_fork_stranger_and_unknown_are_skipped_with_a_log(self):
        self.assertEqual(self.check(FORK), (False, [f'pominięty (fork): r#5 {OWNER}']))
        self.assertEqual(self.check(STRANGER), (False, ['pominięty (autor): r#5 evil']))
        self.assertFalse(self.check({'author': {'login': OWNER}})[0])  # fork status unknown → skipped
        self.assertFalse(self.check({**OWN, 'headRepositoryOwner': {'login': 'evil'}})[0])


class PickTest(unittest.TestCase):
    def test_fork_is_never_checked_out(self):
        prs = [{'repository': {'name': 'r'}, 'number': n, 'labels': []} for n in (1, 2, 3)]
        views = {1: FORK, 2: OWN, 3: BOT}
        logs = []
        with mock.patch.object(pr_review, 'view', side_effect=lambda repo, n: {'headRefOid': f's{n}', **views[n]}), \
                mock.patch.object(review_db, 'reviewed_shas', return_value=set()), \
                mock.patch.object(pr_review, 'log', logs.append), \
                mock.patch.object(pr_review_gh, 'checkout', side_effect=AssertionError('checked out')) as checkout:
            picked = pr_review.pick(prs, None, 5)
            self.assertEqual([p['number'] for p, _ in picked], [2, 3])
            self.assertEqual(pr_review.pick(prs, 'r#1', 1), [])
        checkout.assert_not_called()
        self.assertIn(f'pominięty (fork): r#1 {OWNER}', logs)


class CandidatesTest(unittest.TestCase):
    def test_fork_and_stranger_never_become_questions(self):
        rows = [{'repository': {'name': 'r'}, 'number': n, 'isDraft': False, 'labels': [], 'author': a['author'],
                 'createdAt': f'2026-11-0{n}T00:00:00Z'} for n, a in ((1, FORK), (2, STRANGER), (3, OWN), (4, BOT))]
        metas = {'1': FORK, '2': STRANGER, '3': OWN, '4': BOT}
        calls, logs = [], []

        def gh(args):
            calls.append(args)
            if args[:2] == ['repo', 'list']:
                return '[]'
            if args[:2] == ['search', 'prs']:
                return json.dumps(rows)
            return json.dumps(metas[args[2]])

        self.assertEqual([p['number'] for p in pr_decide.candidates(gh, logs.append)], [3, 4])
        self.assertNotIn('2', [c[2] for c in calls if c[:2] == ['pr', 'view']])  # author known from search
        self.assertEqual(sorted(logs), ['pominięty (autor): r#2 evil', f'pominięty (fork): r#1 {OWNER}'])


if __name__ == '__main__':
    unittest.main()
