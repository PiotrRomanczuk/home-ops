"""gmail_report.py — markdown coverage report of the categorisation (dry-run, no Gmail calls)."""
from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict

from gmail_classify import classify, correspondents


def report(db: sqlite3.Connection, cfg: dict, top: int = 8) -> str:
    """Markdown coverage report: per label count, reasons, top senders."""
    db.row_factory = sqlite3.Row
    people = correspondents(db, cfg['me'])
    counts: Counter = Counter()
    reasons: dict[str, Counter] = defaultdict(Counter)
    senders: dict[str, Counter] = defaultdict(Counter)
    for row in db.execute('SELECT from_addr, subject, labels, to_addrs, has_unsub FROM messages'):
        label, why = classify(row, cfg, people)
        counts[label] += 1
        reasons[label][why] += 1
        senders[label][row['from_addr']] += 1
    total = sum(counts.values()) or 1
    lines = [f'# Kategoryzacja — {total} wiadomości', '',
             '| Kategoria | Maili | % | Skąd | Top nadawcy |', '|---|---:|---:|---|---|']
    for label, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        why = ', '.join(f'{k} {v}' for k, v in reasons[label].most_common())
        tops = ', '.join(f'{a} ({c})' for a, c in senders[label].most_common(top))
        lines.append(f'| {label} | {n} | {100 * n / total:.1f} | {why} | {tops} |')
    return '\n'.join(lines)
