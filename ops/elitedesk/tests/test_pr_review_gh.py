"""Unit tests for publishing a review: the PR comment, labels through REST (not `gh pr edit`,
which breaks with gh 2.46 on uwh), and a failed label never blocking the saved review."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pr_review  # noqa: E402
import pr_review_gh  # noqa: E402
import pr_review_llm  # noqa: E402
import review_db  # noqa: E402

F2 = {'severity': 'ważne', 'file': 'b.py', 'line': 9, 'problem': 'brak testu', 'evidence': 'nowa gałąź', 'suggestion': 'test'}


class GhTest(unittest.TestCase):
    def test_comment_has_marker_verdict_and_findings(self):
        text = pr_review_gh.render({'verdict': 'zmiany', 'summary': 'Sum', 'findings': [F2], 'dropped': 2}, 'abcdef123')
        self.assertTrue(text.startswith('<!-- pr-review sha=abcdef123 -->'))
        self.assertIn('Do poprawy', text)
        self.assertIn('`b.py:9`', text)
        self.assertIn('niepotwierdzone: 2', text)

    def test_publish_only_comments(self):
        calls = []
        run = lambda args: calls.append(args) or 'https://gh/c/9'  # noqa: E731
        url = pr_review_gh.publish(run, 'r', 4, {'verdict': 'ok', 'summary': 'S', 'findings': []}, 'abc')
        self.assertEqual((url, [c[:2] for c in calls]), ('https://gh/c/9', [['pr', 'comment']]))

    def test_labels_go_through_rest_not_pr_edit(self):
        calls = []
        pr_review_gh.label(lambda args: calls.append(args) or '', 'r', 4, 'ok')
        self.assertEqual(sum(c[:2] == ['label', 'create'] for c in calls), 2)
        self.assertIn(['api', '-X', 'POST', 'repos/PiotrRomanczuk/r/issues/4/labels', '-f', 'labels[]=review:ok'], calls)
        self.assertIn(['api', '-X', 'DELETE', 'repos/PiotrRomanczuk/r/issues/4/labels/review:zmiany'], calls)
        self.assertFalse(any(c[:2] == ['pr', 'edit'] for c in calls))

    def test_removing_an_absent_label_is_fine_other_errors_are_not(self):
        def run(args, msg='gh: Label does not exist (HTTP 404)'):
            if args[:3] == ['api', '-X', 'DELETE']:
                raise subprocess.CalledProcessError(1, 'gh', stderr=msg)
            return ''
        pr_review_gh.pr_gate.set_labels(run, 'o', 'r', 4, remove=('x',))
        with self.assertRaises(subprocess.CalledProcessError):
            pr_review_gh.pr_gate.set_labels(lambda a: run(a, 'HTTP 403'), 'o', 'r', 4, remove=('x',))


class LabelFailureTest(unittest.TestCase):
    def test_failed_label_still_saves_the_review(self):
        result = {'verdict': 'ok', 'summary': 'S', 'findings': [], 'dropped': 0, 'model': 'm', 'cost_usd': 0.1}
        boom = subprocess.CalledProcessError(1, 'gh', stderr='Projects (classic) is being deprecated')
        with mock.patch.object(pr_review_gh, 'checkout', return_value=Path('.')), \
                mock.patch.object(pr_review_gh, 'diff', return_value=('D', '')), \
                mock.patch.object(pr_review_llm, 'review', return_value=result), \
                mock.patch.object(review_db, 'latest', return_value=None), \
                mock.patch.object(pr_review_gh, 'publish', return_value='https://gh/c/1'), \
                mock.patch.object(pr_review_gh, 'label', side_effect=boom), \
                mock.patch.object(review_db, 'save') as save:
            row = pr_review.review_one({'repository': {'name': 'r'}, 'number': 1, 'labels': []},
                                       {'headRefOid': 'abc1234', 'baseRefName': 'main', 'title': 'T'}, False)
            save.assert_called_once()
            self.assertEqual(row['comment_url'], 'https://gh/c/1')


if __name__ == '__main__':
    unittest.main()
