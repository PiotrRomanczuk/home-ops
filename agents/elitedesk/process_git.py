"""process_git — git side of a BPMN save: pull, re-check, write, commit, push.

planner-sync has two threads touching one working clone (the 60 s vault sync
and the 2 s toggle drain), so every pull → write → commit → push sequence
holds `GIT_LOCK`. `apply_process_write` leaves the clone exactly as it found it
whenever it does not return 'applied': an Obsidian edit that landed during the
pull is never overwritten, a failed add/commit restores the file, a rejected
push drops our local commit (a diverged clone would stop planner-sync seeing
the vault at all).
"""
from __future__ import annotations

import functools
import hashlib
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

GIT_LOCK = threading.RLock()

RunGit = Callable[..., 'subprocess.CompletedProcess[str]']

_IDENTITY = ('-c', 'user.name=planner-sync', '-c', 'user.email=planner-sync@home-ops')


def locked(fn):
    """Run `fn` holding GIT_LOCK (pull → write → commit → push sequences)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with GIT_LOCK:
            return fn(*args, **kwargs)
    return wrapper


def _tail(r: 'subprocess.CompletedProcess[str]') -> str:
    return (r.stderr or r.stdout or '').strip()[-300:]


def _restore(run_git: RunGit, rel: str) -> None:
    run_git('reset', '-q', 'HEAD', '--', rel)
    run_git('checkout', '--', rel)


def _drop_local_commit(run_git: RunGit) -> None:
    # Our commit sits on top of the upstream we just pulled; go back to it.
    if run_git('reset', '--hard', '@{u}').returncode != 0:
        run_git('reset', '--hard', 'HEAD~1')
    run_git('pull', '--ff-only')


def apply_process_write(run_git: RunGit, bpmn_path: Path, rel: str, xml: str,
                        base_hash: str, msg: str) -> tuple[str, str | None]:
    """(status, reason) with status ∈ {'applied', 'conflict'}. Never leaves a
    modified file or an unpushed commit behind unless it returns 'applied'."""
    with GIT_LOCK:
        pull = run_git('pull', '--ff-only')
        if pull.returncode != 0:
            return 'conflict', f'pre-write pull failed: {_tail(pull)}'
        try:
            on_disk = bpmn_path.read_bytes()
        except OSError as e:
            return 'conflict', f'diagram unreadable after pull: {e}'
        if hashlib.sha256(on_disk).hexdigest() != base_hash:
            return 'conflict', 'diagram changed in the vault since it was opened — reload and redo the edit'
        data = xml.encode('utf-8')
        if on_disk == data:
            return 'applied', None
        bpmn_path.write_bytes(data)
        add = run_git('add', '--', rel)
        if add.returncode != 0:
            _restore(run_git, rel)
            return 'conflict', f'git add failed: {_tail(add)}'
        if run_git('diff', '--cached', '--quiet', '--', rel).returncode == 0:
            return 'applied', None  # git sees no change (line-ending normalisation)
        commit = run_git(*_IDENTITY, 'commit', '-m', msg)
        if commit.returncode != 0:
            _restore(run_git, rel)
            return 'conflict', f'git commit failed: {_tail(commit)}'
        push = run_git('push')
        if push.returncode != 0:
            _drop_local_commit(run_git)
            return 'conflict', f'push rejected — nothing written: {_tail(push)}'
        return 'applied', None
