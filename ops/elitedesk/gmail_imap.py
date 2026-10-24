"""gmail_imap.py — fast read-only inventory over IMAP (XOAUTH2).

The REST API meters every messages.get against a per-minute quota (~3 msg/s
in practice for this project); IMAP FETCH returns thousands of headers per
round-trip. Rows land in the same `messages` table as gmail_inventory.sync,
keyed by the REST message id (hex of X-GM-MSGID), so labelling via REST
batchModify keeps working. The mailbox is opened read-only (EXAMINE).
"""
from __future__ import annotations

import imaplib
import re
import sqlite3
from email.header import decode_header, make_header
from email.parser import BytesHeaderParser
from email.policy import compat32
from email.utils import parsedate_to_datetime

from gmail_inventory import to_row

HOST = 'imap.gmail.com'
FETCH = ('(UID X-GM-MSGID X-GM-THRID X-GM-LABELS FLAGS RFC822.SIZE INTERNALDATE '
         'BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT LIST-UNSUBSCRIBE)])')
SYSTEM = {'\\Inbox': 'INBOX', '\\Sent': 'SENT', '\\Important': 'IMPORTANT',
          '\\Starred': 'STARRED', '\\Draft': 'DRAFT'}
CATEGORIES = ('promotions', 'social', 'updates', 'forums', 'personal')
_FIELDS = {
    'uid': re.compile(rb'UID (\d+)'), 'msgid': re.compile(rb'X-GM-MSGID (\d+)'),
    'thrid': re.compile(rb'X-GM-THRID (\d+)'), 'size': re.compile(rb'RFC822\.SIZE (\d+)'),
    'date': re.compile(rb'INTERNALDATE "([^"]+)"'), 'flags': re.compile(rb'FLAGS \(([^)]*)\)'),
    'labels': re.compile(rb'X-GM-LABELS \(((?:[^()"]|"(?:[^"\\]|\\.)*")*)\)'),
}
_LABEL = re.compile(r'"((?:[^"\\]|\\.)*)"|(\S+)')


def connect(email: str, token: str) -> imaplib.IMAP4_SSL:
    imap = imaplib.IMAP4_SSL(HOST)
    imap.authenticate('XOAUTH2', lambda _: f'user={email}\x01auth=Bearer {token}\x01\x01'.encode())
    return imap


def all_mail_box(list_lines: list[bytes]) -> str:
    """Quoted name of the \\All folder ('"[Gmail]/Wszystkie"' on a Polish account)."""
    for line in list_lines:
        if b'\\All' in line:
            name = line.decode().rsplit(' "/" ', 1)[1]
            return name if name.startswith('"') else f'"{name}"'
    raise RuntimeError('no \\All mailbox')


def parse_labels(raw: str) -> list[str]:
    names = [re.sub(r'\\(.)', r'\1', q) if q else b for q, b in _LABEL.findall(raw)]
    return [SYSTEM.get(n, n) for n in names]


def decode(value: str) -> str:
    """RFC 2047 → text, tolerant of malformed headers (keeps the raw value on failure)."""
    try:
        return str(make_header(decode_header(value))).replace('\r', ' ').replace('\n', ' ')
    except (ValueError, LookupError, UnicodeError):
        return value


def epoch_ms(internaldate: str) -> int:
    """'24-Oct-2026 18:00:00 +0200' → epoch milliseconds."""
    return int(parsedate_to_datetime(internaldate.strip().replace('-', ' ', 2)).timestamp() * 1000)


def to_message(meta: bytes, header: bytes, categories: dict[int, str]) -> dict:
    """Shape one FETCH item like a REST messages.get(format=metadata) resource."""
    f = {k: (m.group(1) if (m := rx.search(meta)) else b'') for k, rx in _FIELDS.items()}
    labels = parse_labels(f['labels'].decode('utf-8', 'replace'))
    if b'\\Seen' not in f['flags']:
        labels.append('UNREAD')
    if cat := categories.get(int(f['uid'])):
        labels.append(f'CATEGORY_{cat.upper()}')
    msg = BytesHeaderParser(policy=compat32).parsebytes(header)
    return {'id': format(int(f['msgid']), 'x'), 'threadId': format(int(f['thrid']), 'x'),
            'internalDate': epoch_ms(f['date'].decode()) if f['date'] else 0,
            'sizeEstimate': int(f['size'] or 0), 'labelIds': labels,
            'payload': {'headers': [{'name': k, 'value': decode(str(v))} for k, v in msg.items()]}}


def category_uids(imap: imaplib.IMAP4_SSL) -> dict[int, str]:
    out: dict[int, str] = {}
    for cat in CATEGORIES:
        data = imap.uid('SEARCH', 'X-GM-RAW', f'"category:{cat}"')[1]
        out.update((int(uid), cat) for uid in (data[0] or b'').split())
    return out


def sync(imap: imaplib.IMAP4_SSL, db: sqlite3.Connection, chunk: int = 2000, log=print) -> int:
    imap.select(all_mail_box(imap.list()[1]), readonly=True)
    uids = imap.uid('SEARCH', None, 'ALL')[1][0].split()
    cats = category_uids(imap)
    log(f'{len(uids)} messages in All Mail, {len(cats)} with a category tab')
    done = 0
    for i in range(0, len(uids), chunk):
        data = imap.uid('FETCH', b','.join(uids[i:i + chunk]).decode(), FETCH)[1]
        rows = [to_row(to_message(it[0], it[1], cats)) for it in data if isinstance(it, tuple)]
        db.executemany(f'INSERT OR REPLACE INTO messages VALUES ({",".join("?" * 11)})', rows)
        db.commit()
        done += len(rows)
        log(f'  {done}/{len(uids)}')
    return done
