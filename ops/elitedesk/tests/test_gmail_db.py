"""Unit tests for gmail_db pure helpers: row shaping, journal flattening, COPY block."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gmail_db import APPLIED_COLS, copy_block, journal_rows, message_row  # noqa: E402


class MessageRow(unittest.TestCase):
    def test_sqlite_row_maps_to_pg_columns(self):
        row = message_row(('abc', 'thr', 1792860857000, 1234, 'a@x.pl', 'A', 'x.pl', 'me@g.com', 'Hi', 1, 'INBOX,UNREAD'))
        self.assertEqual(row[0], 'abc')
        self.assertTrue(row[2].startswith('2026-10-24T'))
        self.assertEqual(row[9], True)
        self.assertEqual(row[10], 'INBOX,UNREAD')

    def test_nulls_become_defaults(self):
        row = message_row(('abc', None, None, None, None, None, None, None, None, None, None))
        self.assertEqual(row[3:], (0, '', '', '', '', '', False, ''))


class JournalRows(unittest.TestCase):
    def _write(self, lines):
        d = tempfile.mkdtemp()
        p = Path(d) / 'journal-test.jsonl'
        p.write_text('\n'.join(json.dumps(x) for x in lines) + '\n')
        return p

    def test_trash_rows_carry_inbox_flag(self):
        p = self._write([{'ts': 1792862375, 'op': 'trash', 'note': 'Promocje >=90d', 'ids': ['a', 'b'], 'inbox_ids': ['b']}])
        rows = journal_rows(p)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][:5], ('journal-test.jsonl', 1, 'a', 'trash', 'TRASH'))
        self.assertFalse(rows[0][5])
        self.assertTrue(rows[1][5])
        self.assertEqual(rows[0][6], 'Promocje >=90d')

    def test_add_uses_label_and_label_ops_get_one_row(self):
        p = self._write([{'ts': 1, 'op': 'add', 'label': 'Ludzie', 'label_id': 'Label_1', 'ids': ['a']},
                         {'ts': 2, 'op': 'label-delete', 'label': 'GitHub'}])
        rows = journal_rows(p)
        self.assertEqual(rows[0][3:5], ('add', 'Ludzie'))
        self.assertEqual(rows[1][2:5], ('', 'label-delete', 'GitHub'))

    def test_blank_lines_skipped(self):
        p = self._write([{'ts': 1, 'op': 'read', 'ids': ['a'], 'inbox_ids': ['a']}])
        p.write_text(p.read_text() + '\n\n')
        self.assertEqual(len(journal_rows(p)), 1)


class CopyBlock(unittest.TestCase):
    def test_csv_with_booleans_nulls_and_terminator(self):
        block = copy_block('gmail.applied', APPLIED_COLS, [('j', 1, 'a', 'trash', None, True, 'x,y', '2026-01-01T00:00:00+00:00')])
        self.assertTrue(block.startswith('COPY gmail.applied (journal, line_no, message_id, op, label, had_inbox, note, ts) FROM STDIN'))
        self.assertIn('j,1,a,trash,\\N,t,"x,y",2026-01-01T00:00:00+00:00\n', block)
        self.assertIn("NULL '\\N'", block)
        self.assertTrue(block.endswith('\\.\n'))


if __name__ == '__main__':
    unittest.main()
