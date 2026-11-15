"""sprint_tasks.py — the sprint's task queue: one markdown file per task.

    ---
    id: vault-lesson-notes
    project: lesson-notes
    cwd: ~/Obsidian/MainCV-Planner
    model: sonnet            # haiku | sonnet | opus (fable only by escalation after Opus failed)
    effort: medium
    kind: vault              # free text, used in the report
    priority: 10             # lower runs first
    max_minutes: 40
    lock: vault              # at most one running task per lock (optional)
    after: vault-pilot-review  # eligible once that id is in done/ (optional)
    attempts: 0
    ---
    <prompt for the worker>

A task moves queue/ → running/ → done/ | failed/ by rename, so a crashed
runner leaves it visible in running/ (start() puts those back).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

DIRS = ('queue', 'running', 'done', 'failed', 'results', 'logs')
ESCALATE = {'haiku': 'sonnet', 'sonnet': 'opus', 'opus': 'fable'}


def parse(path: Path) -> dict[str, Any]:
    text = path.read_text()
    meta: dict[str, Any] = {}
    body = text
    if text.startswith('---\n'):
        head, _, body = text[4:].partition('\n---\n')
        for line in head.splitlines():
            key, sep, value = line.partition(':')
            if sep:
                meta[key.strip()] = value.split('  #')[0].strip()
    meta['id'] = meta.get('id') or path.stem
    for key, default in (('priority', 50), ('max_minutes', 45), ('attempts', 0)):
        try:
            meta[key] = int(meta.get(key, default))
        except ValueError:
            meta[key] = default
    return {**meta, 'body': body.strip(), 'path': path}


def write(path: Path, task: dict[str, Any]) -> None:
    head = '\n'.join(f'{k}: {v}' for k, v in task.items() if k not in ('body', 'path') and v not in (None, ''))
    path.write_text(f'---\n{head}\n---\n{task["body"]}\n')


def setup(state: Path) -> None:
    for name in DIRS:
        (state / name).mkdir(parents=True, exist_ok=True)
    for path in (state / 'running').glob('*.md'):  # left over from a crash
        path.rename(state / 'queue' / path.name)


def ids(state: Path, where: str) -> set[str]:
    return {p.stem for p in (state / where).glob('*.md')}


def eligible(state: Path) -> list[dict[str, Any]]:
    """Queued tasks whose `after` is done and whose `lock` is free, best first."""
    done = ids(state, 'done')
    locks = {t.get('lock') for t in map(parse, (state / 'running').glob('*.md')) if t.get('lock')}
    tasks = [parse(p) for p in (state / 'queue').glob('*.md')]
    ok = [t for t in tasks if (not t.get('after') or t['after'] in done) and t.get('lock') not in locks]
    return sorted(ok, key=lambda t: (t['priority'], t['id']))


def claim(state: Path) -> dict[str, Any] | None:
    """Move the best eligible task to running/ (call under the runner's lock)."""
    for task in eligible(state):
        target = state / 'running' / task['path'].name
        try:
            task['path'].rename(target)
        except FileNotFoundError:
            continue
        task['path'] = target
        return task
    return None


def finish(state: Path, task: dict[str, Any], outcome: str) -> None:
    """outcome: done | failed | requeue (limit hit) | retry (failed once → stronger model)."""
    if outcome == 'retry':
        task['attempts'] += 1
        if task['attempts'] >= 2:
            outcome = 'failed'
        else:
            task['model'] = ESCALATE.get(str(task.get('model')), 'fable')
    where = {'done': 'done', 'failed': 'failed'}.get(outcome, 'queue')
    write(state / where / task['path'].name, task)
    task['path'].unlink(missing_ok=True)
