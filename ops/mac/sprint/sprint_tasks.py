"""sprint_tasks.py — the Mac worker's task queue: one markdown file per task.

    ---
    id: vault-lesson-notes
    project: lesson-notes
    cwd: ~/Obsidian/MainCV-Planner
    model: sonnet            # haiku | sonnet | opus | local:<ollama model> (fable only after Opus failed)
    effort: medium
    kind: vault              # free text, used in the report
    priority: 10             # lower runs first
    max_minutes: 40
    lock: vault              # at most one running task per lock (optional)
    after: vault-pilot-review  # eligible once that id is in done/ (optional)
    attempts: 0
    not_before: 2026-11-16T04:50:00+01:00  # set by the runner after a limit or an interrupted run
    resume: <session id>     # set by the runner after a limit: the next run continues that session
    ---
    <prompt for the worker>

A task moves queue/ → running/ → done/ | failed/ by rename, so a crashed
runner leaves it visible in running/ (start() puts those back). A task whose
`after` ended in failed/ goes to failed/ too instead of waiting forever.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

DIRS = ('queue', 'running', 'done', 'failed', 'results', 'logs')
ESCALATE = {'haiku': 'sonnet', 'sonnet': 'opus', 'opus': 'fable'}  # local:* → sonnet
MAX_INTERRUPTS = 3


def stronger(model: str) -> str:
    return 'sonnet' if model.startswith('local:') else ESCALATE.get(model, 'fable')


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
    for key, default in (('priority', 50), ('max_minutes', 45), ('attempts', 0), ('interrupts', 0)):
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


def waiting(task: dict[str, Any], now: datetime) -> bool:
    """True while the task's `not_before` (ISO 8601; no offset = local time) is still ahead; a bad value is ignored."""
    try:
        at = datetime.fromisoformat(str(task.get('not_before') or ''))
    except ValueError:
        return False
    return (at if at.tzinfo else at.astimezone()) > now


def eligible(state: Path, now: datetime | None = None) -> list[dict[str, Any]]:
    """Queued tasks past their `not_before`, whose `after` is done and whose `lock` is free, best first."""
    now = now or datetime.now(timezone.utc)
    done = ids(state, 'done')
    locks = {t.get('lock') for t in map(parse, (state / 'running').glob('*.md')) if t.get('lock')}
    tasks = [parse(p) for p in (state / 'queue').glob('*.md')]
    ok = [t for t in tasks if (not t.get('after') or t['after'] in done) and t.get('lock') not in locks and not waiting(t, now)]
    return sorted(ok, key=lambda t: (t['priority'], t['id']))


def drop_blocked(state: Path) -> None:
    """Fail queued tasks whose `after` task failed — they could never become eligible."""
    failed = ids(state, 'failed')
    for path in (state / 'queue').glob('*.md'):
        if parse(path).get('after') in failed:
            path.rename(state / 'failed' / path.name)


def claim(state: Path, accept: Callable[[dict[str, Any]], bool] | None = None) -> dict[str, Any] | None:
    """Move the best eligible task that `accept` lets start now to running/ (call under the runner's lock)."""
    drop_blocked(state)
    for task in eligible(state):
        if accept is not None and not accept(task):
            continue
        target = state / 'running' / task['path'].name
        try:
            task['path'].rename(target)
        except FileNotFoundError:
            continue
        task['path'] = target
        return task
    return None


def finish(state: Path, task: dict[str, Any], outcome: str, escalate: bool = True) -> None:
    """outcome (outcomes.py): done | failed | limit, requeue (back to queue/, nothing counted) |
    interrupted (counted in `interrupts`, the third fails) | retry (the second fails; else a stronger model
    unless `escalate` is False)."""
    if outcome == 'retry':
        task['attempts'] += 1
        if task['attempts'] >= 2:
            outcome = 'failed'
        elif escalate:
            task['model'] = stronger(str(task.get('model')))
    elif outcome == 'interrupted':
        task['interrupts'] = int(task.get('interrupts') or 0) + 1
        if task['interrupts'] >= MAX_INTERRUPTS:
            outcome = 'failed'
    where = {'done': 'done', 'failed': 'failed'}.get(outcome, 'queue')
    write(state / where / task['path'].name, task)
    task['path'].unlink(missing_ok=True)
