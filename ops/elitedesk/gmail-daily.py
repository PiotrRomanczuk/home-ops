#!/usr/bin/env python3
"""gmail-daily.py — the Gmail cleanup as a routine (timer on elitedesk).

Every run: (1) inventory new messages over IMAP into the local SQLite and
gmail.message, (2) classify every non-trashed message with the rules in
Postgres (gmail.rules_json), (3) add the category labels new/changed messages
are missing (labels only — never trash, never delete), (4) rewrite
gmail.message_state, (5) post one digest card. Journals go to the same
~/.local/state/home-ops/gmail/ as on the Mac, and into gmail.applied.
"""
from __future__ import annotations

import collections
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import gmail_apply  # noqa: E402
import gmail_auth  # noqa: E402
import gmail_classify  # noqa: E402
import gmail_db  # noqa: E402
import gmail_imap  # noqa: E402
import gmail_import  # noqa: E402
import gmail_inventory  # noqa: E402
from gmail_api import Gmail  # noqa: E402

ROUTINE = 'gmail-daily'


def expected_labels(db: sqlite3.Connection, cfg: dict, trash: set[str]) -> dict[str, set[str]]:
    db.row_factory = sqlite3.Row
    people = gmail_classify.correspondents(db, cfg['me'])
    out: dict[str, set[str]] = collections.defaultdict(set)
    for r in db.execute('SELECT * FROM messages'):
        if r['id'] in trash:
            continue
        label = gmail_classify.classify(r, cfg, people)[0]
        out[label].add(r['id'])
        child = gmail_classify.subcategory(label, r, cfg)
        if child:
            out[child].add(r['id'])
    return out


def reconcile_live(gmail: Gmail, expected: dict[str, set[str]], known: set[str], journal: Path, log=print) -> tuple[int, int]:
    """Add missing / remove stale category labels so Gmail matches `expected`. Returns (added, removed)."""
    ids_by_label = gmail_apply.ensure_labels(gmail, sorted(expected), log)
    added = removed = 0
    import json
    with journal.open('a') as j:
        for name, lid in sorted(ids_by_label.items()):
            live = {i for i in gmail.iter_ids(f'label:"{name}" -in:trash') if i in known}
            extra, missing = sorted(live - expected[name]), sorted(expected[name] - live)
            if extra:
                gmail.batch_modify(extra, remove=[lid])
                j.write(json.dumps({'ts': int(time.time()), 'op': 'remove', 'label': name, 'label_id': lid, 'ids': extra}) + '\n')
            if missing:
                gmail.batch_modify(missing, add=[lid])
                j.write(json.dumps({'ts': int(time.time()), 'op': 'add', 'label': name, 'label_id': lid, 'ids': missing}) + '\n')
            added, removed = added + len(missing), removed + len(extra)
    return added, removed


def main() -> int:
    log = print
    gmail = Gmail(gmail_auth.access_token)
    db = gmail_inventory.connect()
    before = db.execute('SELECT COUNT(*) FROM messages').fetchone()[0]
    email = gmail.call('GET', '/profile')['emailAddress']
    gmail_imap.sync(gmail_imap.connect(email, gmail_auth.access_token()), db, log=log)
    new_ids = [r[0] for r in db.execute('SELECT id FROM messages ORDER BY rowid DESC LIMIT ?',
                                        (db.execute('SELECT COUNT(*) FROM messages').fetchone()[0] - before,))]
    gmail_db.upsert_messages([gmail_db.message_row(r) for r in db.execute(
        f"SELECT * FROM messages WHERE id IN ({','.join('?' * len(new_ids))})", new_ids)] if new_ids else [])
    cfg = gmail_classify.load_rules(Path('db'))
    trash = set(gmail.iter_ids('in:trash'))
    expected = expected_labels(db, cfg, trash)
    known = {r[0] for r in db.execute('SELECT id FROM messages')}
    journal = gmail_inventory.STATE_DIR / f'journal-daily-{time.strftime("%Y%m%d-%H%M%S")}.jsonl'
    added, removed = reconcile_live(gmail, expected, known, journal, log)
    if journal.exists():
        gmail_db.insert_applied(gmail_db.journal_rows(journal))
    inbox, unread = set(gmail.iter_ids('in:inbox')), set(gmail.iter_ids('is:unread -in:trash'))
    gmail_db.replace_state(gmail_import.state_rows(db, cfg, trash, inbox, unread))
    review = len(expected.get(gmail_classify.FALLBACK, ()))
    headline = f'{len(new_ids)} nowych, {added} etykiet dodanych, {removed} zdjętych, INBOX {len(inbox)}, do przejrzenia {review}'
    log(headline)
    try:
        from agents.routine_report import Reporter
        Reporter.from_env(ROUTINE).card(headline, status='ok' if len(inbox) == 0 else 'warn',
                                        metric={'label': 'INBOX', 'value': len(inbox)})
    except Exception as e:  # the card is best-effort; the run itself succeeded
        log(f'card not posted: {e}')
    return 0


if __name__ == '__main__':
    os.environ.setdefault('GMAIL_RULES', 'db')
    sys.exit(main())
