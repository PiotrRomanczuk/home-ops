"""Tests for activity_gha (GitHub Actions jobs → runs) and activity_now
(CPU owners from cgroups).

Run:
    python3 -m unittest discover -s agents/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load(name: str):
    path = REPO_ROOT / 'agents' / 'elitedesk' / f'{name}.py'
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gha = _load('activity_gha')
now = _load('activity_now')

WF_RUN = {'id': 42509513761, 'name': 'Nightly E2E', 'status': 'completed', 'head_branch': 'main', 'event': 'schedule'}


def job(**extra) -> dict:
    return {'id': 777, 'name': 'Desktop Chrome', 'status': 'completed', 'conclusion': 'success',
            'runner_name': 'uwh-e2e', 'started_at': '2026-11-08T18:20:39Z',
            'completed_at': '2026-11-08T18:28:55Z', 'html_url': 'https://github.com/x/y/job/777', **extra}


class JobToRunTest(unittest.TestCase):
    def test_completed_job_on_our_runner(self) -> None:
        r = gha.job_to_run(job(), WF_RUN, 'PiotrRomanczuk/strummy', {'uwh-e2e'})
        self.assertEqual(r['unit'], 'Nightly E2E / Desktop Chrome')
        self.assertEqual((r['invocation_id'], r['project_slug'], r['result']), ('gha:777', 'strummy', 'ok'))
        self.assertEqual(r['detail'], 'uwh-e2e · main · schedule · success')

    def test_running_and_failed_jobs(self) -> None:
        running = gha.job_to_run(job(status='in_progress', conclusion=None), WF_RUN, 'o/strummy', {'uwh-e2e'})
        self.assertEqual((running['result'], running['finished_at']), ('running', None))
        failed = gha.job_to_run(job(conclusion='timed_out'), WF_RUN, 'o/strummy', {'uwh-e2e'})
        self.assertEqual(failed['result'], 'failed')

    def test_jobs_elsewhere_or_not_started_are_skipped(self) -> None:
        self.assertIsNone(gha.job_to_run(job(runner_name='GitHub Actions 1000029981'), WF_RUN, 'o/r', {'uwh-e2e'}))
        self.assertIsNone(gha.job_to_run(job(started_at=None), WF_RUN, 'o/r', {'uwh-e2e'}))


class PollerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        cfg = Path(self.tmp.name) / 'strummy'
        cfg.mkdir()
        body = json.dumps({'agentName': 'uwh-e2e', 'gitHubUrl': 'https://github.com/PiotrRomanczuk/strummy'})
        (cfg / '.runner').write_bytes(b'\xef\xbb\xbf' + body.encode())  # the runner writes a BOM
        self.calls: list[str] = []

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def api(self, path: str):
        self.calls.append(path)
        if path.endswith('/jobs'):
            return {'jobs': [job()]}
        return {'workflow_runs': [WF_RUN]}

    def test_discovers_runner_with_bom(self) -> None:
        (r,) = gha.discover_runners(Path(self.tmp.name))
        self.assertEqual((r['name'], r['repo']), ('uwh-e2e', 'PiotrRomanczuk/strummy'))

    def test_completed_runs_are_fetched_once(self) -> None:
        p = gha.GhaPoller(Path(self.tmp.name), api=self.api)
        self.assertEqual([r['invocation_id'] for r in p.poll()], ['gha:777'])
        self.assertEqual(p.poll(), [])
        self.assertEqual(sum(c.endswith('/jobs') for c in self.calls), 1)


class CgroupTest(unittest.TestCase):
    def test_owners(self) -> None:
        names = {'a' * 64: 'supabase_db_StudentProduction'}
        cases = {
            '0::/user.slice/user-1000.slice/user@1000.service/app.slice/gha-runner-light.service\n': 'gha-runner-light',
            f'0::/system.slice/docker-{"a" * 64}.scope\n': 'supabase_db_StudentProduction',
            f'0::/system.slice/docker-{"b" * 64}.scope\n': 'docker:' + 'b' * 12,
            '0::/user.slice/user-1000.slice/session-3.scope\n': 'sesja',
            '0::/system.slice/cloudflared.service\n': 'cloudflared',
            '': 'kernel',
        }
        for text, want in cases.items():
            self.assertEqual(now.owner_from_cgroup(text, names), want, text)

    def test_group_cpu_is_share_of_machine(self) -> None:
        samples = [('github-runner-strummy', 300.0), ('github-runner-strummy', 180.0), ('ssh', 2.0), ('db', 40.0)]
        self.assertEqual(now.group_cpu(samples, ncpu=8),
                         [{'owner': 'github-runner-strummy', 'pct': 60.0}, {'owner': 'db', 'pct': 5.0}])


if __name__ == '__main__':
    unittest.main()
