"""gpu_pause.py — the pause/resume half of gpu_worker: the GPU borrow marker and SIGSTOP/SIGCONT of the shards."""
from __future__ import annotations

import os
import signal
from pathlib import Path
from typing import Any, Callable

import machine
import procs


def borrowed(gpu: Path) -> bool:
    """True while a local-LLM task of the runner holds the GPU (STATE/gpu/borrow holds its live pid)."""
    try:
        os.kill(int((gpu / 'borrow').read_text().strip()), 0)
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def hold_reason(s: dict[str, Any], gpu: Path, idle_min: float) -> str | None:
    """Why the shards should be paused right now (None = they may run)."""
    if not machine.away(s, idle_min):
        return 'Piotr przy Macu'
    if borrowed(gpu):
        return 'lokalny LLM używa GPU'
    if s['foreign']:
        return 'song2logic uruchomiony poza nadzorcą'
    return None if s['graphics'] else 'dark wake'


def pause(shards: dict[int, dict[str, Any]], on: bool, log: Callable[..., None]) -> None:
    for n, sh in shards.items():
        if sh['paused'] != on and procs.send(sh['proc'].pid, signal.SIGSTOP if on else signal.SIGCONT):
            sh['paused'] = on
            log('paused' if on else 'resumed', shard=n)
