"""gmail_llm_digest.py — per-sender digests of the inventory: who Claude is asked about, and what the rules already file.

Pure functions over the SQLite inventory (no Gmail, no Postgres, no model).
"""
from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict

import gmail_classify

WEAK = {'none', 'tab', 'unsub'}
MAX_SUBJECTS = 20


def _tab(labels: str) -> str:
    for key, name in (('PROMOTIONS', 'promotions'), ('SOCIAL', 'social'), ('UPDATES', 'updates'), ('FORUMS', 'forums')):
        if f'CATEGORY_{key}' in (labels or ''):
            return name
    return 'primary'


def _digest(sender: str, rows: list) -> dict:
    return {'sender': sender, 'name': rows[0]['from_name'] or '', 'domain': rows[0]['from_domain'] or '',
            'n': len(rows), 'unsub_share': round(sum(bool(r['has_unsub']) for r in rows) / len(rows), 2),
            'tab': Counter(_tab(r['labels']) for r in rows).most_common(1)[0][0],
            'subjects': [r['subject'] or '' for r in rows[:MAX_SUBJECTS]]}


def sender_digests(db: sqlite3.Connection, cfg: dict, trash: set[str], skip: set[str]) -> tuple[list[dict], list[dict]]:
    """(weak, labelled) sender digests in one pass over the inventory.

    weak     — every message of the sender has a weak reason (no rule): what Claude is asked about.
               `domain_mixed` / `domain_people`: other senders of the same domain are NOT weak (a person
               the owner writes to, or a sender an existing rule files) — an '@domain' rule would swallow them.
    labelled — every message filed by rules under one label: the example senders shown per category
    """
    db.row_factory = sqlite3.Row
    people = gmail_classify.correspondents(db, cfg['me'])
    groups: dict[str, list] = defaultdict(list)
    for r in db.execute('SELECT * FROM messages ORDER BY internal_ms DESC'):
        if r['id'] not in trash and r['from_addr'] and r['from_addr'] not in cfg['me']:
            groups[r['from_addr']].append(r)
    weak, labelled = [], []
    strong: dict[str, set[str]] = defaultdict(set)  # domain -> senders with a non-weak verdict or a correspondent
    for sender, rows in groups.items():
        verdicts = {gmail_classify.classify(r, cfg, people) for r in rows}
        if sender in people or any(reason not in WEAK for _, reason in verdicts):
            strong[sender.rpartition('@')[2]].add(sender)
        if all(reason in WEAK for _, reason in verdicts) and sender not in skip:
            weak.append(_digest(sender, rows))
        elif len(verdicts) == 1 and next(iter(verdicts))[1] == 'rule':
            labelled.append({**_digest(sender, rows), 'label': next(iter(verdicts))[0]})
    for d in weak:
        others = strong.get(d['sender'].rpartition('@')[2], set()) - {d['sender']}
        d['domain_mixed'], d['domain_people'] = bool(others), len(others)
    return sorted(weak, key=lambda s: (-s['n'], s['sender'])), labelled
