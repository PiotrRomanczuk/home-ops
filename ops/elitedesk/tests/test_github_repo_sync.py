"""Tests for github-repo-sync's per-project dispatch + parsing.

Covers:
  * build_repo_meta       — unsupported / local_git_dir / owner_repo dispatch
  * sync_via_github       — repo/commits/package.json parsing (mocked _gh_request)
  * sync_via_local_git    — git log parsing (mocked subprocess.run)
  * check_deploy          — HEAD/GET reachability (mocked urlopen)
  * load_mapping          — strips "_comment"/"_note" keys

All network/subprocess calls are mocked — no real GitHub API or git process
is touched. Run:
    python3 -m unittest discover -s ops/elitedesk/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _load_module():
    """Load github-repo-sync.py as a module despite its hyphenated filename.
    Sets the env vars IngestClient.from_env requires so the import doesn't
    sys.exit — same trick as agents/tests/test_planner_sync.py."""
    os.environ.setdefault('INGEST_URL', 'http://x/api/ingest')
    os.environ.setdefault('INGEST_TOKEN', 'y')
    path = REPO_ROOT / 'ops' / 'elitedesk' / 'github-repo-sync.py'
    spec = importlib.util.spec_from_file_location('github_repo_sync', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_module()


class TestLoadMapping(unittest.TestCase):
    def test_strips_underscore_keys(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'projects.json'
            p.write_text(json.dumps({
                '_comment': 'ignore me',
                'strummy': {'owner_repo': 'PiotrRomanczuk/strummy', '_note': 'kept as a value, not a top-level key'},
            }))
            mapping = mod.load_mapping(p)
            self.assertEqual(list(mapping.keys()), ['strummy'])
            self.assertEqual(mapping['strummy']['owner_repo'], 'PiotrRomanczuk/strummy')


class TestBuildRepoMetaDispatch(unittest.TestCase):
    def test_unsupported_short_circuits(self):
        meta = mod.build_repo_meta({'unsupported': 'no git remote configured'})
        self.assertEqual(meta, {'source': 'github-api', 'unsupported': 'no git remote configured'})

    def test_no_recognizable_key_records_error(self):
        meta = mod.build_repo_meta({})
        self.assertIn('error', meta)

    @patch.object(mod, 'sync_via_local_git')
    def test_local_git_dir_dispatches(self, mock_local):
        mock_local.return_value = {'source': 'local-git', 'git': {'last_commit': '2026-07-15', 'commits_30d': 3}}
        meta = mod.build_repo_meta({'local_git_dir': '/home/piotr/git/stano.git'})
        mock_local.assert_called_once()
        self.assertEqual(meta['source'], 'local-git')

    @patch.object(mod, 'sync_via_github')
    def test_owner_repo_dispatches(self, mock_gh):
        mock_gh.return_value = {'source': 'github-api', 'github_repo': 'PiotrRomanczuk/strummy'}
        meta = mod.build_repo_meta({'owner_repo': 'PiotrRomanczuk/strummy'})
        mock_gh.assert_called_once()
        self.assertEqual(meta['github_repo'], 'PiotrRomanczuk/strummy')

    @patch.object(mod, 'check_deploy')
    def test_deploy_url_is_checked_when_present(self, mock_deploy):
        mock_deploy.return_value = {'url': 'strummy.vercel.app', 'reachable': True}
        meta = mod.build_repo_meta({'unsupported': 'x', 'deploy_url': 'strummy.vercel.app'})
        mock_deploy.assert_called_once_with('strummy.vercel.app')
        self.assertEqual(meta['deploy']['reachable'], True)


class TestSyncViaGithub(unittest.TestCase):
    @patch.object(mod, '_gh_request')
    def test_repo_not_found_records_error(self, mock_req):
        mock_req.return_value = None
        meta = mod.sync_via_github({'owner_repo': 'PiotrRomanczuk/ghost'})
        self.assertIn('error', meta)
        self.assertEqual(meta['github_repo'], 'PiotrRomanczuk/ghost')

    @patch.object(mod, '_gh_request')
    def test_node_manifest_pulls_version_and_deps(self, mock_req):
        pkg = base64.b64encode(json.dumps({
            'version': '0.158.5',
            'dependencies': {'next': '16.0.0', 'react': '19.0.0'},
        }).encode()).decode()

        def fake(path):
            if path.startswith('/repos/PiotrRomanczuk/strummy/commits'):
                return [{'commit': {'committer': {'date': '2026-07-15T10:00:00Z'}}}]
            if path == '/repos/PiotrRomanczuk/strummy/contents/package.json':
                return {'content': pkg}
            if path == '/repos/PiotrRomanczuk/strummy':
                return {'name': 'strummy'}
            return None

        mock_req.side_effect = fake
        meta = mod.sync_via_github({'owner_repo': 'PiotrRomanczuk/strummy', 'manifest': 'node'})
        self.assertEqual(meta['version'], '0.158.5')
        self.assertEqual(meta['stack']['key_deps'], ['next', 'react'])
        self.assertEqual(meta['git']['commits_30d'], 1)
        self.assertEqual(meta['git']['last_commit'], '2026-07-15')

    @patch.object(mod, '_gh_request')
    def test_dotnet_manifest_falls_back_to_release_tag(self, mock_req):
        def fake(path):
            if path == '/repos/PiotrRomanczuk/ShortsCannon':
                return {'name': 'ShortsCannon'}
            if 'commits' in path:
                return []
            if path.endswith('/releases/latest'):
                return {'tag_name': 'v1.2.0'}
            return None

        mock_req.side_effect = fake
        meta = mod.sync_via_github({'owner_repo': 'PiotrRomanczuk/ShortsCannon', 'manifest': 'dotnet'})
        self.assertEqual(meta['version'], 'v1.2.0')
        self.assertEqual(meta['stack']['runtime'], 'dotnet')

    @patch.object(mod, '_gh_request')
    def test_python_manifest_has_no_version_attempt(self, mock_req):
        def fake(path):
            if 'commits' in path:
                return []
            if path == '/repos/PiotrRomanczuk/job-search':
                return {'name': 'job-search'}
            return None

        mock_req.side_effect = fake
        meta = mod.sync_via_github({'owner_repo': 'PiotrRomanczuk/job-search', 'manifest': 'python'})
        self.assertNotIn('version', meta)
        self.assertEqual(meta['stack']['runtime'], 'python')


class TestSyncViaLocalGit(unittest.TestCase):
    def test_missing_dir_records_error(self):
        meta = mod.sync_via_local_git({'local_git_dir': '/nonexistent/path/stano.git'})
        self.assertIn('error', meta)

    @patch('subprocess.run')
    def test_parses_commit_count_and_last_commit(self, mock_run):
        with tempfile.TemporaryDirectory() as td:
            git_dir = Path(td) / 'stano.git'
            git_dir.mkdir()

            def fake_run(args, **kwargs):
                if 'log' in args and '--oneline' in args:
                    return subprocess.CompletedProcess(args, 0, stdout='abc123 fix\ndef456 feat\n', stderr='')
                return subprocess.CompletedProcess(args, 0, stdout='2026-07-15\n', stderr='')

            mock_run.side_effect = fake_run
            meta = mod.sync_via_local_git({'local_git_dir': str(git_dir)})
            self.assertEqual(meta['source'], 'local-git')
            self.assertEqual(meta['git']['commits_30d'], 2)
            self.assertEqual(meta['git']['last_commit'], '2026-07-15')


class TestCheckDeploy(unittest.TestCase):
    @patch('urllib.request.urlopen')
    def test_reachable_2xx(self, mock_urlopen):
        cm = MagicMock()
        cm.__enter__.return_value.status = 200
        mock_urlopen.return_value = cm
        result = mod.check_deploy('strummy.vercel.app')
        self.assertTrue(result['reachable'])
        self.assertEqual(result['status_code'], 200)

    @patch('urllib.request.urlopen')
    def test_4xx_is_still_reachable(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError('https://x', 404, 'Not Found', {}, io.BytesIO(b''))
        result = mod.check_deploy('x.example.com')
        self.assertTrue(result['reachable'])
        self.assertEqual(result['status_code'], 404)

    @patch('urllib.request.urlopen')
    def test_5xx_is_not_reachable(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError('https://x', 503, 'Unavailable', {}, io.BytesIO(b''))
        result = mod.check_deploy('x.example.com')
        self.assertFalse(result['reachable'])
        self.assertEqual(result['status_code'], 503)

    @patch('urllib.request.urlopen')
    def test_network_error_is_not_reachable(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError('no route to host')
        result = mod.check_deploy('x.example.com')
        self.assertFalse(result['reachable'])
        self.assertIsNone(result['status_code'])


if __name__ == '__main__':
    unittest.main()
