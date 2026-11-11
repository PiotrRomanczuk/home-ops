#!/usr/bin/env python3
"""gmail_import.py — one-off backfill of schema `gmail` (migration 025) from the Mac-side state.

  python3 gmail_import.py messages            inventory.sqlite  -> gmail.message
  python3 gmail_import.py journals            journal-*.jsonl   -> gmail.applied
  python3 gmail_import.py rules [FILE]        gmail-rules.json  -> gmail.rule + gmail.config
  python3 gmail_import.py state               classify every message -> gmail.message_state
  python3 gmail_import.py all

Idempotent: messages upsert, applied rows are keyed by (journal, line, message),
rules and state are replaced wholesale. Needs the compose Postgres on this host
(or CONTAINER/DB env pointing at it).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gmail_classify  # noqa: E402
import gmail_db  # noqa: E402
import gmail_inventory  # noqa: E402

STATE = gmail_inventory.STATE_DIR


def import_messages(log=print) -> int:
    db = gmail_inventory.connect()
    rows = [gmail_db.message_row(r) for r in db.execute('SELECT * FROM messages')]
    n = 0
    for i in range(0, len(rows), 20000):
        n += gmail_db.upsert_messages(rows[i:i + 20000])
        log(f'  messages {n}/{len(rows)}')
    return n


def import_journals(log=print) -> int:
    n = 0
    for path in sorted(STATE.glob('journal-*.jsonl')):
        rows = gmail_db.journal_rows(path)
        for i in range(0, len(rows), 50000):
            gmail_db.insert_applied(rows[i:i + 50000])
        n += len(rows)
        log(f'  {path.name}: {len(rows)}')
    return n


def import_rules(path: Path = gmail_classify.RULES_PATH, log=print) -> int:
    n = gmail_db.import_rules(json.loads(path.read_text()))
    log(f'  rules: {n} rows from {path}')
    return n


def current_trash_ids() -> set[str]:
    """Message ids whose last trash/restore op in gmail.applied is a trash."""
    rows = gmail_db.psql_json(
        "SELECT DISTINCT ON (message_id) message_id, op FROM gmail.applied "
        "WHERE op IN ('trash', 'restore') AND message_id <> '' ORDER BY message_id, ts DESC")
    return {r['message_id'] for r in rows if r['op'] == 'trash'}


def state_rows(db, cfg: dict, trash: set[str], inbox: set[str] | None = None, unread: set[str] | None = None) -> list[tuple]:
    """gmail.message_state rows for every inventoried message (live INBOX/UNREAD sets optional)."""
    import sqlite3
    db.row_factory = sqlite3.Row
    people = gmail_classify.correspondents(db, cfg['me'])
    out = []
    for r in db.execute('SELECT * FROM messages'):
        label, why = gmail_classify.classify(r, cfg, people)
        labels = r['labels'] or ''
        out.append((r['id'], label, gmail_classify.subcategory(label, r, cfg), why, r['id'] in trash,
                    (r['id'] in inbox) if inbox is not None else 'INBOX' in labels,
                    (r['id'] in unread) if unread is not None else 'UNREAD' in labels,
                    gmail_classify.is_protected(label, r['subject'] or '', labels, cfg)))
    return out


def import_state(log=print) -> int:
    db = gmail_inventory.connect()
    cfg = gmail_classify.load_rules(Path('db'))
    n = gmail_db.replace_state(state_rows(db, cfg, current_trash_ids()))
    log(f'  state: {n} rows')
    return n


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument('what', choices=['messages', 'journals', 'rules', 'state', 'all'])
    p.add_argument('file', nargs='?', help='rules JSON (default: the private rules file)')
    a = p.parse_args(argv)
    steps = {'messages': import_messages, 'journals': import_journals,
             'rules': lambda: import_rules(Path(a.file) if a.file else gmail_classify.RULES_PATH),
             'state': import_state}
    for name in (steps if a.what == 'all' else [a.what]):
        print(name)
        steps[name]()


if __name__ == '__main__':
    main()
