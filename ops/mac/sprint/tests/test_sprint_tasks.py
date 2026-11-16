"""Tests for sprint_tasks.py — the file-per-task queue of the Claude sprint runner.

Run:
    python3 -m unittest discover -s ops/mac/sprint/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sprint_tasks as q  # noqa: E402


def add(state: Path, tid: str, **meta) -> None:
    q.write(state / 'queue' / f'{tid}.md', {'id': tid, 'model': 'sonnet', **meta, 'body': f'do {tid}'})


class QueueTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        q.setup(self.state)
        self.addCleanup(setattr, q, 'MIN_AGE', q.MIN_AGE)
        q.MIN_AGE = 0  # files written a moment ago may start (test_hardening.py covers the rest period)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_parse_roundtrip_and_defaults(self):
        add(self.state, 'a', priority=7, lock='vault')
        t = q.parse(self.state / 'queue' / 'a.md')
        self.assertEqual((t['id'], t['priority'], t['max_minutes'], t['attempts'], t['lock'], t['body']),
                         ('a', 7, 45, 0, 'vault', 'do a'))

    def test_priority_after_and_lock(self):
        add(self.state, 'late', priority=50)
        add(self.state, 'first', priority=10, lock='vault')
        add(self.state, 'second', priority=10, lock='vault', after='first')
        add(self.state, 'third', priority=20, lock='vault')
        self.assertEqual([t['id'] for t in q.eligible(self.state)], ['first', 'third', 'late'])
        first = q.claim(self.state)
        self.assertEqual(first['id'], 'first')
        # 'vault' is held by the running task: only the unlocked one is left.
        self.assertEqual([t['id'] for t in q.eligible(self.state)], ['late'])
        q.finish(self.state, first, 'done')
        self.assertEqual([t['id'] for t in q.eligible(self.state)], ['second', 'third', 'late'])

    def test_retry_escalates_model_then_fails(self):
        add(self.state, 'x', model='haiku')
        t = q.claim(self.state)
        q.finish(self.state, t, 'retry')
        t = q.claim(self.state)
        self.assertEqual((t['model'], t['attempts']), ('sonnet', 1))
        q.finish(self.state, t, 'retry')
        self.assertEqual(q.ids(self.state, 'failed'), {'x'})
        self.assertIsNone(q.claim(self.state))

    def test_accept_skips_tasks_that_may_not_start_now(self):
        add(self.state, 'claude', priority=10)
        add(self.state, 'local', priority=20, model='local:qwen3.8:27b')
        t = q.claim(self.state, accept=lambda task: str(task['model']).startswith('local:'))
        self.assertEqual(t['id'], 'local')
        self.assertIsNone(q.claim(self.state, accept=lambda task: False))
        self.assertEqual(q.ids(self.state, 'queue'), {'claude'})

    def test_local_model_escalates_to_sonnet(self):
        add(self.state, 'l', model='local:gemma4:26b')
        q.finish(self.state, q.claim(self.state), 'retry')
        self.assertEqual(q.parse(self.state / 'queue' / 'l.md')['model'], 'sonnet')

    def test_task_after_a_failed_one_fails_too(self):
        add(self.state, 'base')
        add(self.state, 'next', after='base')
        add(self.state, 'other', priority=90)
        q.finish(self.state, q.claim(self.state), 'failed')
        self.assertEqual(q.claim(self.state)['id'], 'other')
        self.assertEqual(q.ids(self.state, 'failed'), {'base', 'next'})

    def test_requeue_keeps_attempts_and_setup_recovers_running(self):
        add(self.state, 'y')
        t = q.claim(self.state)
        q.finish(self.state, t, 'requeue')
        self.assertEqual(q.parse(self.state / 'queue' / 'y.md')['attempts'], 0)
        q.claim(self.state)
        q.setup(self.state)  # a crashed runner left it in running/
        self.assertEqual(q.ids(self.state, 'queue'), {'y'})


    def test_not_before_holds_a_task_until_then(self):
        now = datetime(2026, 11, 16, 0, 12, tzinfo=timezone.utc)
        add(self.state, 'wait', not_before=(now + timedelta(minutes=38)).isoformat())
        add(self.state, 'bad', not_before='after the reset')  # ignored, not a blocker
        add(self.state, 'naive', not_before='2000-01-01T00:00:00')  # local time, long past
        self.assertEqual([t['id'] for t in q.eligible(self.state, now)], ['bad', 'naive'])
        self.assertEqual([t['id'] for t in q.eligible(self.state, now + timedelta(minutes=39))], ['bad', 'naive', 'wait'])

    def test_interrupted_keeps_the_model_and_the_third_one_fails(self):
        add(self.state, 'i')
        for n in (1, 2):
            q.finish(self.state, q.claim(self.state), 'interrupted')
            t = q.parse(self.state / 'queue' / 'i.md')
            self.assertEqual((t['model'], t['attempts'], t['interrupts']), ('sonnet', 0, n))
        q.finish(self.state, q.claim(self.state), 'interrupted')
        self.assertEqual(q.ids(self.state, 'failed'), {'i'})

    def test_retry_without_escalation_and_failed(self):
        add(self.state, 'p', kind='pr-fix')
        q.finish(self.state, q.claim(self.state), 'retry', escalate=False)
        self.assertEqual(q.parse(self.state / 'queue' / 'p.md')['model'], 'sonnet')
        q.finish(self.state, q.claim(self.state), 'failed')
        self.assertEqual((q.ids(self.state, 'failed'), q.ids(self.state, 'running')), ({'p'}, set()))
        self.assertEqual(q.parse(self.state / 'failed' / 'p.md')['attempts'], 1)

if __name__ == '__main__':
    unittest.main()
