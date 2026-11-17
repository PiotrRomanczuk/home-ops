"""run_groups.py — the process groups of the runs in progress (claude_run.run starts each in its own session).

Its own group lets the hard time limit kill everything a run started, but it also takes the run out of the
launchd job's group, so the job's stop (bootout, `kickstart -k`, a reinstall) no longer reaches `claude`. So:
- LIVE holds every running group; stop_all() (lifecycle.shutdown: SIGTERM, or a dead thread before exit 1) ends
  them all, TERM then KILL, and sets CLOSED, so no run starts afterwards. Workers see rc -15 → `interrupted`.
- track() writes the group into the task file in running/ (pgid, boot time, leader's start time, as procs.py does
  for GPU shards). After a SIGKILL or a crash, sprint_tasks.setup() calls stop_stale() before it requeues the task,
  so the task never runs twice side by side; a reused process id (other boot, other leader) is never signalled.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from task_files import write

sys.path.append(str(Path(__file__).resolve().parent.parent / 'gpu'))  # repo layout; installed copies sit side by side
import procs  # noqa: E402

GRACE_S = 10  # SIGTERM → SIGKILL
KEYS = ('pgid', 'pgid_boot', 'pgid_start')
LIVE: dict[int, subprocess.Popen[str]] = {}  # pgid → its `claude`, while it runs
LIVE_LOCK = threading.Lock()
CLOSED = threading.Event()


def stop_group(p: subprocess.Popen[str], grace: float) -> tuple[str, str]:
    """SIGTERM the run's process group, SIGKILL after `grace` seconds; → (stdout, stderr) it had written.
    Only the group: after a KILL, tool shells that `claude` started outside it may survive (on TERM claude ends them)."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(p.pid, sig)
        except ProcessLookupError:
            break
        try:
            return p.communicate(timeout=grace)
        except subprocess.TimeoutExpired:
            continue
    return p.communicate()


def stop_all(grace: float = GRACE_S) -> None:
    """End every live run (TERM to each group, KILL after `grace`) and refuse new ones; the runs return rc -15/-9."""
    with LIVE_LOCK:
        CLOSED.set()
        pgids = list(LIVE)
    procs.stop_all(pgids, grace_s=grace)  # the workers' communicate() reaps the leaders


def stop_stale(task: dict[str, Any], grace: float = GRACE_S) -> bool:
    """Stop the group a task file in running/ names, if it is still that run's group (same boot, same leader)."""
    try:
        pgid = int(task.get('pgid') or 0)
    except ValueError:
        return False
    leader = procs.started(pgid) if pgid else ''
    if not pgid or str(task.get('pgid_boot')) != str(procs.boot_time()) or (leader and leader != task.get('pgid_start')):
        return False
    if not procs.alive(pgid):
        return False
    procs.stop_all([pgid], grace_s=grace)
    return True


def start(argv: list[str], task: dict[str, Any], **kw: Any) -> subprocess.Popen[str] | None:
    """Popen in a new session, registered in LIVE; None once stop_all() ran. The task file in running/ gets the
    group (for stop_stale after a crash)."""
    with LIVE_LOCK:  # so stop_all() either sees this run or this run never starts
        if CLOSED.is_set():
            return None
        p = subprocess.Popen(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, **kw)
        LIVE[p.pid] = p
    if task.get('path'):
        task.update(pgid=p.pid, pgid_boot=procs.boot_time(), pgid_start=procs.started(p.pid))
        write(task['path'], task)
    return p


def untrack(p: subprocess.Popen[str] | None, task: dict[str, Any]) -> None:
    if p is not None:
        with LIVE_LOCK:
            LIVE.pop(p.pid, None)
    for key in KEYS:
        task.pop(key, None)
