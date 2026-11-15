"""Unit tests for pr_decide + pr_gate: candidates filter, PR state, options by review verdict,
asking only about reviewed commits, superseding stale questions, merging only the reviewed SHA.
No network, no DB."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pr_decide  # noqa: E402
import pr_gate  # noqa: E402
from pr_decide import act, ask, candidates  # noqa: E402

NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)
OK = {'verdict': 'ok', 'summary': 'Dobrze.', 'findings': [], 'comment_url': 'https://gh/c/1'}
CHANGES = {'verdict': 'zmiany', 'summary': 'Brak testu.', 'findings': [{'severity': 'ważne'}], 'comment_url': None}


class FakeReporter:
    def __init__(self, answered=(), open_rows=(), history=()):
        self.answered, self.open_rows, self.history = list(answered), list(open_rows), list(history)
        self.consumed: list[int] = []
        self.asked: list[dict] = []
        self.posts: list[tuple[str, dict]] = []

    def answers(self):
        return [d for d in self.answered if d['id'] not in self.consumed]

    def consume(self, i):
        self.consumed.append(i)

    def ask(self, question, **kw):
        self.asked.append({'question': question, **kw})

    def _call(self, method, path, body=None):
        if method == 'POST':
            self.posts.append((path, body))
            return {}
        return {'decisions': self.open_rows if 'state=open' in path else self.history}


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
            base = {'headRefOid': 'sha1', 'mergeable': 'MERGEABLE', 'statusCheckRollup': []}
            return json.dumps({**base, **self.view.get(args[2], {})})
        return ''

    def verbs(self):
        return [c[:2] for c in self.calls if c[:2] != ['pr', 'view']]


def reviews(table):
    return lambda repo, num, sha: table.get((repo, num, sha))


class CandidatesTest(unittest.TestCase):
    def test_drops_drafts_archived_and_seo_auto_oldest_first(self):
        g = FakeGh(prs=[pr('a', 1, 1), pr('a', 2, 9), pr('a', 3, draft=True), pr('old', 4),
                        pr('gitara', 5, labels=['seo-auto'])], archived=['old'])
        self.assertEqual([p['number'] for p in candidates(g)], [2, 1])


class GateTest(unittest.TestCase):
    def test_state_blocks_conflict_and_red_ci(self):
        g = FakeGh(view={'1': {'mergeable': 'CONFLICTING'},
                         '2': {'statusCheckRollup': [{'name': 'lint', 'conclusion': 'FAILURE'}]},
                         '3': {'mergeable': 'UNKNOWN', 'statusCheckRollup': [{'name': 'lint', 'conclusion': 'SUCCESS'}]}})
        self.assertFalse(pr_gate.state(g, 'o', 'a', 1)['ok'])
        self.assertIn('lint', pr_gate.state(g, 'o', 'a', 2)['line'])
        self.assertEqual(pr_gate.state(g, 'o', 'a', 3), {'sha': 'sha1', 'ok': True, 'line': '+0 / −0 linii'})

    def test_options_follow_the_review(self):
        keys = lambda opts: [o['key'] for o in opts]  # noqa: E731
        self.assertEqual(keys(pr_gate.options(OK, True, 0)), ['yes', 'no', 'later'])
        self.assertEqual(keys(pr_gate.options(OK, False, 0)), ['fix', 'no', 'later'])
        self.assertEqual(keys(pr_gate.options(CHANGES, True, 0)), ['fix', 'force', 'no', 'later'])
        self.assertEqual(keys(pr_gate.options(CHANGES, False, 1)), ['fix', 'no', 'later'])
        self.assertEqual(keys(pr_gate.options(CHANGES, True, 2)), ['force', 'no', 'later'])

    def test_refs_and_rounds(self):
        self.assertEqual(pr_gate.split_ref('a#12@abc'), ('a', '12', 'abc'))
        self.assertEqual(pr_gate.split_ref('a#12'), ('a', '12', None))
        self.assertIsNone(pr_gate.split_ref('nonsense'))
        self.assertEqual(pr_gate.rounds([{'name': 'fix-round:1'}, {'name': 'fix-round:2'}, {'name': 'x'}]), 2)


class AskTest(unittest.TestCase):
    def run_ask(self, r, g, prs, table):
        return ask(r, g, prs, lambda m: None, set(), NOW, reviews(table))

    def test_only_reviewed_commits_are_asked_about(self):
        r = FakeReporter()
        self.run_ask(r, FakeGh(), [pr('a', 1), pr('a', 2)], {('a', 2, 'sha1'): OK})
        self.assertEqual([q['ref'] for q in r.asked], ['a#2@sha1'])
        self.assertEqual([o['key'] for o in r.asked[0]['options']], ['yes', 'no', 'later'])
        self.assertIn('Recenzja: ok', r.asked[0]['detail'])

    def test_files_review_page_sections_before_asking_and_requires_review(self):
        r = FakeReporter()
        view = {'1': {'body': 'Naprawia X.', 'headRefName': 'fix/x', 'baseRefName': 'dev',
                      'files': [{'path': 'app/x.ts', 'additions': 3, 'deletions': 1},
                                {'path': 'docs/manual-tests/2026-11-15-x.html', 'additions': 90, 'deletions': 0}]}}
        self.run_ask(r, FakeGh(view=view), [pr('a', 1)], {('a', 1, 'sha1'): OK})
        path, body = r.posts[0]
        self.assertEqual(path, '/api/reviews/sections')
        self.assertEqual((body['repo'], body['number'], body['head_sha'], body['source']), ('a', 1, 'sha1', 'pr-decide'))
        keys = [s['key'] for s in body['sections']]
        self.assertEqual(keys, ['summary', 'files', 'checks', 'manual-test'])
        self.assertIn('fix/x → dev', body['sections'][0]['title'])
        self.assertIn('/blob/sha1/docs/manual-tests/2026-11-15-x.html', body['sections'][3]['body_md'])
        self.assertTrue(r.asked[0]['requires_review'])

    def test_sections_for_a_bare_pr(self):
        import pr_sections
        out = pr_sections.collect(FakeGh(), 'me', 'a', 1, 'sha1')
        self.assertEqual([s['key'] for s in out], ['summary', 'files', 'checks'])
        self.assertEqual(out[0]['body_md'], '_(PR bez opisu)_')

    def test_ci_section_carries_the_snapshot_time_and_files_the_real_count(self):
        import pr_sections
        g = FakeGh(view={'1': {'changedFiles': 140, 'files': [{'path': f'f{i}'} for i in range(100)]}})
        out = {s['key']: s for s in pr_sections.collect(g, 'me', 'a', 1, 'sha1')}
        self.assertRegex(out['checks']['title'], r'^CI \(stan z \d\d:\d\d\)$')
        self.assertEqual(out['files']['title'], 'Zmienione pliki (140)')
        self.assertIn('i 40 więcej', out['files']['body_md'])

    def test_a_pr_whose_sections_cannot_be_filed_is_skipped_not_fatal(self):
        class NoBodyGh(FakeGh):
            def __call__(self, args):
                if args[:2] == ['pr', 'view'] and 'body' in args[-1] and args[2] == '1':
                    raise subprocess.CalledProcessError(1, 'gh', stderr='rate limited')
                return super().__call__(args)
        r, logs = FakeReporter(open_rows=[{'id': 7, 'ref': 'a#1@old'}]), []
        n = ask(r, NoBodyGh(), [pr('a', 1), pr('a', 2)], logs.append, set(), NOW,
                reviews({('a', 1, 'sha1'): OK, ('a', 2, 'sha1'): OK}))
        self.assertEqual([q['ref'] for q in r.asked], ['a#2@sha1'])  # the next PR is still asked about
        self.assertEqual(n, 1)
        self.assertNotIn('/api/decisions/7/answer', [p for p, _ in r.posts])  # the old question stays
        self.assertEqual(r.consumed, [])
        self.assertTrue(any('skipped a#1' in m for m in logs))

    def test_a_failing_sections_post_is_skipped_too(self):
        class Down(FakeReporter):
            def _call(self, method, path, body=None):
                if path == '/api/reviews/sections':
                    raise RuntimeError('POST /api/reviews/sections → HTTP 404: ')
                return super()._call(method, path, body)
        r, logs = Down(), []
        ask(r, FakeGh(), [pr('a', 1)], logs.append, set(), NOW, reviews({('a', 1, 'sha1'): OK}))
        self.assertEqual(r.asked, [])
        self.assertTrue(any('skipped a#1' in m and 'HTTP 404' in m for m in logs))

    def test_caps_waiting_questions(self):
        r = FakeReporter(open_rows=[{'id': i, 'ref': f'x#{i}@s'} for i in range(pr_decide.MAX_OPEN - 2)])
        table = {('a', i, 'sha1'): OK for i in range(1, 6)}
        self.assertEqual(self.run_ask(r, FakeGh(), [pr('a', i) for i in range(1, 6)], table), 2)

    def test_supersedes_question_about_older_commit(self):
        r = FakeReporter(open_rows=[{'id': 7, 'ref': 'a#1@old'}])
        self.run_ask(r, FakeGh(), [pr('a', 1, labels=['fix-round:1'])], {('a', 1, 'sha1'): CHANGES})
        # documentation is filed first, so a failure there leaves the old question waiting
        self.assertEqual(r.posts[0][0], '/api/reviews/sections')
        self.assertEqual(r.posts[1][0], '/api/decisions/7/answer')
        self.assertTrue(r.posts[1][1]['reason'].startswith(pr_decide.SUPERSEDED))
        self.assertEqual(r.consumed, [7])
        self.assertEqual([o['key'] for o in r.asked[0]['options']], ['fix', 'force', 'no', 'later'])

    def test_does_not_repeat_question_for_same_commit_or_snoozed_pr(self):
        later = (NOW - timedelta(days=2)).isoformat()
        r = FakeReporter(open_rows=[{'id': 1, 'ref': 'a#1@sha1'}],
                         history=[{'ref': 'a#2@sha0', 'answer': 'later', 'answered_at': later}])
        self.run_ask(r, FakeGh(), [pr('a', 1), pr('a', 2)], {('a', 1, 'sha1'): OK, ('a', 2, 'sha1'): OK})
        self.assertEqual(r.asked, [])


class ActTest(unittest.TestCase):
    def test_merges_only_the_reviewed_commit(self):
        r = FakeReporter([{'id': 1, 'ref': 'a#1@sha1', 'answer': 'yes'}, {'id': 2, 'ref': 'a#2@stale', 'answer': 'force'},
                          {'id': 3, 'ref': 'a#3', 'answer': 'yes'}])
        g, logs = FakeGh(), []
        act(r, g, logs.append)
        merges = [c for c in g.calls if c[:2] == ['pr', 'merge']]
        self.assertEqual(merges, [['pr', 'merge', '1', '-R', 'PiotrRomanczuk/a', '--squash', '--delete-branch',
                                   '--match-head-commit', 'sha1']])
        self.assertTrue(any('head moved' in m for m in logs) and any('predates reviews' in m for m in logs))
        self.assertEqual(r.consumed, [1, 2, 3])

    def test_fix_labels_and_no_closes(self):
        r = FakeReporter([{'id': 1, 'ref': 'a#1@s', 'answer': 'fix'}, {'id': 2, 'ref': 'b#2@s', 'answer': 'no', 'reason': 'stare'}])
        g = FakeGh()
        self.assertEqual(act(r, g, lambda m: None), {'a#1', 'b#2'})
        self.assertIn(['api', '-X', 'POST', 'repos/PiotrRomanczuk/a/issues/1/labels', '-f', 'labels[]=fix-requested'], g.calls)
        self.assertFalse(any(c[:2] == ['pr', 'edit'] for c in g.calls))  # gh 2.46 on uwh breaks on pr edit
        self.assertIn('Odrzucone w home-ops Decisions: stare', [c for c in g.calls if c[:2] == ['pr', 'close']][0])

    def test_failed_merge_is_consumed_and_logged(self):
        r, logs = FakeReporter([{'id': 1, 'ref': 'a#1@sha1', 'answer': 'yes'}]), []
        act(r, FakeGh(fail_on='merge'), logs.append)
        self.assertEqual(r.consumed, [1])
        self.assertTrue(any('protected branch' in m for m in logs))


if __name__ == '__main__':
    unittest.main()
