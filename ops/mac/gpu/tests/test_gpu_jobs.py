"""Tests for gpu_jobs.py — the job list, per-shard argv and the persisted progress.

Run:
    python3 -m unittest discover -s ops/mac/gpu/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gpu_jobs as gj  # noqa: E402

JOBS = [
    {'name': 'a', 'argv': ['~/bin/tool', 'study', '--shard', '{shard}/{shards}'], 'cwd': '~/code', 'shards': 2},
    {'name': 'b', 'argv': ['python3', 'bench.py'], 'env': {'OLLAMA_BASE_URL': 'http://127.0.0.1:11434'}},
]


class JobsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / 'jobs.json').write_text(json.dumps(JOBS))
        self.jobs = gj.load(self.dir / 'jobs.json')

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_load_normalises(self):
        a, b = self.jobs
        self.assertEqual((a['shards'], b['shards']), (2, 1))
        self.assertEqual(a['cwd'], os.path.expanduser('~/code'))
        self.assertEqual(b['env'], {'OLLAMA_BASE_URL': 'http://127.0.0.1:11434'})

    def test_load_rejects_bad_lists(self):
        for bad in ([{'name': 'x', 'argv': 'sh -c rm'}], [{'name': 'x', 'argv': ['a']}, {'name': 'x', 'argv': ['b']}]):
            (self.dir / 'bad.json').write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                gj.load(self.dir / 'bad.json')

    def test_argv_for_fills_shard_and_home(self):
        self.assertEqual(gj.argv_for(self.jobs[0], 2), [os.path.expanduser('~/bin/tool'), 'study', '--shard', '2/2'])

    def test_jobs_run_in_order_and_progress_survives_a_restart(self):
        p = gj.Progress(self.dir / 'progress.json')
        self.assertEqual(p.current(self.jobs)['name'], 'a')
        p.mark_done(self.jobs[0], 1)
        self.assertEqual(p.current(self.jobs)['name'], 'a')  # shard 2 still to do
        p.mark_done(self.jobs[0], 2)
        again = gj.Progress(self.dir / 'progress.json')
        self.assertEqual(again.current(self.jobs)['name'], 'b')
        again.mark_done(self.jobs[1], 1)
        self.assertIsNone(again.current(self.jobs))

    def test_job_given_up_after_max_fails(self):
        p = gj.Progress(self.dir / 'progress.json')
        for _ in range(gj.MAX_FAILS):
            p.fail(self.jobs[0], 2)
        self.assertTrue(p.job_finished(self.jobs[0]))
        self.assertEqual(p.current(self.jobs)['name'], 'b')


if __name__ == '__main__':
    unittest.main()
