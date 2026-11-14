"""Tests for sprint_tasks.py — the file-per-task queue of the Claude sprint runner.

Run:
    python3 -m unittest discover -s ops/mac/sprint/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
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

    def test_requeue_keeps_attempts_and_setup_recovers_running(self):
        add(self.state, 'y')
        t = q.claim(self.state)
        q.finish(self.state, t, 'requeue')
        self.assertEqual(q.parse(self.state / 'queue' / 'y.md')['attempts'], 0)
        q.claim(self.state)
        q.setup(self.state)  # a crashed runner left it in running/
        self.assertEqual(q.ids(self.state, 'queue'), {'y'})


if __name__ == '__main__':
    unittest.main()
