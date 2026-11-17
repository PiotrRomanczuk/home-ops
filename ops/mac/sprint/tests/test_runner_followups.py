"""Follow-ups to the r15 review of PR #83: SIGTERM handler order, watch() shutting down, run_groups.CLOSED.

Run:
    python3 -m unittest discover -s ops/mac/sprint/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import signal
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lifecycle  # noqa: E402
import run_groups  # noqa: E402
import runner  # noqa: E402
import sprint_tasks as q  # noqa: E402


class FollowupsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        q.setup(self.state)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr, runner, 'STATE', runner.STATE)
        runner.STATE = self.state
        self.addCleanup(setattr, q, 'MIN_AGE', q.MIN_AGE)
        q.MIN_AGE = 0  # the files written here may start at once
        self.addCleanup(lifecycle.halted.clear)  # main() → shutdown() sets both for the whole process
        self.addCleanup(run_groups.CLOSED.clear)
        self.addCleanup(signal.signal, signal.SIGTERM, signal.getsignal(signal.SIGTERM))

    def test_main_installs_the_sigterm_handler_before_it_starts_a_thread(self):
        order = []
        real_start = threading.Thread.start
        with (mock.patch.object(runner, 'worker', lambda n: None), mock.patch.object(runner, 'housekeeping', lambda: None),
              mock.patch.object(runner.budget, 'refresh'), mock.patch.object(runner.lifecycle, 'notify'),
              mock.patch.object(runner.lifecycle, 'on_sigterm', lambda w: order.append('sigterm')),
              mock.patch.object(runner.lifecycle, 'watch', lambda *a: None),
              mock.patch.object(threading.Thread, 'start', lambda t: (order.append('start'), real_start(t))[1])):
            runner.main()
        self.assertEqual(order[0], 'sigterm')
        self.assertIn('start', order)

    def test_a_dead_thread_shuts_everything_down_before_the_exit(self):
        calls = []
        done = threading.Thread(target=lambda: None, name='worker-0')
        done.start()
        done.join()
        with (mock.patch.object(lifecycle.run_groups, 'stop_all', lambda grace: calls.append('stop_all')),
              mock.patch.object(lifecycle.time, 'sleep'), mock.patch.object(lifecycle, 'notify'),
              self.assertRaises(SystemExit) as why):
            lifecycle.watch(self.state, [done, done], lambda: False)
        self.assertEqual((why.exception.code, calls), (1, ['stop_all']))
        self.assertTrue(lifecycle.halted.is_set())

    def test_nothing_starts_once_stop_all_ran(self):
        run_groups.stop_all(0)
        with mock.patch.object(run_groups.subprocess, 'Popen') as popen:
            self.assertIsNone(run_groups.start(['true'], {}))
        popen.assert_not_called()
        self.assertEqual(run_groups.LIVE, {})


if __name__ == '__main__':
    unittest.main()
