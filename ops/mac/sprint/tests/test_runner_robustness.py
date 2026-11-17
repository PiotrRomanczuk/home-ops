"""Tests for lifecycle.py and what runner.py / seed.py do with it: one instance, errors in threads, dead threads.

Run:
    python3 -m unittest discover -s ops/mac/sprint/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import json
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
import seed  # noqa: E402
import sprint_tasks as q  # noqa: E402


class RobustnessTest(unittest.TestCase):
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

    def errors(self) -> list[dict]:
        path = self.state / 'logs' / 'runner-errors.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def add(self, tid: str, **meta) -> None:
        q.write(self.state / 'queue' / f'{tid}.md', {'id': tid, 'model': 'sonnet', **meta, 'body': f'do {tid}'})

    def test_a_second_instance_does_not_start(self):
        first = lifecycle.single_instance(self.state)
        self.assertIsNotNone(first)
        self.assertIsNone(lifecycle.single_instance(self.state))
        first.close()  # the lock goes with the process (or the file)
        again = lifecycle.single_instance(self.state)
        self.assertIsNotNone(again)
        again.close()

    def test_a_second_runner_leaves_running_tasks_alone(self):
        self.add('busy')
        q.claim(self.state)
        held = lifecycle.single_instance(self.state)
        with mock.patch.object(runner.q, 'setup') as setup:
            self.assertIsNone(runner.main())
        setup.assert_not_called()
        self.assertTrue((self.state / 'running' / 'busy.md').exists())
        held.close()

    def test_seed_does_not_take_running_tasks_either(self):
        self.add('busy')
        q.claim(self.state)
        held = lifecycle.single_instance(self.state)
        with mock.patch.object(seed, 'STATE', self.state), self.assertRaises(SystemExit) as why:
            seed.main()
        self.assertIn('runner', str(why.exception))
        self.assertTrue((self.state / 'running' / 'busy.md').exists())
        held.close()

    def test_an_exception_in_a_worker_is_logged_and_fails_its_task(self):
        self.add('boom')
        with (mock.patch.object(runner, 'accept_for', lambda cfg: None),
              mock.patch.object(runner.claude_run, 'run', side_effect=RuntimeError('kaboom')),
              mock.patch.object(runner.lifecycle, 'halted', mock.Mock(wait=lambda s: (self.state / 'STOP').touch(),
                                                                      is_set=lambda: False))):
            runner.worker(0)  # returns: STOP appears at the sleep after the error
        failed = q.parse(self.state / 'failed' / 'boom.md')
        self.assertIn('runner exception in worker-0', failed['failed_reason'])
        self.assertFalse((self.state / 'running' / 'boom.md').exists())
        (row,) = self.errors()
        self.assertEqual((row['where'], row['task']), ('worker-0', 'boom'))
        self.assertIn('RuntimeError: kaboom', row['error'])
        self.assertRegex(row['ts'], r'[+-]\d\d:\d\d$')

    def test_an_exception_in_housekeeping_is_logged_and_the_loop_goes_on(self):
        calls = []

        def sleep(seconds: float) -> None:
            calls.append(seconds)
            if len(calls) == 2:
                (self.state / 'STOP').touch()

        with (mock.patch.object(runner.config, 'load', side_effect=ValueError('bad config')),
              mock.patch.object(runner.time, 'sleep', sleep)):
            runner.housekeeping()
        self.assertEqual(len(calls), 2)  # it survived the first error
        self.assertEqual([r['where'] for r in self.errors()], ['housekeeping', 'housekeeping'])

    def test_main_exits_non_zero_when_a_thread_is_gone(self):
        real_sleep = runner.time.sleep
        with (mock.patch.object(runner, 'worker', lambda n: None),  # the worker threads end at once
              mock.patch.object(runner, 'housekeeping', lambda: real_sleep(30)),
              mock.patch.object(runner.budget, 'refresh'), mock.patch.object(runner.lifecycle, 'notify'),
              mock.patch.object(runner.time, 'sleep', lambda s: real_sleep(0.3)),
              self.assertRaises(SystemExit) as why):
            runner.main()
        self.assertEqual(why.exception.code, 1)
        self.assertIn('thread(s) died: worker-0', self.errors()[-1]['error'])

    def test_fail_without_a_task_only_logs(self):
        try:
            raise KeyError('x')
        except KeyError:
            lifecycle.fail(self.state, 'housekeeping', None)
        self.assertEqual(self.errors()[0]['task'], None)

    def test_dead_names_threads_that_ended(self):
        done = threading.Thread(target=lambda: None, name='worker-3')
        done.start()
        done.join()
        alive = threading.Thread(target=threading.Event().wait, args=(5,), name='housekeeping', daemon=True)
        alive.start()
        self.assertEqual(lifecycle.dead([done, alive]), ['worker-3'])


if __name__ == '__main__':
    unittest.main()
