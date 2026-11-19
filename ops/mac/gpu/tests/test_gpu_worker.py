"""Tests for gpu_worker.py — tick/reap/start_missing and the move to the next job.

Run:
    python3 -m unittest discover -s ops/mac/gpu/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gpu_jobs as gj  # noqa: E402
import gpu_worker as gw  # noqa: E402

QUIET = {'idle_s': 9999.0, 'on_ac': True, 'display_held': False, 'graphics': True, 'thermal': 0, 'pressure': 1,
         'logic': False, 'foreign': False}


def job(name: str, shards: int) -> dict:
    return {'name': name, 'argv': ['x'], 'cwd': '/', 'env': {}, 'shards': shards}


class FakeProc:
    def __init__(self, pid: int, rc: int | None = None) -> None:
        self.pid, self.rc = pid, rc

    def poll(self) -> int | None:
        return self.rc


class TickTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.gpu = Path(self.tmp.name)
        for sub in ('pids', 'logs'):
            (self.gpu / sub).mkdir()
        self.progress = gj.Progress(self.gpu / 'progress.json')
        self.jobs = [job('A', 2), job('B', 2)]
        self.procs: dict[tuple[str, int], FakeProc] = {}
        self.next_pid = 100
        gw.shards.clear()
        gw.retry_at.clear()
        for patcher in (
            mock.patch.object(gw, 'GPU', self.gpu),
            mock.patch.object(gw.machine, 'snapshot', side_effect=lambda **_: dict(QUIET)),
            mock.patch.object(gw.machine, 'away', return_value=True),
            mock.patch.object(gw.machine, 'can_start', return_value=True),
            mock.patch.object(gw.machine, 'must_stop', return_value=None),
            mock.patch.object(gw.gpu_pause, 'borrowed', return_value=False),
            mock.patch.object(gw.gpu_pause.procs, 'send', return_value=True),
            mock.patch.object(gw.procs, 'start', side_effect=self.fake_start),
            mock.patch.object(gw.procs, 'stop_all', side_effect=self.fake_stop_all),
            mock.patch.object(gw, 'RETRY_S', 0),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.stopped: list[int] = []

    def fake_start(self, argv, cwd, env, pid_file, log_file) -> FakeProc:
        self.next_pid += 1
        pid_file.write_text('{}')
        proc = FakeProc(self.next_pid)
        self.procs[(Path(log_file.name).name.split('.')[0], int(Path(log_file.name).name.split('.')[1]))] = proc
        return proc

    def fake_stop_all(self, pgids, procs=(), grace_s: float = 30) -> None:
        self.stopped.extend(pgids)
        for proc in procs:
            proc.rc = -15

    def fail_shard(self, name: str, n: int) -> None:
        self.progress.fails[f'{name}.{n}'] = gj.MAX_FAILS - 1
        self.procs[(name, n)].rc = 1

    def test_a_given_up_job_does_not_hand_its_shards_to_the_next_job(self) -> None:
        gw.tick(self.jobs, self.progress)  # A's shards 1 and 2 start
        self.assertEqual(sorted(gw.shards), [1, 2])
        self.fail_shard('A', 1)  # shard 1 reaches MAX_FAILS; shard 2 of A keeps running
        gw.tick(self.jobs, self.progress)
        self.procs[('A', 2)].rc = 0  # A's shard 2 finishes later, or has been stopped
        gw.tick(self.jobs, self.progress)
        gw.tick(self.jobs, self.progress)  # now B runs: its shards must start from scratch
        self.assertFalse(self.progress.shard_done(self.jobs[1], 1), 'B shard 1 marked done though it never ran')
        self.assertFalse(self.progress.shard_done(self.jobs[1], 2))
        self.assertEqual(sorted(k for k in self.procs if k[0] == 'B'), [('B', 1), ('B', 2)])
        self.assertEqual({sh['job'] for sh in gw.shards.values()}, {'B'})

    def test_giving_up_stops_the_other_shards_and_ends_the_job_once(self) -> None:
        gw.tick(self.jobs, self.progress)
        a2 = self.procs[('A', 2)]
        self.fail_shard('A', 1)
        with mock.patch.object(gw.gj, 'unload_ollama', return_value=[]):
            gw.tick(self.jobs, self.progress)
        self.assertIn(a2.pid, self.stopped, 'the surviving shard of the abandoned job must be stopped')
        self.assertTrue(all(sh['job'] != 'A' for sh in gw.shards.values()))
        self.assertEqual(self.progress.done.get('A', []), [])  # stopped, not "done"

    def test_a_shard_of_the_previous_job_never_removes_the_pid_file_of_the_current_one(self) -> None:
        gw.tick(self.jobs, self.progress)
        (self.gpu / 'pids' / 'B.1.json').write_text('{}')
        self.fail_shard('A', 1)
        gw.tick(self.jobs, self.progress)
        self.assertTrue((self.gpu / 'pids' / 'B.1.json').exists())
        self.assertFalse((self.gpu / 'pids' / 'A.1.json').exists())


if __name__ == '__main__':
    unittest.main()
