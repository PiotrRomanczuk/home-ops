"""Tests for github_signals (daily progress counts from GitHub) and
repo_projects (vault repo: + JSON overrides). No network: a fake getter
serves paths.

Run:
    python3 -m unittest discover -s ops/elitedesk/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import github_signals as gs  # noqa: E402
import repo_projects as rp  # noqa: E402

SINCE = datetime(2026, 10, 1, tzinfo=timezone.utc)


def fake(routes: dict[str, object]):
    calls: list[str] = []

    def get(path: str):
        calls.append(path)
        for prefix, data in routes.items():
            if path.startswith(prefix):
                return data if 'page=1' in path else ([] if isinstance(data, list) else {'workflow_runs': []})
        return None
    return get, calls


class CollectTest(unittest.TestCase):
    def test_counts_per_warsaw_day(self) -> None:
        get, calls = fake({
            '/repos/o/r/commits': [
                {'commit': {'committer': {'date': '2026-11-02T23:30:00Z'}}},  # 00:30 on 3.11 in Warsaw
                {'commit': {'committer': {'date': '2026-11-03T10:00:00Z'}}},
                {'commit': {'committer': None}},
            ],
            '/repos/o/r/pulls': [
                {'updated_at': '2026-11-05T10:00:00Z', 'created_at': '2026-11-04T10:00:00Z', 'merged_at': '2026-11-05T10:00:00Z'},
                {'updated_at': '2026-10-20T10:00:00Z', 'created_at': '2026-09-01T10:00:00Z', 'merged_at': None},
                {'updated_at': '2026-09-01T10:00:00Z', 'created_at': '2026-08-01T10:00:00Z', 'merged_at': '2026-09-01T10:00:00Z'},
            ],
            '/repos/o/r/deployments': [
                {'created_at': '2026-11-07T06:49:28Z'},
                {'created_at': '2026-09-01T06:00:00Z'},
            ],
            '/repos/o/r/actions/runs': {'workflow_runs': [
                {'status': 'in_progress', 'conclusion': None, 'created_at': '2026-11-08T18:20:00Z'},
                {'status': 'completed', 'conclusion': 'skipped', 'name': 'Deploy', 'created_at': '2026-11-08T16:00:00Z'},
                {'status': 'completed', 'conclusion': 'success', 'name': 'Nightly E2E', 'created_at': '2026-11-08T14:19:00Z', 'html_url': 'u'},
                {'status': 'completed', 'conclusion': 'failure', 'name': 'CI', 'created_at': '2026-11-06T10:00:00Z'},
                {'status': 'completed', 'conclusion': 'cancelled', 'name': 'CI', 'created_at': '2026-11-06T11:00:00Z'},
            ]},
        })
        counts, summary = gs.collect(get, 'o/r', 'main', SINCE)
        self.assertEqual(counts[('2026-11-03', 'commits')], 2)
        self.assertEqual(counts[('2026-11-04', 'pr_opened')], 1)
        self.assertEqual(counts[('2026-11-05', 'pr_merged')], 1)
        self.assertEqual(sum(n for (d, s), n in counts.items() if s == 'pr_opened'), 1)  # 1.09 is before the window
        self.assertEqual(counts[('2026-11-07', 'deploys')], 1)
        self.assertEqual((counts[('2026-11-08', 'ci_ok')], counts[('2026-11-06', 'ci_failed')]), (1, 1))
        self.assertNotIn(('2026-11-06', 'ci_ok'), counts)  # cancelled says nothing
        self.assertEqual(summary['ci'], {'conclusion': 'success', 'workflow': 'Nightly E2E', 'at': '2026-11-08T14:19:00Z', 'url': 'u'})
        self.assertEqual(summary['last_deploy_at'], '2026-11-07T06:49:28Z')
        self.assertTrue(any('sha=main' in c for c in calls))
        self.assertTrue(any('created=%3E%3D2026-10-01' in c for c in calls))

    def test_pages_until_a_short_page(self) -> None:
        pages = {1: [{'n': i} for i in range(100)], 2: [{'n': 1}]}
        got = list(gs.paged(lambda p: pages.get(int(p.rsplit('page=', 1)[1]), []), '/x?a=1'))
        self.assertEqual(len(got), 101)

    def test_api_errors_mean_no_counts(self) -> None:
        counts, summary = gs.collect(lambda p: None, 'o/r', 'main', SINCE)
        self.assertEqual((dict(counts), summary), ({}, {'ci': None, 'last_deploy_at': None}))

    def test_to_rows(self) -> None:
        rows = gs.to_rows('strummy', gs.Counter({('2026-11-03', 'commits'): 2}))
        self.assertEqual(rows, [{'project_slug': 'strummy', 'day': '2026-11-03', 'signal': 'commits', 'n': 2}])


class RepoProjectsTest(unittest.TestCase):
    PROJECTS = [
        {'slug': 'strummy', 'raw_frontmatter': {'repo': 'strummy'}},
        {'slug': 'infrastructure', 'raw_frontmatter': {'repo': 'home-infra-docs'}},
        {'slug': 'zadluzenie', 'raw_frontmatter': {'repo': '-'}},
        {'slug': 'smart-home', 'raw_frontmatter': {}},
        {'slug': 'contentforge', 'raw_frontmatter': {'repo': 'ContentForge', 'verdict': 'usunięty'}},
        {'slug': 'forked', 'raw_frontmatter': {'repo': '"someone/else"'}},
    ]

    def test_vault_entries(self) -> None:
        self.assertEqual(rp.vault_entries(self.PROJECTS, 'PiotrRomanczuk'), {
            'strummy': {'owner_repo': 'PiotrRomanczuk/strummy'},
            'infrastructure': {'owner_repo': 'PiotrRomanczuk/home-infra-docs'},
            'forked': {'owner_repo': 'someone/else'},
        })

    def test_json_overrides_win_and_elsewhere_replaces(self) -> None:
        vault = {'strummy': {'owner_repo': 'P/strummy'}, 'stano': {'owner_repo': 'P/stano'}}
        json_map = {'strummy': {'deploy_url': 'strummy.online'}, 'stano': {'local_git_dir': '/g/stano.git'},
                    'rhcsa-lab': {'unsupported': 'local only'}}
        self.assertEqual(rp.merged_mapping(json_map, vault), {
            'strummy': {'owner_repo': 'P/strummy', 'deploy_url': 'strummy.online'},
            'stano': {'local_git_dir': '/g/stano.git'},
            'rhcsa-lab': {'unsupported': 'local only'},
        })


if __name__ == '__main__':
    unittest.main()
