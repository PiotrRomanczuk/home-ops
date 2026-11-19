"""lifecycle.py — keeping the runner single and visibly alive.

- single_instance(): `flock` on STATE/runner.lock, held for the life of the process. A second runner (a manual
  start, a double bootstrap) or seed.py would otherwise run setup() and put the tasks that are running right
  now back in queue/, to run twice.
- log_error() / fail(): a thread that hits an exception writes it to STATE/logs/runner-errors.jsonl (traceback,
  task id) and carries on; the task that caused it goes to failed/ instead of staying in running/ as a zombie.
- dead(): the names of threads that are no longer alive, for main() to exit non-zero so launchd restarts the runner.
- shutdown() / on_sigterm(): the runs live in their own process groups (run_groups.py), outside the launchd job's
  group, so stopping the job (bootout, `kickstart -k`, a reinstall) must end them here: TERM→KILL every run, no
  new claims (`halted`, in memory: a STOP file would outlive the restart), then wait for the workers to put
  their tasks back as `interrupted`. Within the plist's ExitTimeOut (60 s): grace 10 s + JOIN_S 30 s.
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import IO, Any, Callable

import run_groups
import sprint_tasks as q

JOIN_S = 30
halted = threading.Event()  # set by shutdown(): workers stop claiming and stop sleeping


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


def watch(state: Path, threads: list[threading.Thread], stopping: Callable[[], bool]) -> None:
    """Return once `stopping()`; exit 1 when a thread died (launchd, KeepAlive SuccessfulExit=false, starts a fresh
    runner) — after shutdown(), else the runs would outlive this process. threads[-1] is housekeeping."""
    while not stopping():
        time.sleep(15)
        gone = dead(threads)
        if gone and not stopping():
            log_error(state, 'main', error=f'thread(s) died: {", ".join(gone)}')
            notify(f'Mac worker: padł wątek {", ".join(gone)}, restart.')
            shutdown(threads[:-1])
            sys.exit(1)


def shutdown(workers: list[threading.Thread], grace: float = run_groups.GRACE_S) -> None:
    halted.set()
    run_groups.stop_all(grace)
    deadline = time.time() + JOIN_S
    for t in workers:
        t.join(timeout=max(0.0, deadline - time.time()))


def on_sigterm(workers: list[threading.Thread]) -> None:
    """SIGTERM (launchd stopping the job): shutdown(), then exit 0 so KeepAlive does not count it as a crash."""
    def handler(signum: int, frame: Any) -> None:
        shutdown(workers)
        sys.exit(0)
    signal.signal(signal.SIGTERM, handler)
