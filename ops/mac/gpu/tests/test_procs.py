"""Tests for procs.py — a shard is a process group: pause, resume and stop reach the grandchildren,
and a crashed supervisor's leftovers are stopped on the next start.

Run:
    python3 -m unittest discover -s ops/mac/gpu/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import procs  # noqa: E402

TREE = 'sleep 60 & sleep 60 & wait'  # a leader with two children


def members(pgid: int) -> list[tuple[int, str]]:
    out = subprocess.run(['ps', '-axo', 'pid=,pgid=,stat='], capture_output=True, text=True).stdout
    return [(int(p), s) for p, g, s in (line.split() for line in out.splitlines()) if int(g) == pgid]


class GroupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.log = (self.dir / 'shard.log').open('ab')

    def tearDown(self) -> None:
        self.log.close()
        self.tmp.cleanup()

    def start(self) -> subprocess.Popen:
        proc = procs.start(['sh', '-c', TREE], str(self.dir), dict(os.environ), self.dir / 'job.1.json', self.log)
        time.sleep(0.5)
        self.addCleanup(lambda: procs.send(proc.pid, signal.SIGKILL))
        return proc

    def test_pause_resume_stop_reach_the_whole_group(self):
        proc = self.start()
        self.assertEqual(len(members(proc.pid)), 3)
        procs.send(proc.pid, signal.SIGSTOP)
        time.sleep(0.3)
        self.assertTrue(all(stat.startswith('T') for _, stat in members(proc.pid)))
        procs.send(proc.pid, signal.SIGCONT)
        time.sleep(0.3)
        self.assertFalse(any(stat.startswith('T') for _, stat in members(proc.pid)))
        procs.send(proc.pid, signal.SIGSTOP)  # a stopped group still has to die
        procs.stop_all([proc.pid], [proc], grace_s=5)
        self.assertFalse(procs.alive(proc.pid))
        self.assertIsNotNone(proc.poll())

    def test_record_has_boot_and_start_time(self):
        proc = self.start()
        rec = json.loads((self.dir / 'job.1.json').read_text())
        self.assertEqual((rec['pgid'], rec['boot']), (proc.pid, procs.boot_time()))
        self.assertTrue(rec['lstart'])

    def test_cleanup_stops_leftover_group_whose_leader_is_gone(self):
        proc = procs.start(['sh', '-c', 'sleep 60 & exit 0'], str(self.dir), dict(os.environ), self.dir / 'old.1.json', self.log)
        proc.wait()  # the leader exits; its child keeps the group alive, as after a supervisor crash
        self.addCleanup(lambda: procs.send(proc.pid, signal.SIGKILL))
        time.sleep(0.3)
        self.assertTrue(procs.alive(proc.pid))
        self.assertEqual(procs.cleanup_orphans(self.dir, grace_s=5), [proc.pid])
        self.assertFalse(procs.alive(proc.pid))
        self.assertEqual(list(self.dir.glob('*.json')), [])

    def test_cleanup_drops_records_from_an_earlier_boot_without_killing(self):
        proc = self.start()
        rec = json.loads((self.dir / 'job.1.json').read_text())
        (self.dir / 'job.1.json').write_text(json.dumps({**rec, 'boot': rec['boot'] - 1000}))
        self.assertEqual(procs.cleanup_orphans(self.dir, grace_s=5), [])
        self.assertTrue(procs.alive(proc.pid))
        self.assertEqual(list(self.dir.glob('*.json')), [])


if __name__ == '__main__':
    unittest.main()
