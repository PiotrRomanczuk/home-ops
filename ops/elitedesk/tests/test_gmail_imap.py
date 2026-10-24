"""Unit tests for gmail_imap parsing (no network)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gmail_imap import all_mail_box, epoch_ms, parse_labels, to_message  # noqa: E402

META = (b'7 (X-GM-THRID 1780000000000000001 X-GM-MSGID 1780000000000000002 '
        b'X-GM-LABELS ("\\\\Important" \\Inbox "Dev/GitHub" Allegro) UID 42 RFC822.SIZE 5120 '
        b'INTERNALDATE " 4-Oct-2026 18:00:00 +0200" FLAGS (\\Flagged) '
        b'BODY[HEADER.FIELDS (FROM TO CC SUBJECT LIST-UNSUBSCRIBE)] {120}')
HEADER = (b'From: =?UTF-8?Q?Sklep_=C5=81=C3=B3d=C5=BA?= <Promo@Sklep.PL>\r\n'
          b'To: p.romanczuk@gmail.com\r\nSubject: =?UTF-8?Q?Zni=C5=BCki?=\r\n'
          b'List-Unsubscribe: <mailto:u@sklep.pl>\r\n\r\n')


class ImapParseTest(unittest.TestCase):
    def test_to_message_matches_rest_shape(self):
        msg = to_message(META, HEADER, {42: 'promotions'})
        self.assertEqual(msg['id'], format(1780000000000000002, 'x'))
        self.assertEqual(msg['sizeEstimate'], 5120)
        self.assertEqual(sorted(msg['labelIds']), sorted(
            ['IMPORTANT', 'INBOX', 'Dev/GitHub', 'Allegro', 'UNREAD', 'CATEGORY_PROMOTIONS']))
        hdrs = {h['name']: h['value'] for h in msg['payload']['headers']}
        self.assertEqual(hdrs['Subject'], 'Zniżki')
        self.assertIn('promo@sklep.pl', hdrs['From'].lower())

    def test_malformed_header_does_not_raise(self):
        bad = b'From: "Broken\r\n Name" <x@y.pl>\r\nSubject: =?bogus?Q?x?=\r\n\r\n'
        msg = to_message(META, bad, {})
        hdrs = {h['name']: h['value'] for h in msg['payload']['headers']}
        self.assertIn('x@y.pl', hdrs['From'])

    def test_seen_message_not_unread(self):
        msg = to_message(META.replace(b'(\\Flagged)', b'(\\Seen)'), HEADER, {})
        self.assertNotIn('UNREAD', msg['labelIds'])

    def test_epoch_ms(self):
        self.assertEqual(epoch_ms(' 4-Oct-2026 18:00:00 +0200'), 1791129600000)

    def test_parse_labels_quoted_with_spaces(self):
        self.assertEqual(parse_labels('"IU Uni" \\Sent'), ['IU Uni', 'SENT'])

    def test_all_mail_box_localised(self):
        lines = [b'(\\HasNoChildren) "/" "INBOX"',
                 b'(\\All \\HasNoChildren) "/" "[Gmail]/Wszystkie"']
        self.assertEqual(all_mail_box(lines), '"[Gmail]/Wszystkie"')


if __name__ == '__main__':
    unittest.main()
