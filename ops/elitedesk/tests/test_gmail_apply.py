"""Unit tests for gmail_apply: label creation order, add-only writes, journal + undo."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gmail_apply import apply_categories, ensure_labels, modify_journaled, move, reconcile, undo  # noqa: E402


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
            move(g, 'trash', ['a', 'b'], {'a'}, journal, 'x', log=lambda *_: None, protected=set())
            move(g, 'archive', ['c'], {'c'}, journal, 'y', log=lambda *_: None)
            self.assertEqual(g.modified, [(('a', 'b'), ('TRASH',), ()), (('c',), (), ('INBOX',))])
            g.modified.clear()
            undo(g, journal, log=lambda *_: None)
            self.assertEqual(g.modified, [(('c',), ('INBOX',), ()),
                                          (('a', 'b'), (), ('TRASH',)), (('a',), ('INBOX',), ())])

    def test_trash_never_touches_protected_ids_and_journals_the_skip(self):
        g = FakeGmail()
        with tempfile.TemporaryDirectory() as d:
            journal = Path(d) / 'j.jsonl'
            n = move(g, 'trash', ['a', 'b', 'c'], {'a', 'b'}, journal, 'x', log=lambda *_: None, protected={'b', 'z'})
            self.assertEqual(n, 2)
            self.assertEqual(g.modified, [(('a', 'c'), ('TRASH',), ())])
            entry = json.loads(journal.read_text())
            self.assertEqual((entry['ids'], entry['inbox_ids'], entry['skipped_protected']), (['a', 'c'], ['a'], 1))

    def test_trash_of_only_protected_ids_is_a_noop(self):
        g = FakeGmail()
        with tempfile.TemporaryDirectory() as d:
            journal = Path(d) / 'j.jsonl'
            self.assertEqual(move(g, 'trash', ['b'], set(), journal, log=lambda *_: None, protected={'b'}), 0)
            self.assertEqual(g.modified, [])
            self.assertFalse(journal.exists())

    def test_trash_without_protected_is_refused(self):
        g = FakeGmail()
        with self.assertRaises(ValueError):
            move(g, 'trash', ['a'], set(), Path('/dev/null'), log=lambda *_: None)
        self.assertEqual(g.modified, [])

    def test_modify_journaled_writes_a_line_per_chunk_even_if_a_later_chunk_fails(self):
        class Flaky(FakeGmail):
            def batch_modify(self, ids, add=(), remove=()):
                if len(self.modified) == 1:
                    raise RuntimeError('boom')
                super().batch_modify(ids, add, remove)

        g = Flaky()
        with tempfile.TemporaryDirectory() as d:
            journal = Path(d) / 'j.jsonl'
            with self.assertRaises(RuntimeError):
                modify_journaled(g, journal, 'add', 'L', 'id-L', [str(i) for i in range(2500)])
            lines = [json.loads(x) for x in journal.read_text().splitlines()]
            self.assertEqual([len(e['ids']) for e in lines], [1000])   # the applied chunk is undoable

    def test_read_undo_restores_unread_only_where_it_was(self):
        g = FakeGmail()
        with tempfile.TemporaryDirectory() as d:
            journal = Path(d) / 'j.jsonl'
            move(g, 'read', ['a', 'b'], {'b'}, journal, log=lambda *_: None)
            self.assertEqual(g.modified, [(('a', 'b'), (), ('UNREAD',))])
            g.modified.clear()
            undo(g, journal, log=lambda *_: None)
            self.assertEqual(g.modified, [(('b',), ('UNREAD',), ())])

    def test_reconcile_moves_message_between_categories(self):
        g = FakeGmail(labels=['Praca/Szukanie-pracy', 'Promocje'])
        old = {'Praca/Szukanie-pracy': ['a', 'b'], 'Promocje': ['c']}
        new = {'Praca/Zatrudnienie': ['a'], 'Praca/Szukanie-pracy': ['b'], 'Promocje': ['c']}
        with tempfile.TemporaryDirectory() as d:
            journal = Path(d) / 'j.jsonl'
            reconcile(g, old, new, journal, log=lambda *_: None)
            self.assertIn((('a',), (), ('id-Praca/Szukanie-pracy',)), g.modified)
            self.assertIn((('a',), ('id-Praca/Zatrudnienie',), ()), g.modified)
            g.modified.clear()
            undo(g, journal, log=lambda *_: None)
            self.assertIn((('a',), ('id-Praca/Szukanie-pracy',), ()), g.modified)

    def test_move_rejects_unknown_op(self):
        with self.assertRaises(ValueError):
            move(FakeGmail(), 'delete', ['a'], set(), Path('/dev/null'))


if __name__ == '__main__':
    unittest.main()
