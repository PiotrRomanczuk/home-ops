"""Tests for stopping the runner (lifecycle.shutdown, run_groups.py): every run lives in its own process group, outside
the launchd job's, so SIGTERM to the runner and a restart after a crash must end those groups themselves.

Run:
    python3 -m unittest discover -s ops/mac/sprint/tests -p 'test_*.py' -v
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import run_groups  # noqa: E402
import sprint_tasks as q  # noqa: E402
from run_groups import procs  # noqa: E402

# a fake `claude`: answers /usage, otherwise records its pid and a grandchild's, then waits on the grandchild
FAKE = '''#!/bin/sh
if [ "$2" = /usage ]; then echo '{"usage_report": %s}'; exit 0; fi
echo $$ >> "$PIDS"
sleep 300 &
echo $! >> "$PIDS"
wait
'''


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def until(check, seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.2)
    return check()


class SigtermTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.state, self.pids = self.dir / 'state', self.dir / 'pids'
        q.setup(self.state)
        (self.dir / 'vault' / '3-Zasoby' / 'analysis').mkdir(parents=True)
        week = (datetime.now(timezone.utc) + timedelta(days=6)).isoformat()
        usage = {'rate_limits': {'limits': [{'kind': 'session', 'percent': 1, 'resets_at': week},
                                            {'kind': 'weekly_all', 'percent': 1, 'resets_at': week}]}}
        fake = self.dir / 'claude'
        fake.write_text(FAKE % json.dumps(usage))
        fake.chmod(0o755)
        (self.state / 'config.json').write_text(json.dumps({'claude': {'workers': 2, 'windows': ['daily 00:00-00:00', 'daily 12:00-12:00']}}))
        for tid in ('one', 'two'):
            path = self.state / 'queue' / f'{tid}.md'
            q.write(path, {'id': tid, 'model': 'sonnet', 'max_minutes': 5, 'cwd': str(self.dir), 'body': f'do {tid}'})
            os.utime(path, (time.time() - 60, time.time() - 60))  # past MIN_AGE
        self.env = {**os.environ, 'SPRINT_STATE': str(self.state), 'CLAUDE_BIN': str(fake), 'SPRINT_PLANNER': '0',
                    'SPRINT_VAULT': str(self.dir / 'vault'), 'PIDS': str(self.pids)}

    def recorded(self) -> list[int]:
        return [int(x) for x in self.pids.read_text().split()] if self.pids.exists() else []

    def test_sigterm_ends_every_run_and_requeues_its_task_once(self):
        runner = subprocess.Popen([sys.executable, str(HERE / 'runner.py')], env=self.env, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.PIPE, text=True)
        self.addCleanup(runner.stderr.close)
        self.addCleanup(lambda: runner.poll() is None and runner.kill())
        self.assertTrue(until(lambda: len(self.recorded()) == 4, 30), 'both fake runs should have started')
        self.assertTrue(until(lambda: all(t.get('pgid') for t in q.load(self.state / 'running')), 5))
        pids = self.recorded()
        self.addCleanup(lambda: [os.kill(p, signal.SIGKILL) for p in pids if alive(p)])
        runner.send_signal(signal.SIGTERM)
        self.assertEqual(runner.wait(timeout=55), 0, runner.stderr.read())  # within launchd's ExitTimeOut (60 s)
        self.assertEqual([p for p in pids if alive(p)], [])  # `claude` and its grandchild, in both runs
        self.assertEqual(list((self.state / 'running').glob('*.md')), [])
        for tid in ('one', 'two'):
            task = q.parse(self.state / 'queue' / f'{tid}.md')
            self.assertEqual((task['model'], task['attempts'], task['interrupts']), ('sonnet', 0, 1))
            self.assertNotIn('pgid', task)


class StaleGroupTest(unittest.TestCase):
    """After a SIGKILL or a crash: setup() stops a run that outlived its runner before the task goes back to queue/."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name)
        q.setup(self.state)
        self.group = subprocess.Popen(['sh', '-c', 'sleep 300 & wait'], start_new_session=True)
        self.addCleanup(lambda: procs.send(self.group.pid, signal.SIGKILL) and self.group.wait())

    def leave_running(self, **group) -> None:
        pgid = self.group.pid
        q.write(self.state / 'running' / 'left.md', {'id': 'left', 'model': 'opus', 'pgid': pgid, 'pgid_boot': procs.boot_time(),
                                                      'pgid_start': procs.started(pgid), **group, 'body': 'do it'})

    def test_setup_stops_the_group_and_counts_an_interruption(self):
        self.leave_running()
        q.setup(self.state)
        self.assertTrue(until(lambda: self.group.poll() is not None, 15))
        self.assertFalse(procs.alive(self.group.pid))
        task = q.parse(self.state / 'queue' / 'left.md')
        self.assertEqual((task['model'], task['interrupts']), ('opus', 1))
        for key in run_groups.KEYS:
            self.assertNotIn(key, task)

    def test_a_group_id_with_another_leader_is_not_signalled(self):
        self.leave_running(pgid_start='Thu Jan  1 00:00:00 1970')  # the id was handed to another process since
        q.setup(self.state)
        self.assertIsNone(self.group.poll())
        self.assertEqual(q.parse(self.state / 'queue' / 'left.md')['interrupts'], 1)

    def test_a_task_that_never_started_goes_back_untouched(self):
        q.write(self.state / 'running' / 'fresh.md', {'id': 'fresh', 'model': 'sonnet', 'body': 'do it'})
        q.setup(self.state)
        self.assertEqual(q.parse(self.state / 'queue' / 'fresh.md')['interrupts'], 0)
        self.assertIsNone(self.group.poll())


if __name__ == '__main__':
    unittest.main()
