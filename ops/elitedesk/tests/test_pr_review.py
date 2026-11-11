"""Unit tests for pr_review (+ pr_review_llm, pr_review_gh, review_db): two-pass verdicts,
dropping unconfirmed findings, the PR comment, picking unreviewed heads, dry runs, SQL params.
No network, no DB, no claude — runners and helpers are faked."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pr_review  # noqa: E402
import pr_review_gh  # noqa: E402
import pr_review_llm  # noqa: E402
import review_db  # noqa: E402

F1 = {'severity': 'bloker', 'file': 'a.py', 'line': 3, 'problem': 'dzielenie przez zero', 'evidence': 'x / n', 'suggestion': 'guard'}
F2 = {'severity': 'ważne', 'file': 'b.py', 'line': 9, 'problem': 'brak testu', 'evidence': 'nowa gałąź', 'suggestion': 'test'}
PR = {'repo': 'r', 'number': 4, 'title': 'T', 'body': 'B', 'base': 'main', 'ci': 'ok', 'previous': ''}


class FakeClaude:
    def __init__(self, *outputs):
        self.outputs, self.calls = list(outputs), []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        out = self.outputs.pop(0)
        return subprocess.CompletedProcess(cmd, 0, stdout=out if isinstance(out, str) else json.dumps(out), stderr='')


def structured(data, cost=0.5):
    return {'structured_output': data, 'total_cost_usd': cost, 'modelUsage': {'claude-opus-x': {}}}


class LlmTest(unittest.TestCase):
    def test_verifier_drops_unconfirmed_and_can_lower_severity(self):
        kept, dropped = pr_review_llm.merge_checks([F1, F2], [
            {'index': 0, 'confirmed': True, 'severity': 'ważne', 'reason': 'jest'},
            {'index': 1, 'confirmed': False, 'severity': 'ważne', 'reason': 'obsłużone wyżej'}])
        self.assertEqual((len(kept), kept[0]['severity'], dropped), (1, 'ważne', 1))
        self.assertEqual(pr_review_llm.verdict_of(kept), 'zmiany')
        self.assertEqual(pr_review_llm.verdict_of([]), 'ok')

    def test_two_passes_with_findings_one_without(self):
        with tempfile.TemporaryDirectory() as d:
            two = FakeClaude(structured({'verdict': 'bloker', 'summary': 'S', 'findings': [F1, F2]}),
                             structured({'checks': [{'index': 0, 'confirmed': True, 'severity': 'bloker', 'reason': 'r'},
                                                    {'index': 1, 'confirmed': False, 'severity': 'drobne', 'reason': 'r'}]}, 0.25))
            out = pr_review_llm.review(PR, 'diff', '', Path(d), runner=two)
            self.assertEqual((out['verdict'], out['dropped'], out['cost_usd'], out['model']), ('bloker', 1, 0.75, 'claude-opus-x'))
            self.assertEqual(two.calls[0][0][two.calls[0][0].index('--tools') + 1], 'Read,Grep,Glob')
            self.assertEqual(two.calls[0][1]['cwd'], Path(d))
            one = FakeClaude(structured({'verdict': 'ok', 'summary': 'S', 'findings': []}))
            self.assertEqual(pr_review_llm.review(PR, 'diff', '', Path(d), runner=one)['verdict'], 'ok')
            self.assertEqual(len(one.calls), 1)

    def test_broken_cli_output_is_an_error(self):
        with self.assertRaises(pr_review_llm.ReviewError):
            pr_review_llm.review(PR, 'd', '', Path('.'), runner=FakeClaude('not json'))
        with self.assertRaises(pr_review_llm.ReviewError):
            pr_review_llm.review(PR, 'd', '', Path('.'), runner=FakeClaude({'is_error': True, 'subtype': 'error_max_budget_usd'}))

    def test_message_carries_skipped_files_and_previous_review(self):
        msg = pr_review_llm.message({**PR, 'previous': 'Commit abc: zmiany'}, 'DIFF', 'report.html | 200 +', Path('.'))
        self.assertIn('report.html | 200 +', msg)
        self.assertIn('Commit abc: zmiany', msg)
        self.assertTrue(msg.endswith('DIFF'))


class GhTest(unittest.TestCase):
    def test_comment_has_marker_verdict_and_findings(self):
        text = pr_review_gh.render({'verdict': 'zmiany', 'summary': 'Sum', 'findings': [F2], 'dropped': 2}, 'abcdef123')
        self.assertTrue(text.startswith('<!-- pr-review sha=abcdef123 -->'))
        self.assertIn('Do poprawy', text)
        self.assertIn('`b.py:9`', text)
        self.assertIn('niepotwierdzone: 2', text)

    def test_publish_comments_then_swaps_labels(self):
        calls = []
        run = lambda args: calls.append(args) or ('https://gh/c/9' if args[:2] == ['pr', 'comment'] else '')  # noqa: E731
        url = pr_review_gh.publish(run, 'r', 4, {'verdict': 'ok', 'summary': 'S', 'findings': []}, 'abc')
        self.assertEqual(url, 'https://gh/c/9')
        self.assertEqual(calls[-1][-4:], ['--add-label', 'review:ok', '--remove-label', 'review:zmiany'])
        self.assertEqual(sum(c[:2] == ['label', 'create'] for c in calls), 2)


class PickAndRunTest(unittest.TestCase):
    def prs(self):
        return [{'repository': {'name': 'r'}, 'number': n, 'labels': []} for n in (1, 2, 3)]

    def test_pick_skips_reviewed_heads_and_respects_limit(self):
        with mock.patch.object(review_db, 'reviewed_shas', return_value={('r', 1, 's1')}), \
                mock.patch.object(pr_review, 'view', side_effect=lambda repo, n: {'headRefOid': f's{n}'}):
            picked = pr_review.pick(self.prs(), None, 1)
            self.assertEqual([p['number'] for p, _ in picked], [2])
            self.assertEqual([p['number'] for p, _ in pr_review.pick(self.prs(), 'r#1', 1)], [1])

    def test_dry_run_writes_file_and_never_publishes(self):
        result = {'verdict': 'ok', 'summary': 'S', 'findings': [], 'dropped': 0, 'model': 'm', 'cost_usd': 0.1}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(pr_review_gh, 'CACHE', Path(d)), \
                mock.patch.object(pr_review_gh, 'checkout', return_value=Path(d)), \
                mock.patch.object(pr_review_gh, 'diff', return_value=('D', '')), \
                mock.patch.object(pr_review_llm, 'review', return_value=result), \
                mock.patch.object(review_db, 'latest', side_effect=AssertionError('dry run touched the DB')), \
                mock.patch.object(pr_review_gh, 'publish') as publish, mock.patch.object(review_db, 'save') as save:
            row = pr_review.review_one(self.prs()[0], {'headRefOid': 'abc1234', 'baseRefName': 'main', 'title': 'T'}, True)
            self.assertTrue((Path(d) / 'dry' / 'r-1-abc1234.json').is_file())
            publish.assert_not_called()
            save.assert_not_called()
            self.assertEqual(row['head_sha'], 'abc1234')


class DbTest(unittest.TestCase):
    def test_save_passes_values_as_psql_variables(self):
        seen = {}
        review_db.save({'repo': 'r', 'number': 4, 'head_sha': 's', 'verdict': 'ok', 'summary': "it's",
                        'findings': [F1], 'dropped': 0, 'round': 1, 'model': None},
                       execute=lambda sql, params: seen.update(sql=sql, params=params))
        self.assertIn(":'summary'", seen['sql'])
        self.assertNotIn("it's", seen['sql'])
        self.assertEqual(json.loads(seen['params']['findings'])[0]['file'], 'a.py')
        self.assertEqual(seen['params']['model'], '')


if __name__ == '__main__':
    unittest.main()
