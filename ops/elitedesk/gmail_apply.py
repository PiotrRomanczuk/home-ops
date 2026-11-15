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

from gmail_api import BATCH_LIMIT, Gmail


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


def modify_journaled(gmail: Gmail, journal: Path, op: str, label: str, label_id: str, ids: list[str]) -> int:
    """op 'add'/'remove' one label on `ids`, BATCH_LIMIT at a time; each chunk gets its journal line
    (flushed) right after it succeeds, so a failure half-way leaves every applied chunk undoable."""
    if not ids:
        return 0
    journal.parent.mkdir(parents=True, exist_ok=True)
    labels = {'add': [label_id]} if op == 'add' else {'remove': [label_id]}
    with journal.open('a') as j:
        for i in range(0, len(ids), BATCH_LIMIT):
            chunk = ids[i:i + BATCH_LIMIT]
            gmail.batch_modify(chunk, **labels)
            j.write(json.dumps({'ts': int(time.time()), 'op': op, 'label': label,
                                'label_id': label_id, 'ids': chunk}) + '\n')
            j.flush()
    return len(ids)


def apply_categories(gmail: Gmail, mapping: dict[str, list[str]], journal: Path,
                     log=print) -> int:
    """Add label L to every id in mapping[L]; returns number of messages labelled."""
    ids_by_label = ensure_labels(gmail, sorted(mapping), log)
    done = 0
    for name, ids in sorted(mapping.items(), key=lambda kv: -len(kv[1])):
        done += modify_journaled(gmail, journal, 'add', name, ids_by_label[name], ids)
        log(f'  {name}: {len(ids)}')
    return done


OPS = {'trash': (['TRASH'], []), 'archive': ([], ['INBOX']), 'read': ([], ['UNREAD'])}


def reconcile(gmail: Gmail, old: dict[str, list[str]], new: dict[str, list[str]], journal: Path,
              log=print) -> int:
    """Strip labels a message no longer belongs to (old mapping) and add its new ones."""
    old_of: dict[str, set[str]] = {}
    for name, ids in old.items():
        for i in ids:
            old_of.setdefault(i, set()).add(name)
    stale: dict[str, list[str]] = {}
    for name, ids in new.items():
        for i in ids:
            for prev in old_of.get(i, ()):  # a parent stays valid if still in new
                if i not in set(new.get(prev, ())):
                    stale.setdefault(prev, []).append(i)
    ids_by_label = ensure_labels(gmail, sorted(set(stale) | set(new)), log)
    for name, ids in stale.items():
        ids = sorted(set(ids))
        modify_journaled(gmail, journal, 'remove', name, ids_by_label[name], ids)
        log(f'  -{name}: {len(ids)}')
    return apply_categories(gmail, new, journal, log) + sum(len(v) for v in stale.values())


def move(gmail: Gmail, op: str, ids: list[str], restore_ids: set[str], journal: Path,
         note: str = '', log=print, *, protected: set[str] | None = None) -> int:
    """trash → add TRASH; archive → remove INBOX; read → remove UNREAD.

    restore_ids = messages that had INBOX (trash/archive) or UNREAD (read) before,
    so undo puts back exactly that state.

    Trash needs `protected` (gmail_labels.protected_ids): those ids are never trashed, whoever built
    the list; the count lands in the journal entry as skipped_protected. Archive/read are not filtered.
    """
    if op not in OPS:
        raise ValueError(op)
    if op == 'trash' and protected is None:
        raise ValueError('move(trash) requires protected= (see gmail_labels.protected_ids)')
    skipped = [i for i in ids if i in protected] if op == 'trash' else []
    if skipped:
        ids = [i for i in ids if i not in protected]
        log(f'  {op} {note}: SKIPPED {len(skipped)} protected ({", ".join(skipped[:20])}{" …" if len(skipped) > 20 else ""})')
    if not ids:
        return 0
    add, remove = OPS[op]
    gmail.batch_modify(ids, add=add, remove=remove)
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open('a') as j:
        j.write(json.dumps({'ts': int(time.time()), 'op': op, 'note': note, 'ids': ids,
                            'inbox_ids': sorted(restore_ids & set(ids)),
                            'skipped_protected': len(skipped)}) + '\n')
    log(f'  {op} {note}: {len(ids)}')
    return len(ids)


def undo(gmail: Gmail, journal: Path, log=print) -> int:
    """Reverse every entry in the journal (newest first)."""
    entries = [json.loads(line) for line in journal.read_text().splitlines() if line.strip()]
    undone = 0
    for e in reversed(entries):
        if e['op'] == 'add':
            gmail.batch_modify(e['ids'], remove=[e['label_id']])
        elif e['op'] == 'remove':
            gmail.batch_modify(e['ids'], add=[e['label_id']])
        elif e['op'] == 'trash':
            gmail.batch_modify(e['ids'], remove=['TRASH'])
        if e['op'] in ('trash', 'archive') and e['inbox_ids']:
            gmail.batch_modify(e['inbox_ids'], add=['INBOX'])
        elif e['op'] == 'read' and e['inbox_ids']:
            gmail.batch_modify(e['inbox_ids'], add=['UNREAD'])
        undone += len(e['ids'])
        log(f'  undone {e["op"]} {e.get("label") or e.get("note", "")}: {len(e["ids"])}')
    return undone
