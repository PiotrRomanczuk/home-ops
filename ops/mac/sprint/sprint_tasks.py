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
runner leaves it visible in running/ (setup() puts those back; one whose run had started, `pgid:`, counts as
interrupted, and its process group is stopped first if it outlived the runner — run_groups.stop_stale). A task whose `after` ended in failed/ — or
names no task for 24 h — goes to failed/ too instead of waiting forever. A file that is not a whole task
(header never closed, no prompt) or is younger than MIN_AGE is skipped, so a half-written file never runs.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import run_groups
from task_files import load, parse, write  # noqa: F401  (parse and write are part of this module's API)

DIRS = ('queue', 'running', 'done', 'failed', 'results', 'logs')
ESCALATE = {'haiku': 'sonnet', 'sonnet': 'opus', 'opus': 'fable'}  # local:* → sonnet
MAX_INTERRUPTS = 3
MIN_AGE = 5  # seconds a queue file rests before it may start: a planner may still be writing it
ORPHAN_AFTER = 24 * 3600  # an `after` naming no task anywhere is given this long to appear


def stronger(model: str) -> str:
    return 'sonnet' if model.startswith('local:') else ESCALATE.get(model, 'fable')


def is_local(task: dict[str, Any]) -> bool:
    return str(task.get('model') or '').startswith('local:')


def setup(state: Path) -> None:
    for name in DIRS:
        (state / name).mkdir(parents=True, exist_ok=True)
    for path in (state / 'running').glob('*.md'):  # left over from a crash, a SIGKILL or a lost thread
        task = parse(path)
        if not (task and task.get('pgid')):  # never started
            path.rename(state / 'queue' / path.name)
            continue
        run_groups.stop_stale(task)  # else the old run goes on next to the new one
        for key in run_groups.KEYS:
            task.pop(key, None)
        finish(state, task, 'interrupted')


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
    locks = {t.get('lock') for t in load(state / 'running') if t.get('lock')}
    tasks = load(state / 'queue', MIN_AGE)
    ok = [t for t in tasks if (not t.get('after') or t['after'] in done) and t.get('lock') not in locks and not waiting(t, now)]
    return sorted(ok, key=lambda t: (t['priority'], t['id']))


def drop_blocked(state: Path) -> None:
    """Fail queued tasks that could never become eligible: their `after` failed, or names no task in any
    folder for more than ORPHAN_AFTER (the reason goes into the file as `failed_reason`)."""
    failed = ids(state, 'failed')
    known = failed | ids(state, 'queue') | ids(state, 'running') | ids(state, 'done')
    for task in load(state / 'queue', MIN_AGE):
        after = task.get('after')
        if after in failed:
            reason = f'after: {after} ended in failed/'
        elif after and after not in known and time.time() - task['path'].stat().st_mtime > ORPHAN_AFTER:
            reason = f'after: {after} does not exist'
        else:
            continue
        task['failed_reason'] = reason
        finish(state, task, 'failed')


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
