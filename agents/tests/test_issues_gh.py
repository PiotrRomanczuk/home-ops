"""issues_gh: pagination, error handling and token caching. `_gh` and
subprocess are stubbed — no network.

Run:
    python3 -m unittest discover -s agents/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
import urllib.error
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location('issues_gh', REPO_ROOT / 'agents' / 'elitedesk' / 'issues_gh.py')
assert _spec is not None and _spec.loader is not None
gh = importlib.util.module_from_spec(_spec)
sys.modules['issues_gh'] = gh
_spec.loader.exec_module(gh)


class IssuesGhTest(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = (gh._gh, gh._token_cache, gh.subprocess.run)

    def tearDown(self) -> None:
        gh._gh, gh._token_cache, gh.subprocess.run = self.saved

    def test_follows_link_rel_next(self) -> None:
        pages = {
            f'{gh.GITHUB_API}/repos/o/r/issues?state=open&per_page=100':
                ([{'number': 1}], '<https://api.github.com/p2>; rel="next", <https://api.github.com/p9>; rel="last"'),
            'https://api.github.com/p2': ([{'number': 2}], '<https://api.github.com/p1>; rel="prev"'),
        }
        gh._gh = lambda method, url, payload=None: pages[url]
        self.assertEqual([i['number'] for i in gh.fetch_open_issues('o/r') or []], [1, 2])

    def test_http_error_returns_none(self) -> None:
        def boom(method, url, payload=None):
            raise urllib.error.HTTPError(url, 403, 'rate limited', {}, None)  # type: ignore[arg-type]
        gh._gh = boom
        self.assertIsNone(gh.fetch_open_issues('o/r'))

    def test_non_list_page_returns_none(self) -> None:
        gh._gh = lambda method, url, payload=None: ({'message': 'oops'}, '')
        self.assertIsNone(gh.fetch_open_issues('o/r'))

    def test_empty_token_is_not_cached(self) -> None:
        gh._token_cache = ''
        results = iter([subprocess.CompletedProcess([], 1, '', ''), subprocess.CompletedProcess([], 0, 'tok\n', '')])
        gh.subprocess.run = lambda *a, **k: next(results)
        saved_env = gh.os.environ.pop('GITHUB_TOKEN', None)
        try:
            self.assertEqual(gh._token(), '')
            self.assertEqual(gh._token(), 'tok')  # retried after the failed first lookup
            self.assertEqual(gh._token(), 'tok')  # cached now: the iterator is exhausted
        finally:
            if saved_env is not None:
                gh.os.environ['GITHUB_TOKEN'] = saved_env

    def test_set_issue_state_without_token_does_not_call_github(self) -> None:
        gh._token_cache = ''
        gh.subprocess.run = lambda *a, **k: subprocess.CompletedProcess([], 1, '', '')
        called: list[str] = []
        gh._gh = lambda *a, **k: called.append('x')
        saved_env = gh.os.environ.pop('GITHUB_TOKEN', None)
        try:
            self.assertFalse(gh.set_issue_state('o/r', 1, True))
        finally:
            if saved_env is not None:
                gh.os.environ['GITHUB_TOKEN'] = saved_env
        self.assertEqual(called, [])


if __name__ == '__main__':
    unittest.main()
