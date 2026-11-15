"""gmail_labels.py — which labels the routine owns, and which messages must never be trashed.

Pure functions over the inventory + compiled rules; no Gmail calls.
"""
from __future__ import annotations

import sqlite3

import gmail_classify
from gmail_classify import FALLBACK

# Categories gmail_classify.classify/subcategory can return without any rule row.
FIXED = ('Ludzie', 'Ludzie/Wysłane', 'Ludzie/Znajomi', 'Ludzie/Firmy', 'Inne/Do-siebie',
         'Społecznościowe', 'Promocje', 'Newslettery', 'Powiadomienia', FALLBACK)


def managed_labels(cfg: dict, expected: dict[str, set[str]]) -> list[str]:
    """Every label name the reconciler may touch: today's categories, all rule/subrule labels
    (so a category that lost all its messages is still cleaned up) and the built-in ones."""
    rule_labels = {r.label for r in cfg['rules']} | {r.label for _, r in cfg['subrules']}
    return sorted(set(expected) | rule_labels | set(FIXED))


def protected_ids(db: sqlite3.Connection, cfg: dict) -> set[str]:
    """Ids of messages that must never be trashed (starred, protected category, document-like subject).

    Reads the inventory's labels, so refresh it (IMAP sync) right before building a trash list.
    """
    db.row_factory = sqlite3.Row
    people = gmail_classify.correspondents(db, cfg['me'])
    return {r['id'] for r in db.execute('SELECT * FROM messages')
            if gmail_classify.is_protected(gmail_classify.classify(r, cfg, people)[0],
                                           r['subject'] or '', r['labels'] or '', cfg)}
