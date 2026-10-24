"""gmail_apply.py — journaled, reversible label changes in Gmail.

`apply_categories` only ADDS user labels. `move` archives (drop INBOX) or
trashes (add TRASH; Gmail purges after 30 days) an explicit id list. Every
batch is appended to a JSONL journal so `undo` restores exactly what changed.
Never permanently deletes.
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


def move(gmail: Gmail, op: str, ids: list[str], inbox_ids: set[str], journal: Path,
         note: str = '', log=print) -> int:
    """op='trash' → add TRASH; op='archive' → remove INBOX. inbox_ids lets undo restore INBOX."""
    if op not in ('trash', 'archive'):
        raise ValueError(op)
    if op == 'trash':
        gmail.batch_modify(ids, add=['TRASH'])
    else:
        gmail.batch_modify(ids, remove=['INBOX'])
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open('a') as j:
        j.write(json.dumps({'ts': int(time.time()), 'op': op, 'note': note, 'ids': ids,
                            'inbox_ids': sorted(inbox_ids & set(ids))}) + '\n')
    log(f'  {op} {note}: {len(ids)}')
    return len(ids)


def undo(gmail: Gmail, journal: Path, log=print) -> int:
    """Reverse every entry in the journal (newest first)."""
    entries = [json.loads(line) for line in journal.read_text().splitlines() if line.strip()]
    undone = 0
    for e in reversed(entries):
        if e['op'] == 'add':
            gmail.batch_modify(e['ids'], remove=[e['label_id']])
        elif e['op'] == 'trash':
            gmail.batch_modify(e['ids'], remove=['TRASH'])
        if e['op'] in ('trash', 'archive') and e['inbox_ids']:
            gmail.batch_modify(e['inbox_ids'], add=['INBOX'])
        undone += len(e['ids'])
        log(f'  undone {e["op"]} {e.get("label") or e.get("note", "")}: {len(e["ids"])}')
    return undone
