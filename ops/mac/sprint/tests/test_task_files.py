"""Tests for task_files.py and the queue rules that rest on it: half-written files, young files, dangling `after`.

Run:
    python3 -m unittest discover -s ops/mac/sprint/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sprint_tasks as q  # noqa: E402
import task_files as tf  # noqa: E402

DAY = 24 * 3600


def put(folder: Path, name: str, text: str, age: float = 60) -> Path:
    path = folder / f'{name}.md'
    path.write_text(text)
    old = time.time() - age
    os.utime(path, (old, old))
    return path


class ParseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_unclosed_frontmatter_is_not_a_task(self):
        self.assertIsNone(tf.parse(put(self.dir, 'half', '---\nid: half\nmodel: sonnet\nproject: x\n')))
        self.assertIsNone(tf.parse(put(self.dir, 'cut', '---\nid: cut\n---')))  # header closed, no prompt
        self.assertIsNone(tf.parse(put(self.dir, 'empty', '')))

    def test_whole_files_still_parse(self):
        ok = tf.parse(put(self.dir, 'ok', '---\nid: ok\nafter: other # a comment\npriority: 3  # why\n---\ndo it\n'))
        self.assertEqual((ok['after'], ok['priority'], ok['body']), ('other', 3, 'do it'))
        bare = tf.parse(put(self.dir, 'bare', 'just a prompt\n'))  # no header at all: the file is the prompt
        self.assertEqual((bare['id'], bare['body']), ('bare', 'just a prompt'))
        self.assertIsNone(tf.parse(self.dir / 'missing.md'))

    def test_load_skips_files_that_have_not_rested(self):
        put(self.dir, 'old', 'a\n', age=60)
        put(self.dir, 'new', 'b\n', age=0)
        self.assertEqual(sorted(t['id'] for t in tf.load(self.dir)), ['new', 'old'])
        self.assertEqual([t['id'] for t in tf.load(self.dir, min_age=5)], ['old'])


class QueueRulesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        q.setup(self.state)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def queue(self, name: str, text: str, age: float = 60) -> Path:
        return put(self.state / 'queue', name, text, age)

    def names(self, folder: str) -> list[str]:
        return sorted(p.stem for p in (self.state / folder).glob('*.md'))

    def test_half_written_and_fresh_files_never_start(self):
        self.queue('half', '---\nid: half\nmodel: opus\n')
        self.queue('fresh', '---\nid: fresh\n---\nprompt\n', age=1)
        self.queue('ready', '---\nid: ready\n---\nprompt\n')
        self.assertEqual([t['id'] for t in q.eligible(self.state)], ['ready'])
        self.assertEqual(q.claim(self.state)['id'], 'ready')
        self.assertIsNone(q.claim(self.state))
        self.assertEqual(self.names('queue'), ['fresh', 'half'])  # left alone: they may still be being written

    def test_after_naming_nothing_fails_after_a_day(self):
        self.queue('lost', '---\nid: lost\nafter: nowhere\n---\nprompt\n', age=DAY + 60)
        self.queue('recent', '---\nid: recent\nafter: nowhere\n---\nprompt\n', age=DAY - 3600)
        self.queue('chained', '---\nid: chained\nafter: recent\n---\nprompt\n', age=DAY + 60)
        q.drop_blocked(self.state)
        self.assertEqual(q.parse(self.state / 'failed' / 'lost.md')['failed_reason'], 'after: nowhere does not exist')
        self.assertEqual(self.names('queue'), ['chained', 'recent'])

    def test_after_in_running_or_done_is_not_dangling(self):
        put(self.state / 'running', 'busy', '---\nid: busy\n---\nx\n')
        put(self.state / 'done', 'fin', '---\nid: fin\n---\nx\n')
        self.queue('a', '---\nid: a\nafter: busy\n---\np\n', age=2 * DAY)
        self.queue('b', '---\nid: b\nafter: fin\n---\np\n', age=2 * DAY)
        q.drop_blocked(self.state)
        self.assertEqual(self.names('queue'), ['a', 'b'])

    def test_after_a_failed_task_still_fails_at_once(self):
        put(self.state / 'failed', 'dead', '---\nid: dead\n---\nx\n')
        self.queue('child', '---\nid: child\nafter: dead\n---\np\n')
        q.drop_blocked(self.state)
        self.assertEqual(self.names('failed'), ['child', 'dead'])


if __name__ == '__main__':
    unittest.main()
