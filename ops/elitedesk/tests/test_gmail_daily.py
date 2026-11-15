"""Tests for the gmail-daily routine against a fake Gmail + in-memory SQLite (no network, no Postgres).

Covers: every inventory row reaches Postgres (restored / retried messages), messages deleted from the
mailbox are never labelled or given state, label reconciliation by exact label id.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import gmail_db  # noqa: E402
import gmail_inventory  # noqa: E402

spec = importlib.util.spec_from_file_location('gmail_daily', HERE / 'gmail-daily.py')
daily_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily_mod)

RAW_RULES = {'me': ['me@example.test'], 'freemail': ['gmail.com'], 'rules': [
    {'label': 'Dev/GitHub', 'from': ['github.com']},
    {'label': 'Stara', 'from': ['old.example']}]}


def inv_row(i, addr='noreply@github.com', labels='INBOX'):
    return (i, 't' + i, 1_700_000_000_000, 100, addr, '', addr.rpartition('@')[2], 'me@example.test', 's', 0, labels)


def new_db(*ids):
    db = sqlite3.connect(':memory:')
    db.executescript(gmail_inventory.SCHEMA)
    db.executemany('INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,?,?)', [inv_row(i) for i in ids])
    return db


class FakeGmail:
    """Label membership per message id; ids missing from `msgs` and `trash` do not exist (batchModify → 404)."""

    def __init__(self, msgs: dict[str, set[str]], trash=(), labels=()):
        self.msgs, self.trash = msgs, set(trash)
        self._labels = [{'name': n, 'id': f'id-{n}'} for n in labels]
        self.created: list[str] = []
        self.modified: list[tuple] = []
        self.queries: list[tuple] = []

    def labels(self):
        return self._labels

    def create_label(self, name):
        self.created.append(name)
        lab = {'name': name, 'id': f'id-{name}'}
        self._labels.append(lab)
        return lab

    def iter_ids(self, query='', *, label_ids=None, limit=None):
        self.queries.append((query, tuple(label_ids or ())))
        if label_ids:
            return iter([i for i, ls in self.msgs.items() if set(label_ids) <= ls])
        pick = {'in:trash': self.trash, 'in:inbox': {i for i, ls in self.msgs.items() if 'INBOX' in ls},
                'is:unread -in:trash': {i for i, ls in self.msgs.items() if 'UNREAD' in ls}}
        return iter(sorted(pick[query]))

    def batch_modify(self, ids, add=(), remove=()):
        self.modified.append((tuple(ids), tuple(add), tuple(remove)))
        for i in ids:
            if i not in self.msgs:
                raise RuntimeError(f'404 message {i} does not exist')
            self.msgs[i] |= set(add)
            self.msgs[i] -= set(remove)


class DailyTest(unittest.TestCase):
    def run_daily(self, db, gmail, present, sync_rows=(), upsert=None, **kw):
        """One `daily` run; returns (stats, upserted ids, state rows)."""
        upserted: list[str] = []
        state: list[tuple] = []
        self.applied: list = []

        def fake_sync(d, log):
            d.executemany('INSERT OR REPLACE INTO messages VALUES (?,?,?,?,?,?,?,?,?,?,?)', list(sync_rows))
            return len(sync_rows), set(present)

        def fake_upsert(rows):
            if upsert:
                upsert()
            upserted.extend(r[0] for r in rows)
            return len(rows)

        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(gmail_db, 'upsert_messages', fake_upsert), \
                mock.patch.object(gmail_db, 'load_rules', lambda: RAW_RULES), \
                mock.patch.object(gmail_db, 'insert_applied', lambda rows: self.applied.extend(rows) or len(rows)), \
                mock.patch.object(gmail_db, 'replace_state', lambda rows: state.extend(rows) or len(rows)):
            stats = daily_mod.daily(gmail, db, fake_sync, Path(d) / 'j.jsonl', log=lambda *_: None, **kw)
        return stats, upserted, state

    def test_restored_and_new_messages_both_reach_postgres(self):
        db = new_db('a', 'b', 'c')
        # 'a' was restored from Trash → re-inserted with a higher rowid than the genuinely new 'n'
        gmail = FakeGmail({i: {'INBOX'} for i in 'abcn'})
        stats, upserted, state = self.run_daily(db, gmail, present='abcn', sync_rows=[inv_row('n'), inv_row('a')])
        self.assertEqual(sorted(upserted), ['a', 'b', 'c', 'n'])
        self.assertEqual(stats['new'], 1)
        self.assertTrue({r[0] for r in state} <= set(upserted))
        self.assertEqual(len(state), 4)

    def test_postgres_failure_then_retry_still_uploads_the_new_message(self):
        db = new_db('a')
        boom = mock.Mock(side_effect=RuntimeError('psql down'))
        with self.assertRaises(RuntimeError):
            self.run_daily(db, FakeGmail({'a': set(), 'n': set()}), present='an', sync_rows=[inv_row('n')], upsert=boom)
        # the retry sees 'n' already in SQLite (new_ids is empty) but still sends it
        stats, upserted, state = self.run_daily(db, FakeGmail({'a': set(), 'n': set()}), present='an')
        self.assertEqual(stats['new'], 0)
        self.assertEqual(sorted(upserted), ['a', 'n'])
        self.assertEqual(sorted(r[0] for r in state), ['a', 'n'])

    def test_message_deleted_from_mailbox_is_not_labelled_and_has_no_state(self):
        db = new_db('a', 'gone', 'tr')
        gmail = FakeGmail({'a': {'INBOX'}}, trash={'tr'})
        stats, upserted, state = self.run_daily(db, gmail, present='a')
        touched = {i for ids, _, _ in gmail.modified for i in ids}
        self.assertEqual(touched, {'a'})                                  # 'gone' would 404 in batchModify
        self.assertEqual(sorted(r[0] for r in state), ['a', 'tr'])        # trash keeps its state, deleted does not
        self.assertEqual(stats['gone'], 1)
        self.assertIn('gone', upserted)                                   # the header catalogue keeps it
        self.assertIn('id-Dev/GitHub', gmail.msgs['a'])

    def test_empty_all_mail_is_refused(self):
        with self.assertRaises(RuntimeError):
            self.run_daily(new_db('a'), FakeGmail({'a': set()}), present=())

    def test_stale_label_is_removed_even_when_no_message_expects_it(self):
        db = new_db('a')
        gmail = FakeGmail({'a': {'id-Stara'}}, labels=['Stara'])   # 'Stara' rule matches nothing any more
        self.run_daily(db, gmail, present='a')
        self.assertEqual(gmail.msgs['a'], {'id-Dev/GitHub'})
        self.assertNotIn('Stara', gmail.created)

    def test_only_labels_with_messages_are_created_and_members_read_by_label_id(self):
        gmail = FakeGmail({'a': set()})
        self.run_daily(new_db('a'), gmail, present='a')
        self.assertEqual(sorted(gmail.created), ['Dev', 'Dev/GitHub'])   # no empty Ludzie/Promocje/… labels
        label_queries = [q for q in gmail.queries if q[1]]
        self.assertTrue(label_queries)
        self.assertFalse(any(q[0].startswith('label:') for q in gmail.queries))

    def test_second_run_changes_nothing(self):
        db, gmail = new_db('a'), FakeGmail({'a': {'INBOX'}})
        self.run_daily(db, gmail, present='a')
        gmail.modified.clear()
        stats, *_ = self.run_daily(db, gmail, present='a')
        self.assertEqual((stats['added'], stats['removed'], gmail.modified), (0, 0, []))


class BrokenReporter:
    """"Dziś" is down: every call raises."""

    def answers(self):
        raise RuntimeError('ingest down')

    def open_refs(self):
        raise RuntimeError('ingest down')


class LlmFenceTest(unittest.TestCase):
    """The model / "Dziś" steps may fail; labels, journal, message_state and the card input must not."""

    run_daily = DailyTest.run_daily

    def test_dzis_and_psql_failures_do_not_stop_the_run(self):
        db, gmail = new_db('a'), FakeGmail({'a': {'INBOX'}})
        with mock.patch('gmail_llm_db.proposed', side_effect=RuntimeError('migration 031 missing')), \
             mock.patch('gmail_llm_db.known_senders', side_effect=RuntimeError('psql down')):
            stats, upserted, state = self.run_daily(db, gmail, present='a', reporter=BrokenReporter(), llm=True)
        self.assertEqual((stats['proposed'], stats['archived']), (0, 0))
        self.assertIn('id-Dev/GitHub', gmail.msgs['a'])        # reconcile_live still ran
        self.assertEqual([r[0] for r in state], ['a'])         # replace_state still ran
        self.assertTrue(self.applied)                          # insert_applied still ran (the label journal)

    def test_archive_passes_the_protected_ids_and_keeps_the_journal(self):
        db, gmail = new_db('a', 'b'), FakeGmail({'a': {'INBOX'}, 'b': {'INBOX'}})
        with mock.patch('gmail_llm_db.known_senders', return_value=set()), \
             mock.patch('gmail_llm_db.insert_proposals', return_value=0), \
             mock.patch.object(daily_mod.gmail_llm_daily, 'archive_ids', return_value=['a']), \
             mock.patch('gmail_labels.protected_ids', return_value={'b'}) as prot, \
             mock.patch('gmail_apply.move', return_value=1) as move:
            stats, *_ = self.run_daily(db, gmail, present='ab', llm=True)
        self.assertEqual(stats['archived'], 1)
        self.assertEqual(move.call_args.kwargs['protected'], {'b'})
        prot.assert_called_once()


if __name__ == '__main__':
    unittest.main()
