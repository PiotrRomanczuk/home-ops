"""Unit tests for gmail_apply: label creation order, add-only writes, journal + undo."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gmail_apply import apply_categories, ensure_labels, move, undo  # noqa: E402


class FakeGmail:
    def __init__(self, labels=()):
        self._labels = [{'name': n, 'id': f'id-{n}'} for n in labels]
        self.created: list[str] = []
        self.modified: list[tuple] = []

    def labels(self):
        return self._labels

    def create_label(self, name):
        self.created.append(name)
        lab = {'name': name, 'id': f'id-{name}'}
        self._labels.append(lab)
        return lab

    def batch_modify(self, ids, add=(), remove=()):
        self.modified.append((tuple(ids), tuple(add), tuple(remove)))


class ApplyTest(unittest.TestCase):
    def test_parents_created_before_children_and_existing_reused(self):
        g = FakeGmail(labels=['Dev'])
        out = ensure_labels(g, ['Dev/GitHub', 'Finanse/Faktury'], log=lambda *_: None)
        self.assertEqual(g.created, ['Dev/GitHub', 'Finanse', 'Finanse/Faktury'])
        self.assertEqual(out, {'Dev/GitHub': 'id-Dev/GitHub', 'Finanse/Faktury': 'id-Finanse/Faktury'})

    def test_apply_only_adds_and_undo_reverses(self):
        g = FakeGmail()
        with tempfile.TemporaryDirectory() as d:
            journal = Path(d) / 'j.jsonl'
            n = apply_categories(g, {'Promocje': ['a', 'b'], 'Ludzie': ['c']}, journal, log=lambda *_: None)
            self.assertEqual(n, 3)
            self.assertTrue(all(not remove for _, _, remove in g.modified))
            self.assertEqual(g.modified[0], (('a', 'b'), ('id-Promocje',), ()))
            g.modified.clear()
            self.assertEqual(undo(g, journal, log=lambda *_: None), 3)
            self.assertEqual(sorted(g.modified), [(('a', 'b'), (), ('id-Promocje',)),
                                                  (('c',), (), ('id-Ludzie',))])


    def test_trash_and_archive_undo_restore_inbox(self):
        g = FakeGmail()
        with tempfile.TemporaryDirectory() as d:
            journal = Path(d) / 'j.jsonl'
            move(g, 'trash', ['a', 'b'], {'a'}, journal, 'x', log=lambda *_: None)
            move(g, 'archive', ['c'], {'c'}, journal, 'y', log=lambda *_: None)
            self.assertEqual(g.modified, [(('a', 'b'), ('TRASH',), ()), (('c',), (), ('INBOX',))])
            g.modified.clear()
            undo(g, journal, log=lambda *_: None)
            self.assertEqual(g.modified, [(('c',), ('INBOX',), ()),
                                          (('a', 'b'), (), ('TRASH',)), (('a',), ('INBOX',), ())])

    def test_move_rejects_unknown_op(self):
        with self.assertRaises(ValueError):
            move(FakeGmail(), 'delete', ['a'], set(), Path('/dev/null'))


if __name__ == '__main__':
    unittest.main()
