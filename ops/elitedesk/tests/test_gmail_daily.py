"""Tests for the gmail-daily routine against a fake Gmail + in-memory SQLite (no network, no Postgres).

Covers: refusal on empty rules / too many changes, card failures never fail a run, labels of disabled rules
stay managed, every inventory row reaches Postgres (restored / retried messages), messages deleted from the
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
    def run_daily(self, db, gmail, present, sync_rows=(), upsert=None, rules=RAW_RULES, rule_labels=(), **kw):
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
                mock.patch.object(gmail_db, 'load_rules', lambda: rules), \
                mock.patch.object(gmail_db, 'rule_labels', lambda: list(rule_labels)), \
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
        gmail = FakeGmail({'a': set()}, labels=['Stara'])    # existing labels are read by id, new ones are empty
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

    def test_empty_rules_or_me_refuse_before_anything_is_mirrored_or_changed(self):
        for broken in ({**RAW_RULES, 'rules': []}, {**RAW_RULES, 'me': []}):
            db, gmail, synced = new_db('a'), FakeGmail({'a': {'id-Stara'}}, labels=['Stara']), []
            with mock.patch.object(gmail_db, 'load_rules', lambda broken=broken: broken), \
                    self.assertRaisesRegex(RuntimeError, 'not seeded'):
                daily_mod.daily(gmail, db, lambda d, lg: synced.append(1), Path('j.jsonl'), log=lambda *_: None)
            self.assertEqual((synced, gmail.modified, gmail.created, gmail.queries), ([], [], [], []))

    def test_too_many_changes_are_refused_before_any_write(self):
        gmail = FakeGmail({i: set() for i in 'abc'})
        expected = {'Dev/GitHub': set('abc')}
        with tempfile.TemporaryDirectory() as d, self.assertRaisesRegex(RuntimeError, '3 label changes'):
            daily_mod.reconcile_live(gmail, expected, set('abc'), Path(d) / 'j.jsonl', lambda *_: None, max_changes=2)
        self.assertEqual((gmail.modified, gmail.created), ([], []))
        with tempfile.TemporaryDirectory() as d:  # exactly at the limit is allowed
            added, _ = daily_mod.reconcile_live(gmail, expected, set('abc'), Path(d) / 'j.jsonl', lambda *_: None, max_changes=3)
        self.assertEqual(added, 3)

    def test_limit_counts_removals_too_and_default_is_5000(self):
        self.assertEqual(daily_mod.MAX_CHANGES, 5000)
        gmail = FakeGmail({i: {'id-Stara'} for i in 'ab'}, labels=['Stara'])
        with tempfile.TemporaryDirectory() as d, self.assertRaises(RuntimeError):
            daily_mod.reconcile_live(gmail, {}, set('ab'), Path(d) / 'j.jsonl', lambda *_: None, ['Stara'], max_changes=1)
        self.assertEqual(gmail.modified, [])

    def test_label_of_a_disabled_rule_is_still_managed_so_messages_keep_one_category(self):
        db = new_db('a')
        # 'Wylaczona' has enabled = false → absent from rules_json(), only gmail_db.rule_labels() knows it
        gmail = FakeGmail({'a': {'id-Wylaczona'}}, labels=['Wylaczona'])
        self.run_daily(db, gmail, present='a', rule_labels=['Wylaczona', 'Dev/GitHub'])
        self.assertEqual(gmail.msgs['a'], {'id-Dev/GitHub'})

    def test_disabled_rule_label_left_alone_without_rule_labels(self):
        gmail = FakeGmail({'a': {'id-Wylaczona'}}, labels=['Wylaczona'])
        self.run_daily(new_db('a'), gmail, present='a')
        self.assertEqual(gmail.msgs['a'], {'id-Wylaczona', 'id-Dev/GitHub'})   # the bug the test above guards


class CardTest(unittest.TestCase):
    def test_post_card_swallows_systemexit_from_missing_env(self):
        logged: list[str] = []
        with mock.patch.dict('os.environ', {}, clear=True):
            daily_mod.post_card('h', 'ok', log=logged.append)   # Reporter.from_env raises SystemExit
        self.assertTrue(logged and 'card not posted' in logged[0])

    def test_post_card_swallows_network_errors(self):
        with mock.patch.dict('os.environ', {'INGEST_URL': 'http://127.0.0.1:9', 'INGEST_TOKEN': 't'}):
            daily_mod.post_card('h', 'ok', log=lambda *_: None)

    def test_successful_run_exits_0_even_when_the_card_cannot_be_posted(self):
        stats = {'new': 0, 'added': 0, 'removed': 0, 'inbox': 0, 'review': 0, 'gone': 0}
        with mock.patch.dict('os.environ', {}, clear=True), mock.patch.object(daily_mod.gmail_inventory, 'STATE_DIR', Path('.')):
            with mock.patch.object(daily_mod, 'daily', lambda *a, **k: stats), \
                    mock.patch.object(daily_mod, 'Gmail', mock.MagicMock()), \
                    mock.patch.object(daily_mod.gmail_auth, 'access_token', mock.Mock()), \
                    mock.patch.object(daily_mod.gmail_inventory, 'connect', mock.Mock()), \
                    mock.patch.object(daily_mod.gmail_imap, 'connect', mock.Mock()), \
                    mock.patch.object(daily_mod.gmail_imap, 'close', mock.Mock()):
                self.assertEqual(daily_mod.main(), 0)

    def test_refusal_posts_an_error_card_and_fails_the_run(self):
        with mock.patch.object(daily_mod.gmail_inventory, 'STATE_DIR', Path('.')), \
                mock.patch.object(daily_mod, 'daily', mock.Mock(side_effect=RuntimeError('rules empty'))), \
                mock.patch.object(daily_mod, 'Gmail', mock.MagicMock()), \
                mock.patch.object(daily_mod, 'post_card') as card, \
                mock.patch.object(daily_mod.gmail_auth, 'access_token', mock.Mock()), \
                mock.patch.object(daily_mod.gmail_inventory, 'connect', mock.Mock()), \
                mock.patch.object(daily_mod.gmail_imap, 'connect', mock.Mock()), \
                mock.patch.object(daily_mod.gmail_imap, 'close') as close:
            with self.assertRaises(RuntimeError):
                daily_mod.main()
        self.assertEqual(card.call_args.args[1], 'error')
        self.assertIn('rules empty', card.call_args.args[0])
        close.assert_called_once()


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
