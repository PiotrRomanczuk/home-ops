"""task_ticks — which vault tasks got ticked [x] (or added) since planner-sync
last looked, for the Postęp tab (project_signals tasks_done / tasks_added).

A task is keyed by its text without the leading ISO date and markdown marks,
first KEY_LEN characters, lowercased — so moving it between Now/Next/Later or
appending "→ done in PR #70" when ticking it still matches. A project seen
for the first time is a baseline: nothing counts until the next change.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_LINE = re.compile(r'^\s*[-*]\s+\[([ xX])\]\s+(.+?)\s*$')
_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}\s+')
_MARKS = re.compile(r'[*_`~\[\]]')
KEY_LEN = 60
SECTIONS = ('now_md', 'next_md', 'later_md')


def task_key(text: str) -> str:
    t = _MARKS.sub('', _DATE.sub('', text.strip()))
    return re.sub(r'\s+', ' ', t).strip().lower()[:KEY_LEN]


def tasks_in(md: str | None) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for line in (md or '').splitlines():
        m = _LINE.match(line)
        if m:
            key = task_key(m.group(2))
            out[key] = out.get(key, False) or m.group(1).lower() == 'x'
    return out


_HEADER = re.compile(r'^##\s+(.+?)\s*$', re.MULTILINE)
_PROJECT = re.compile(r'^project:\s*["\']?([^"\'\n]+?)["\']?\s*$', re.MULTILINE)
_CANON = ('Now', 'Next', 'Later', 'Pain points', 'Notes')


def note_tasks(text: str) -> dict[str, bool]:
    """A whole vault note → its Now/Next/Later tasks, split the way
    planner-sync's _split_sections does (first canonical header wins)."""
    heads = []
    for m in _HEADER.finditer(text):
        name = m.group(1).strip()
        canon = next((c for c in _CANON if name == c or name.startswith(c + ' ')), None)
        if canon:
            heads.append((m.end(), m.start(), canon))
    tasks: dict[str, bool] = {}
    seen: set[str] = set()
    for i, (end, _, name) in enumerate(heads):
        if name in seen:
            continue
        seen.add(name)
        if name in ('Now', 'Next', 'Later'):
            stop = heads[i + 1][1] if i + 1 < len(heads) else len(text)
            for key, done in tasks_in(text[end:stop]).items():
                tasks[key] = tasks.get(key, False) or done
    return tasks


def note_slug(text: str, stem: str) -> str:
    """Same rule as planner-sync: frontmatter `project:`, else the file name."""
    fm = text.split('\n---', 1)[0] if text.startswith('---') else ''
    m = _PROJECT.search(fm)
    return m.group(1).strip() if m else stem


def snapshot(records: list[dict[str, Any]]) -> dict[str, dict[str, bool]]:
    snap: dict[str, dict[str, bool]] = {}
    for rec in records:
        tasks: dict[str, bool] = {}
        for section in SECTIONS:
            for key, done in tasks_in(rec.get(section)).items():
                tasks[key] = tasks.get(key, False) or done
        snap[rec['slug']] = tasks
    return snap


def diff(prev: dict[str, dict[str, bool]], cur: dict[str, dict[str, bool]]) -> dict[str, tuple[int, int]]:
    """slug → (newly done, newly added open) between two snapshots."""
    out: dict[str, tuple[int, int]] = {}
    for slug, tasks in cur.items():
        before = prev.get(slug)
        if before is None:
            continue
        done = sum(1 for k, d in tasks.items() if d and not before.get(k, False))
        added = sum(1 for k, d in tasks.items() if not d and k not in before)
        if done or added:
            out[slug] = (done, added)
    return out


def rows_for(changes: dict[str, tuple[int, int]], day: str) -> list[dict[str, Any]]:
    rows = []
    for slug, (done, added) in sorted(changes.items()):
        rows += [{'project_slug': slug, 'day': day, 'signal': s, 'n': n}
                 for s, n in (('tasks_done', done), ('tasks_added', added)) if n]
    return rows


class TickTracker:
    """Keeps the last snapshot on disk; commit() only after the rows landed,
    so a failed POST is retried on the next tick instead of being lost."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self.prev: dict[str, dict[str, bool]] = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.prev = {}

    def pending(self, records: list[dict[str, Any]], day: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, bool]]]:
        snap = snapshot(records)
        return rows_for(diff(self.prev, snap), day), snap

    def commit(self, snap: dict[str, dict[str, bool]]) -> None:
        self.prev = snap
        self.path.write_text(json.dumps(snap, ensure_ascii=False), encoding='utf-8')
