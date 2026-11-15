"""Tests for gmail_import (state rows for live messages only, rules seed guard) and gmail_labels."""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gmail_classify  # noqa: E402
import gmail_db  # noqa: E402
import gmail_import  # noqa: E402
import gmail_inventory  # noqa: E402
import gmail_labels  # noqa: E402

CFG = gmail_classify.rules_from_dict({
    'me': ['me@example.test'], 'freemail': ['gmail.com'],
    'rules': [{'label': 'Dev/GitHub', 'from': ['github.com']}],
    'subrules': [{'parent': 'Dev/GitHub', 'label': 'Dev/GitHub/Bots', 'from': ['bot@github.com']}],
    'protect': {'labels': ['Prawne'], 'subject': 'umowa'}})


def new_db(*rows):
    db = sqlite3.connect(':memory:')
    db.executescript(gmail_inventory.SCHEMA)
    db.executemany('INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,?,?)', [
        (i, 't', 0, 0, a, '', a.rpartition('@')[2], 'me@example.test', s, 0, lab) for i, a, s, lab in rows])
    return db


class StateRowsTest(unittest.TestCase):
    def test_alive_filter_skips_vanished_messages_and_default_keeps_all(self):
        db = new_db(('a', 'x@github.com', '', 'INBOX'), ('b', 'y@github.com', '', ''))
        self.assertEqual([r[0] for r in gmail_import.state_rows(db, CFG, set(), alive={'a'})], ['a'])
        self.assertEqual(sorted(r[0] for r in gmail_import.state_rows(db, CFG, set())), ['a', 'b'])


class RulesSeedTest(unittest.TestCase):
    def test_refuses_to_overwrite_nonempty_rules_without_force(self):
        with mock.patch.object(gmail_db, 'rules_count', return_value=12), \
                mock.patch.object(gmail_db, 'import_rules') as imp:
            with self.assertRaises(SystemExit):
                gmail_import.import_rules(Path('/nonexistent.json'), log=lambda *_: None)
            imp.assert_not_called()

    def test_seeds_an_empty_table_and_force_overrides(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as d, mock.patch.object(gmail_db, 'import_rules', return_value=3) as imp:
            f = Path(d) / 'r.json'
            f.write_text(json.dumps({'rules': []}))
            with mock.patch.object(gmail_db, 'rules_count', return_value=0):
                self.assertEqual(gmail_import.import_rules(f, log=lambda *_: None), 3)
            with mock.patch.object(gmail_db, 'rules_count', return_value=5):
                self.assertEqual(gmail_import.import_rules(f, log=lambda *_: None, force=True), 3)
            self.assertEqual(imp.call_count, 2)

    def test_all_does_not_touch_rules(self):
        with mock.patch.object(gmail_import, 'import_messages') as m, mock.patch.object(gmail_import, 'import_journals') as j, \
                mock.patch.object(gmail_import, 'import_state') as s, mock.patch.object(gmail_import, 'import_rules') as r:
            gmail_import.main(['all'])
        self.assertEqual((m.called, j.called, s.called, r.called), (True, True, True, False))


class LabelsTest(unittest.TestCase):
    def test_managed_labels_cover_rules_subrules_and_builtins(self):
        names = gmail_labels.managed_labels(CFG, {'Promocje': {'a'}, 'Nowa/Etykieta': {'b'}})
        for n in ('Dev/GitHub', 'Dev/GitHub/Bots', 'Newslettery', 'Ludzie/Wysłane', gmail_classify.FALLBACK, 'Nowa/Etykieta'):
            self.assertIn(n, names)

    def test_protected_ids(self):
        db = new_db(('star', 'x@news.example', 'hej', 'INBOX,STARRED'), ('doc', 'x@news.example', 'Umowa najmu', ''),
                    ('plain', 'x@news.example', 'hej', ''))
        self.assertEqual(gmail_labels.protected_ids(db, CFG), {'star', 'doc'})


if __name__ == '__main__':
    unittest.main()
