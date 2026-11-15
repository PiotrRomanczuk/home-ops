"""gmail_inventory.py — local SQLite snapshot of every message's metadata.

Read-only against Gmail. Resumable: ids already stored are skipped, so the
first full pass (~105k messages, ~40 min) can be interrupted and restarted.
The table is the input for gmail_classify.py and, later, the daily analysis.
"""
from __future__ import annotations

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from email.utils import getaddresses, parseaddr
from pathlib import Path

from gmail_api import Gmail

STATE_DIR = Path(os.environ.get('GMAIL_STATE_DIR',
                                Path.home() / '.local' / 'state' / 'home-ops' / 'gmail'))
DB_PATH = STATE_DIR / 'inventory.sqlite'
HEADERS = ('From', 'To', 'Cc', 'Subject', 'Date', 'List-Unsubscribe')
SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, thread_id TEXT, internal_ms INTEGER, size INTEGER,
  from_addr TEXT, from_name TEXT, from_domain TEXT, to_addrs TEXT,
  subject TEXT, has_unsub INTEGER, labels TEXT
);
CREATE INDEX IF NOT EXISTS messages_from ON messages(from_addr);
CREATE INDEX IF NOT EXISTS messages_domain ON messages(from_domain);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db


def to_row(msg: dict) -> tuple:
    """Flatten a messages.get(format=metadata) resource into a table row."""
    hdrs: dict[str, str] = {}
    for h in msg.get('payload', {}).get('headers', []):
        hdrs.setdefault(h['name'].lower(), h['value'])
    name, addr = parseaddr(hdrs.get('from', ''))
    addr = addr.lower()
    recipients = getaddresses([hdrs.get('to', ''), hdrs.get('cc', '')])
    to_addrs = ','.join(sorted({a.lower() for _, a in recipients if a}))
    return (msg['id'], msg.get('threadId'), int(msg.get('internalDate', 0)),
            int(msg.get('sizeEstimate', 0)), addr, name, addr.rpartition('@')[2],
            to_addrs, hdrs.get('subject', ''), int('list-unsubscribe' in hdrs),
            ','.join(msg.get('labelIds', [])))


def sync(gmail: Gmail, db: sqlite3.Connection, *, workers: int = 8,
         query: str = '', log=print) -> int:
    """Fetch metadata for every id matching `query` not yet in the table."""
    known = {r[0] for r in db.execute('SELECT id FROM messages')}
    todo = [i for i in gmail.iter_ids(query) if i not in known]
    log(f'{len(known)} already stored, {len(todo)} to fetch')
    fetch = lambda i: to_row(gmail.metadata(i, HEADERS))  # noqa: E731
    done = 0
    with ThreadPoolExecutor(workers) as pool:
        for start in range(0, len(todo), 500):
            rows = list(pool.map(fetch, todo[start:start + 500]))
            db.executemany(f'INSERT OR REPLACE INTO messages VALUES ({",".join("?" * 11)})', rows)
            db.commit()
            done += len(rows)
            log(f'  {done}/{len(todo)} (rate {gmail.rate:.0f} u/s)')
    return done


def senders(db: sqlite3.Connection, limit: int = 200, where: str = '1=1') -> list[tuple]:
    """Top senders: addr, domain, count, unread, first/last year, % with List-Unsubscribe."""
    return db.execute(f"""
        SELECT from_addr, from_domain, COUNT(*) n,
               SUM(labels LIKE '%UNREAD%') unread,
               strftime('%Y', MIN(internal_ms) / 1000, 'unixepoch'),
               strftime('%Y', MAX(internal_ms) / 1000, 'unixepoch'),
               ROUND(100.0 * AVG(has_unsub)), MAX(subject)
        FROM messages WHERE {where}
        GROUP BY from_addr ORDER BY n DESC LIMIT ?""", (limit,)).fetchall()
