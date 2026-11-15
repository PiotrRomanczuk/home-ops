#!/usr/bin/env python3
"""gmail-daily.py — the Gmail cleanup as a routine (timer on elitedesk).

Every run: (1) mirror All Mail over IMAP into the local SQLite and upsert every SQLite row
into gmail.message, (2) work out which messages are still in the mailbox (All Mail ∪ Trash —
anything else was deleted and has no state), (3) classify those with the rules in Postgres
(gmail.rules_json), (4) add/remove the category labels so Gmail matches (labels only — never
trash, never delete; each chunk is journaled), (5) rewrite gmail.message_state, (6) post one
digest card. The model steps (Claude proposals, "Dziś" answers, archiving; GMAIL_LLM=0 switches them off)
are fenced: their failure never stops the run. Journals go to the same ~/.local/state/home-ops/gmail/ as
on the Mac, and into gmail.applied.
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
import gmail_labels  # noqa: E402
import gmail_llm_daily  # noqa: E402
import gmail_llm_steps  # noqa: E402
from gmail_api import Gmail  # noqa: E402

ROUTINE = 'gmail-daily'
LLM = os.environ.get('GMAIL_LLM', '1') != '0'  # GMAIL_LLM=0 switches the model steps off


def expected_labels(db: sqlite3.Connection, cfg: dict, alive: set[str], trash: set[str]) -> dict[str, set[str]]:
    """label -> ids that should carry it: alive, not trashed (parent labels included for children)."""
    db.row_factory = sqlite3.Row
    people = gmail_classify.correspondents(db, cfg['me'])
    out: dict[str, set[str]] = collections.defaultdict(set)
    for r in db.execute('SELECT * FROM messages'):
        if r['id'] in trash or r['id'] not in alive:
            continue
        label = gmail_classify.classify(r, cfg, people)[0]
        out[label].add(r['id'])
        child = gmail_classify.subcategory(label, r, cfg)
        if child:
            out[child].add(r['id'])
    return out


def reconcile_live(gmail: Gmail, expected: dict[str, set[str]], known: set[str], journal: Path, log=print,
                   names: list[str] | None = None) -> tuple[int, int]:
    """Add missing / remove stale category labels so Gmail matches `expected`. Returns (added, removed).

    `names` = every label the routine manages (default: those in `expected`). A label is created only
    when it has messages to carry; one with none is still cleaned if it already exists. Current members
    are read by exact label id, not by a `label:"…"` search.
    """
    names = sorted(set(names or ()) | set(expected))
    existing = {lab['name']: lab['id'] for lab in gmail.labels()}
    existing.update(gmail_apply.ensure_labels(gmail, [n for n in names if expected.get(n) and n not in existing], log))
    added = removed = 0
    for name in names:
        if name not in existing:
            continue
        lid, want = existing[name], expected.get(name, set())
        live = {i for i in gmail.iter_ids(label_ids=[lid]) if i in known}
        removed += gmail_apply.modify_journaled(gmail, journal, 'remove', name, lid, sorted(live - want))
        added += gmail_apply.modify_journaled(gmail, journal, 'add', name, lid, sorted(want - live))
    return added, removed


def daily(gmail: Gmail, db: sqlite3.Connection, sync, journal: Path, log=print, reporter=None,
          llm: bool = False) -> dict:
    """One run without the card. `sync(db, log)` mirrors All Mail and returns (rows, present REST ids).

    `llm`: answered "Dziś" questions become rules before classifying, and proposals / archiving follow the
    reconcile. Both are fenced (`gmail_llm_steps.fenced`), so applied-journal, message_state and the card always happen.
    """
    ids_before = {r[0] for r in db.execute('SELECT id FROM messages')}
    _, present = sync(db, log)
    all_ids = {r[0] for r in db.execute('SELECT id FROM messages')}
    new_ids = all_ids - ids_before  # headline only — nothing downstream depends on it
    if ids_before and not present:
        raise RuntimeError('IMAP returned an empty All Mail — refusing to treat the whole mailbox as deleted')
    gmail_import.import_messages(log, db)  # every row, so message_state's FK can never dangle
    if llm and reporter:
        gmail_llm_steps.fenced('consume answers', lambda: gmail_llm_daily.consume(reporter, log), 0, log)
    cfg = gmail_classify.load_rules(Path('db'))
    trash = set(gmail.iter_ids('in:trash'))
    alive = present | trash
    expected = expected_labels(db, cfg, alive, trash)
    known = all_ids & alive
    added, removed = reconcile_live(gmail, expected, known, journal, log, gmail_labels.managed_labels(cfg, expected))
    proposed, archived = gmail_llm_steps.fenced(
        'llm steps', lambda: gmail_llm_steps.llm_steps(gmail, db, cfg, trash, reporter, journal, log), (0, 0), log
    ) if llm else (0, 0)
    if journal.exists():
        gmail_db.insert_applied(gmail_db.journal_rows(journal))
    inbox, unread = set(gmail.iter_ids('in:inbox')), set(gmail.iter_ids('is:unread -in:trash'))
    gmail_db.replace_state(gmail_import.state_rows(db, cfg, trash, inbox, unread, alive))
    return {'new': len(new_ids), 'added': added, 'removed': removed, 'inbox': len(inbox),
            'review': len(expected.get(gmail_classify.FALLBACK, ())), 'gone': len(all_ids - alive),
            'proposed': proposed, 'archived': archived}


def _reporter(log=print):
    try:
        from agents.routine_report import Reporter
        return Reporter.from_env(ROUTINE)
    except Exception as e:  # no ingest env → run without "Dziś" (card, questions, answers)
        log(f'no reporter: {e}')
        return None


def main() -> int:
    log = print
    gmail = Gmail(gmail_auth.access_token)
    db = gmail_inventory.connect()
    imap = gmail_imap.connect(gmail.call('GET', '/profile')['emailAddress'], gmail_auth.access_token())
    journal = gmail_inventory.STATE_DIR / f'journal-daily-{time.strftime("%Y%m%d-%H%M%S")}.jsonl'
    reporter = _reporter(log)
    try:
        r = daily(gmail, db, lambda d, lg: gmail_imap.sync(imap, d, log=lg), journal, log, reporter, LLM)
    finally:
        gmail_imap.close(imap)
    headline = (f'{r["new"]} nowych, {r["added"]} etykiet dodanych, {r["removed"]} zdjętych, '
                f'INBOX {r["inbox"]}, do przejrzenia {r["review"]}, propozycji reguł {r["proposed"]}, '
                f'zarchiwizowanych {r["archived"]}')
    log(headline + (f', zniknęło ze skrzynki {r["gone"]}' if r['gone'] else ''))
    try:
        if reporter:
            reporter.card(headline, status='ok' if r['inbox'] == 0 else 'warn', metric={'label': 'INBOX', 'value': r['inbox']})
    except Exception as e:  # the card is best-effort; the run itself succeeded
        log(f'card not posted: {e}')
    return 0


if __name__ == '__main__':
    os.environ.setdefault('GMAIL_RULES', 'db')
    sys.exit(main())
