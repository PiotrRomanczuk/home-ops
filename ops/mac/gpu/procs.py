"""procs.py — start, pause, resume and stop a GPU job's shard as one process group.

Each shard runs in its own session (start_new_session), so SIGSTOP/SIGCONT/SIGTERM reach its
children and grandchildren too (uv → python → yt-dlp → ffmpeg). The group is recorded in
pids/<job>.<shard>.json with the boot time and the leader's start time, so a supervisor that
crashed can stop its leftovers on the next start without ever touching a reused process id:
a group id cannot be handed out again while that group still has members.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import IO, Iterable


def boot_time() -> int:
    try:
        out = subprocess.run(['sysctl', '-n', 'kern.boottime'], capture_output=True, text=True, timeout=10).stdout
        m = re.search(r'sec = (\d+)', out)
        if m:
            return int(m.group(1))
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:  # Linux (CI)
        return int(next(line.split()[1] for line in Path('/proc/stat').read_text().splitlines() if line.startswith('btime')))
    except (OSError, StopIteration):
        return 0


def started(pid: int) -> str:
    try:
        return subprocess.run(['ps', '-o', 'lstart=', '-p', str(pid)], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ''


def start(argv: list[str], cwd: str, env: dict[str, str], pid_file: Path, log: IO[bytes]) -> subprocess.Popen:
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    pid_file.write_text(json.dumps({'pgid': proc.pid, 'boot': boot_time(), 'lstart': started(proc.pid)}))
    return proc


def send(pgid: int, sig: int) -> bool:
    try:
        os.killpg(pgid, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def alive(pgid: int) -> bool:
    return send(pgid, 0)


def stop_all(pgids: Iterable[int], procs: Iterable[subprocess.Popen] = (), grace_s: float = 30) -> None:
    """CONT (a stopped group only acts on TERM once it runs) + TERM, then KILL whatever is left."""
    pgids, procs = list(pgids), list(procs)
    for pgid in pgids:
        send(pgid, signal.SIGCONT)
        send(pgid, signal.SIGTERM)
    deadline = time.time() + grace_s
    while time.time() < deadline and any(alive(pgid) for pgid in pgids):
        for proc in procs:
            proc.poll()  # reap our own leaders as they exit
        time.sleep(0.5)
    for pgid in pgids:
        send(pgid, signal.SIGKILL)
    for proc in procs:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def cleanup_orphans(pid_dir: Path, grace_s: float = 30) -> list[int]:
    """Stop the groups a previous supervisor left behind; drop records that are stale or reused."""
    stopped, boot = [], boot_time()
    for path in pid_dir.glob('*.json'):
        try:
            rec = json.loads(path.read_text())
            pgid = int(rec['pgid'])
        except (ValueError, KeyError, TypeError):
            path.unlink()
            continue
        leader = started(pgid)
        reused = bool(leader) and leader != rec.get('lstart')
        if rec.get('boot') == boot and alive(pgid) and not reused:
            stop_all([pgid], grace_s=grace_s)
            stopped.append(pgid)
        path.unlink()
    return stopped
