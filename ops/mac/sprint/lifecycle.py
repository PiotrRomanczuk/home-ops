"""lifecycle.py — keeping the runner single and visibly alive.

- single_instance(): `flock` on STATE/runner.lock, held for the life of the process. A second runner (a manual
  start, a double bootstrap) or seed.py would otherwise run setup() and put the tasks that are running right
  now back in queue/, to run twice.
- log_error() / fail(): a thread that hits an exception writes it to STATE/logs/runner-errors.jsonl (traceback,
  task id) and carries on; the task that caused it goes to failed/ instead of staying in running/ as a zombie.
- dead(): the names of threads that are no longer alive, for main() to exit non-zero so launchd restarts the runner.
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import IO, Any

import sprint_tasks as q


def notify(text: str) -> None:  # macOS notification centre
    subprocess.run(['osascript', '-e', f'display notification "{text}" with title "Mac worker"'], check=False)


def single_instance(state: Path) -> IO[str] | None:
    """The held lock file, or None when another runner already holds it (keep the result referenced)."""
    state.mkdir(parents=True, exist_ok=True)
    f = (state / 'runner.lock').open('a+')
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    f.seek(0)
    f.truncate()
    f.write(str(os.getpid()))
    f.flush()
    return f


def log_error(state: Path, where: str, task_id: str | None = None, error: str | None = None) -> None:
    """Append the exception being handled (or `error`) to logs/runner-errors.jsonl."""
    row = {'ts': datetime.now().astimezone().isoformat(timespec='seconds'), 'where': where, 'task': task_id,
           'error': error or traceback.format_exc()}
    (state / 'logs').mkdir(parents=True, exist_ok=True)
    with (state / 'logs' / 'runner-errors.jsonl').open('a') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def fail(state: Path, where: str, task: dict[str, Any] | None) -> None:
    """Call from an `except`: log it and, if the task is still in running/, send it to failed/ with the reason."""
    log_error(state, where, task and task['id'])
    if task and task['path'].exists():
        task['failed_reason'] = f'runner exception in {where}, see logs/runner-errors.jsonl'
        q.finish(state, task, 'failed')


def dead(threads: list[threading.Thread]) -> list[str]:
    return [t.name for t in threads if not t.is_alive()]
