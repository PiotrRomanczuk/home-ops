"""Unit tests for pr_decide: candidates filter, health, ask cap/snooze, answer actions. No network, no DB."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pr_decide  # noqa: E402
from pr_decide import act, ask, candidates, health  # noqa: E402

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


class FakeReporter:
    def __init__(self, answered=(), open_refs=(), history=()):
        self.answered, self.open, self.history = list(answered), set(open_refs), list(history)
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

    def _call(self, method, path):
        return {'decisions': self.history}


def pr(repo, n, days_old=3, draft=False, labels=()):
    return {'repository': {'name': repo}, 'number': n, 'title': f'PR {n}', 'url': f'https://gh/{repo}/{n}',
            'isDraft': draft, 'author': {'login': 'me'}, 'labels': [{'name': x} for x in labels],
            'createdAt': (NOW - timedelta(days=days_old)).isoformat().replace('+00:00', 'Z')}


class FakeGh:
    def __init__(self, prs=(), archived=(), view=None, fail_on=None):
        self.prs, self.archived, self.view, self.fail_on = list(prs), list(archived), view or {}, fail_on
        self.calls: list[list[str]] = []

    def __call__(self, args):
        self.calls.append(args)
        if self.fail_on and self.fail_on in args:
            raise subprocess.CalledProcessError(1, 'gh', stderr='protected branch')
        if args[:2] == ['repo', 'list']:
            return json.dumps([{'name': a} for a in self.archived])
        if args[:2] == ['search', 'prs']:
            return json.dumps(self.prs)
        if args[:2] == ['pr', 'view']:
            return json.dumps(self.view.get(args[2], {'mergeable': 'MERGEABLE', 'statusCheckRollup': []}))
        return ''


class CandidatesTest(unittest.TestCase):
    def test_drops_drafts_archived_and_seo_auto_oldest_first(self):
        g = FakeGh(prs=[pr('a', 1, 1), pr('a', 2, 9), pr('a', 3, draft=True), pr('old', 4),
                        pr('gitara', 5, labels=['seo-auto'])], archived=['old'])
        self.assertEqual([p['number'] for p in candidates(g)], [2, 1])


class HealthTest(unittest.TestCase):
    def test_conflict_and_red_ci_block_merge(self):
        g = FakeGh(view={'1': {'mergeable': 'CONFLICTING'},
                         '2': {'mergeable': 'MERGEABLE', 'statusCheckRollup': [{'name': 'lint', 'conclusion': 'FAILURE'}]},
                         '3': {'mergeable': 'UNKNOWN', 'statusCheckRollup': [{'name': 'lint', 'conclusion': 'SUCCESS'}]}})
        self.assertFalse(health(g, 'a', 1)[0])
        self.assertIn('lint', health(g, 'a', 2)[1])
        self.assertTrue(health(g, 'a', 3)[0])


class AskTest(unittest.TestCase):
    def test_caps_waiting_questions(self):
        r = FakeReporter(open_refs={f'x#{i}' for i in range(pr_decide.MAX_OPEN - 2)})
        n = ask(r, FakeGh(), [pr('a', i) for i in range(1, 6)], lambda m: None, set(), NOW)
        self.assertEqual(n, 2)
        self.assertEqual([q['ref'] for q in r.asked], ['a#1', 'a#2'])

    def test_skips_snoozed_and_offers_no_merge_on_conflict(self):
        later = (NOW - timedelta(days=2)).isoformat()
        r = FakeReporter(history=[{'ref': 'a#1', 'answer': 'later', 'answered_at': later}])
        g = FakeGh(view={'2': {'mergeable': 'CONFLICTING'}})
        ask(r, g, [pr('a', 1), pr('a', 2)], lambda m: None, set(), NOW)
        self.assertEqual([q['ref'] for q in r.asked], ['a#2'])
        self.assertEqual([o['key'] for o in r.asked[0]['options']], ['no', 'later'])

    def test_snooze_expires_after_a_week(self):
        old = (NOW - timedelta(days=8)).isoformat()
        r = FakeReporter(history=[{'ref': 'a#1', 'answer': 'later', 'answered_at': old}])
        ask(r, FakeGh(), [pr('a', 1)], lambda m: None, set(), NOW)
        self.assertEqual([o['key'] for o in r.asked[0]['options']], ['yes', 'no', 'later'])


class ActTest(unittest.TestCase):
    def test_yes_no_later(self):
        r = FakeReporter([{'id': 1, 'ref': 'a#1', 'answer': 'yes'}, {'id': 2, 'ref': 'b#2', 'answer': 'no', 'reason': 'stare'},
                          {'id': 3, 'ref': 'c#3', 'answer': 'later'}])
        g = FakeGh()
        self.assertEqual(act(r, g, lambda m: None), {'a#1', 'b#2', 'c#3'})
        self.assertEqual(g.calls[0], ['pr', 'merge', '1', '-R', 'PiotrRomanczuk/a', '--squash', '--delete-branch'])
        self.assertEqual(g.calls[1][:5], ['pr', 'close', '2', '-R', 'PiotrRomanczuk/b'])
        self.assertIn('Odrzucone w home-ops Decisions: stare', g.calls[1])
        self.assertEqual(len(g.calls), 2)
        self.assertEqual(r.consumed, [1, 2, 3])

    def test_failed_merge_is_consumed_and_logged(self):
        r, logs = FakeReporter([{'id': 1, 'ref': 'a#1', 'answer': 'yes'}]), []
        act(r, FakeGh(fail_on='merge'), logs.append)
        self.assertEqual(r.consumed, [1])
        self.assertIn('protected branch', logs[0])


if __name__ == '__main__':
    unittest.main()
