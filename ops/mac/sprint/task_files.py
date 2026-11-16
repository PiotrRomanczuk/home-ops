"""task_files.py — reading and writing one task file (the format is in sprint_tasks.py)."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

FILE_RE = re.compile(r'---\n(?:(.*?)\n)?---[ \t]*(?:\n|\Z)(.*)', re.S)
INT_KEYS = (('priority', 50), ('max_minutes', 45), ('attempts', 0), ('interrupts', 0))


def parse(path: Path) -> dict[str, Any] | None:
    """The task in `path`; None when it is not a whole task: a `---` header that never closes (a planner that
    died or is still writing) or no prompt, or the file is gone. A file without a header is all prompt."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return None
    meta: dict[str, Any] = {}
    body = text
    if text.startswith('---\n'):
        m = FILE_RE.match(text)
        if not m:
            return None
        body = m.group(2)
        for line in (m.group(1) or '').splitlines():
            key, sep, value = line.partition(':')
            if sep:
                meta[key.strip()] = re.split(r'\s+#', value, maxsplit=1)[0].strip()
    if not body.strip():
        return None
    meta['id'] = meta.get('id') or path.stem
    for key, default in INT_KEYS:
        try:
            meta[key] = int(meta.get(key, default))
        except ValueError:
            meta[key] = default
    return {**meta, 'body': body.strip(), 'path': path}


def load(folder: Path, min_age: float = 0) -> list[dict[str, Any]]:
    """Every whole task in `folder` that has rested `min_age` seconds (a file may still be being written)."""
    out = []
    for path in folder.glob('*.md'):
        try:
            young = time.time() - path.stat().st_mtime < min_age
        except FileNotFoundError:
            continue
        task = None if young else parse(path)
        if task:
            out.append(task)
    return out


def write(path: Path, task: dict[str, Any]) -> None:
    head = '\n'.join(f'{k}: {v}' for k, v in task.items() if k not in ('body', 'path') and v not in (None, ''))
    path.write_text(f'---\n{head}\n---\n{task["body"]}\n')
