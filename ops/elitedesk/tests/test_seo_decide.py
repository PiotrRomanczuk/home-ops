"""Unit tests for seo_decide: answers → gh actions, open PRs → questions. No network, no DB."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seo_decide import act, ask  # noqa: E402


class FakeReporter:
    def __init__(self, answered=(), open_refs=()):
        self.answered = list(answered)
        self.open = set(open_refs)
        self.consumed: list[int] = []
        self.asked: list[dict] = []

    def answers(self):
        return [d for d in self.answered if d['id'] not in self.consumed]

    def open_refs(self):
        return self.open

    def consume(self, i):
        self.consumed.append(i)

    def ask(self, question, **kw):
        self.asked.append({'question': question, **kw})
        return {}


class FakeGh:
    def __init__(self, fail_on: str | None = None):
        self.calls: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, args):
        self.calls.append(args)
        if self.fail_on and self.fail_on in args:
            raise subprocess.CalledProcessError(1, 'gh', stderr='not mergeable')
        return ''


URL = 'https://github.com/x/y/pull/9'


class ActTest(unittest.TestCase):
    def test_yes_merges_and_consumes(self):
        r, g, retired = FakeReporter([{'id': 1, 'ref': '9', 'answer': 'yes'}]), FakeGh(), []
        self.assertEqual(act(r, g, retired.append, lambda m: None), {'9'})
        self.assertEqual(g.calls, [['pr', 'merge', '9', '--squash', '--delete-branch']])
        self.assertEqual(r.consumed, [1])
        self.assertEqual(retired, [])

    def test_no_closes_with_reason_and_returns_hypotheses(self):
        r = FakeReporter([{'id': 2, 'ref': '9', 'answer': 'no', 'reason': 'zła cena', 'context_url': URL}])
        g, retired = FakeGh(), []
        act(r, g, retired.append, lambda m: None)
        self.assertEqual(g.calls[0][:3], ['pr', 'close', '9'])
        self.assertIn('Odrzucone w home-ops Decisions: zła cena', g.calls[0])
        self.assertEqual(retired, [URL])
        self.assertEqual(r.consumed, [2])

    def test_failed_merge_stays_unconsumed_for_retry(self):
        r, g = FakeReporter([{'id': 3, 'ref': '9', 'answer': 'yes'}]), FakeGh(fail_on='merge')
        self.assertEqual(act(r, g, lambda u: None, lambda m: None), set())
        self.assertEqual(r.consumed, [])

    def test_missing_ref_is_consumed_without_gh(self):
        r, g = FakeReporter([{'id': 4, 'ref': None, 'answer': 'yes'}]), FakeGh()
        act(r, g, lambda u: None, lambda m: None)
        self.assertEqual(g.calls, [])
        self.assertEqual(r.consumed, [4])


class AskTest(unittest.TestCase):
    PRS = [{'number': 9, 'title': 'SEO: tydzień', 'url': URL, 'additions': 40, 'deletions': 2},
           {'number': 10, 'title': 'SEO: kolejny', 'url': URL + '0'}]

    def test_asks_once_per_pr_skipping_waiting_and_answered(self):
        r = FakeReporter(answered=[{'id': 5, 'ref': '10', 'answer': 'yes'}], open_refs={'11'})
        self.assertEqual(ask(r, self.PRS, lambda m: None), 1)
        self.assertEqual(r.asked[0]['ref'], '9')
        self.assertEqual(r.asked[0]['context_url'], URL)
        self.assertEqual([o['key'] for o in r.asked[0]['options']], ['yes', 'no'])

    def test_pr_acted_on_this_run_is_not_asked_again(self):
        r = FakeReporter()
        self.assertEqual(ask(r, self.PRS, lambda m: None, {'9'}), 1)
        self.assertEqual(r.asked[0]['ref'], '10')

    def test_already_open_question_is_not_repeated(self):
        r = FakeReporter(open_refs={'9', '10'})
        self.assertEqual(ask(r, self.PRS, lambda m: None), 0)


if __name__ == '__main__':
    unittest.main()
