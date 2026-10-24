"""gmail_apply.py — write category labels to Gmail, journaled and reversible.

Only ever ADDS user labels. No archiving, no read/unread changes, no trash.
Every batch is appended to a JSONL journal so `undo` can strip exactly the
labels this tool added.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from gmail_api import Gmail


def ensure_labels(gmail: Gmail, names: list[str], log=print) -> dict[str, str]:
    """name -> id for every name, creating missing ones (parents first, sidebar-visible)."""
    existing = {lab['name']: lab['id'] for lab in gmail.labels()}
    wanted: list[str] = []
    for name in names:
        parts = name.split('/')
        wanted += ['/'.join(parts[:i]) for i in range(1, len(parts) + 1)]
    for name in dict.fromkeys(wanted):  # ordered, unique; parents precede children
        if name not in existing:
            existing[name] = gmail.create_label(name)['id']
            log(f'  created label {name}')
    return {n: existing[n] for n in names}


def apply_categories(gmail: Gmail, mapping: dict[str, list[str]], journal: Path,
                     log=print) -> int:
    """Add label L to every id in mapping[L]; returns number of messages labelled."""
    ids_by_label = ensure_labels(gmail, sorted(mapping), log)
    journal.parent.mkdir(parents=True, exist_ok=True)
    done = 0
    with journal.open('a') as j:
        for name, ids in sorted(mapping.items(), key=lambda kv: -len(kv[1])):
            gmail.batch_modify(ids, add=[ids_by_label[name]])
            j.write(json.dumps({'ts': int(time.time()), 'op': 'add', 'label': name,
                                'label_id': ids_by_label[name], 'ids': ids}) + '\n')
            j.flush()
            done += len(ids)
            log(f'  {name}: {len(ids)}')
    return done


def undo(gmail: Gmail, journal: Path, log=print) -> int:
    """Reverse every 'add' entry in the journal (newest first)."""
    entries = [json.loads(line) for line in journal.read_text().splitlines() if line.strip()]
    undone = 0
    for e in reversed(entries):
        if e['op'] == 'add':
            gmail.batch_modify(e['ids'], remove=[e['label_id']])
            undone += len(e['ids'])
            log(f'  removed {e["label"]} from {len(e["ids"])}')
    return undone
