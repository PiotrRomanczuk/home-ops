"""gmail_llm_daily: weak senders, archive selection, Dziś questions/answers (DB and model mocked)."""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gmail_inventory  # noqa: E402
import gmail_llm  # noqa: E402
import gmail_llm_daily as daily  # noqa: E402
from gmail_classify import rules_from_dict  # noqa: E402

ME = 'p.romanczuk@gmail.com'
CFG = rules_from_dict({'me': [ME], 'freemail': ['gmail.com'], 'protect': {'labels': ['Prawne']},
                       'rules': [{'label': 'Dev/GitHub', 'from': ['github.com']},
                                 {'label': 'Zakupy', 'from': ['allegro.pl'], 'inbox': 'archive'},
                                 {'label': 'Prawne', 'from': ['kancelaria.pl'], 'inbox': 'archive'}]})


def inventory(rows):
    db = sqlite3.connect(':memory:')
    db.executescript(gmail_inventory.SCHEMA)
    db.executemany('INSERT INTO messages (id, internal_ms, from_addr, from_name, subject, labels, to_addrs, has_unsub) '
                   'VALUES (?,?,?,?,?,?,?,?)', [(*r, ME, u) for *r, u in rows])
    return db


class WeakSendersTest(unittest.TestCase):
    def test_weak_senders_and_rule_filed_examples(self):
        db = inventory([('1', 3, 'news@shop.io', 'Shop', 'Promo', 'CATEGORY_PROMOTIONS', 1),
                        ('2', 2, 'news@shop.io', 'Shop', 'Sale', 'CATEGORY_PROMOTIONS', 1),
                        ('3', 1, 'notifications@github.com', 'GitHub', 'PR', 'INBOX', 0),
                        ('4', 1, 'x@mixed.io', '', 'a', 'CATEGORY_UPDATES', 0),
                        ('5', 1, 'x@mixed.io', '', 'b', 'CATEGORY_UPDATES', 0),
                        ('6', 1, 'old@gone.io', '', 'c', 'CATEGORY_PROMOTIONS', 1),
                        ('7', 1, 'known@done.io', '', 'd', 'CATEGORY_PROMOTIONS', 1)])
        out, labelled = daily.sender_digests(db, CFG, trash={'6'}, skip={'known@done.io'})
        self.assertEqual([s['sender'] for s in out], ['news@shop.io', 'x@mixed.io'])
        self.assertEqual([(s['sender'], s['label']) for s in labelled], [('notifications@github.com', 'Dev/GitHub')])
        shop = out[0]
        self.assertEqual((shop['n'], shop['tab'], shop['unsub_share'], shop['subjects']),
                         (2, 'promotions', 1.0, ['Promo', 'Sale']))

    def test_model_labels_cover_rules_and_builtins(self):
        labels = daily.model_labels(CFG)
        self.assertIn('Dev/GitHub', labels)
        self.assertIn(gmail_llm.REVIEW, labels)


class ArchiveTest(unittest.TestCase):
    def test_archive_only_inbox_mail_of_archive_rules_and_never_protected(self):
        db = inventory([('1', 1, 'sklep@allegro.pl', '', 'Zamówienie', 'INBOX', 0),
                        ('2', 1, 'sklep@allegro.pl', '', 'Zamówienie', 'INBOX STARRED', 0),
                        ('3', 1, 'sklep@allegro.pl', '', 'Stare', '', 0),
                        ('4', 1, 'biuro@kancelaria.pl', '', 'Pismo', 'INBOX', 0),
                        ('5', 1, 'notifications@github.com', '', 'PR', 'INBOX', 0)])
        self.assertEqual(daily.archive_ids(db, CFG, inbox={'1', '2', '4', '5'}), ['1'])


class FakeReporter:
    def __init__(self, answers=(), open_refs=()):
        self._answers, self._open, self.asked, self.consumed = list(answers), set(open_refs), [], []

    def answers(self):
        return self._answers

    def consume(self, i):
        self.consumed.append(i)

    def open_refs(self):
        return self._open

    def ask(self, q, **kw):
        self.asked.append((q, kw))
        return {'id': 100 + len(self.asked)}


PROPOSALS = [{'id': i, 'sender': f's{i}@x.pl', 'sender_key': f's{i}@x.pl', 'label': 'Zakupy', 'inbox': 'archive',
              'model': 'm', 'confidence': 0.9, 'reason': 'r', 'decision_id': None, 'sample': {'n': 3, 'subjects': ['a']}}
             for i in (1, 2, 3, 4, 5)]


class DzisTest(unittest.TestCase):
    def test_consume_accepts_rejects_and_marks_consumed(self):
        rep = FakeReporter([{'id': 7, 'ref': 'gmail-proposal:1', 'answer': 'tak'},
                            {'id': 8, 'ref': 'gmail-proposal:2', 'answer': 'tak-zostaw'},
                            {'id': 9, 'ref': 'gmail-proposal:3', 'answer': 'nie'},
                            {'id': 10, 'ref': 'pr:other', 'answer': 'yes'}])
        with mock.patch('gmail_llm_db.proposed', return_value=PROPOSALS), \
             mock.patch('gmail_llm_db.accept') as accept, mock.patch('gmail_llm_db.reject') as reject:
            self.assertEqual(daily.consume(rep, log=lambda *_: None), 3)
        accept.assert_any_call(1, 'Zakupy', 'archive', 'dzis')
        accept.assert_any_call(2, 'Zakupy', 'keep', 'dzis')
        reject.assert_called_once_with(3, 'dzis')
        self.assertEqual(rep.consumed, [7, 8, 9])

    def test_ask_tops_up_to_three_open_questions(self):
        rep = FakeReporter(open_refs={'gmail-proposal:1', 'pr:x'})
        with mock.patch('gmail_llm_db.proposed', return_value=PROPOSALS), \
             mock.patch('gmail_llm_db.set_decision') as set_decision:
            self.assertEqual(daily.ask(rep, log=lambda *_: None), 2)
        self.assertEqual([kw['ref'] for _, kw in rep.asked], ['gmail-proposal:2', 'gmail-proposal:3'])
        self.assertIn('do archiwum', rep.asked[0][0])
        set_decision.assert_any_call(2, 101)

    def test_propose_batches_and_stops_when_claude_fails(self):
        ok = ([gmail_llm.Proposal('a@x.pl', 'Zakupy', 'keep', 'address', 0.9, 'r')],
              {'structured_output': {'proposals': [{'sender': 'a@x.pl', 'label': 'Zakupy'}]}, 'total_cost_usd': 0.01})
        calls = iter([ok, gmail_llm.ClaudeError('limit')])

        def fake(*_a, **_k):
            item = next(calls)
            if isinstance(item, Exception):
                raise item
            return item

        with mock.patch('gmail_llm.propose_batch', side_effect=fake), mock.patch.object(gmail_llm, 'BATCH', 1):
            rows, reachable = daily.propose([{'sender': 'a@x.pl'}, {'sender': 'b@x.pl'}, {'sender': 'c@x.pl'}],
                                            ['Zakupy'], [], log=lambda *_: None)
        self.assertEqual((len(rows), reachable), (1, False))
        self.assertEqual(rows[0][:5], ('a@x.pl', 'a@x.pl', 'address', 'Zakupy', 'keep'))
        self.assertIn('"item": {"sender": "a@x.pl"', rows[0][-1])  # raw answer kept with the proposal


if __name__ == '__main__':
    unittest.main()
