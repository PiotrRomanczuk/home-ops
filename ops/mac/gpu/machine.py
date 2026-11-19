"""machine.py — what the Mac is doing right now, read from stock macOS tools (no sudo).

away():      Piotr is not at the Mac: no keyboard/mouse input for `idle_min` minutes, no app keeping
             the display awake (video call, online lesson, a film) and Logic not running.
can_start(): on AC power, display stack up (not a dark wake), thermalState 0, memory pressure normal.
must_stop(): battery, thermalState >= 2 (serious) or memory pressure >= 2 (warn) — GPU work has to go.

`pmset -g therm` and `memory_pressure -Q` say nothing useful on Apple silicon, hence NSProcessInfo
and kern.memorystatus_vm_pressure_level. An unreadable value counts as unsafe (no start, stop).
Parsers are separate from the probes so tests can feed recorded outputs.
"""
from __future__ import annotations

import re
import subprocess
from typing import Any, Iterable

THERMAL_JS = 'ObjC.import("Foundation"); $.NSProcessInfo.processInfo.thermalState'
SONG2LOGIC_RE = re.compile(r'song2logic\s+(scan|study)\s')  # not `scan-ui`


def _out(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ''


def parse_idle(ioreg: str) -> float | None:
    """Seconds since the last keyboard/mouse input (HIDIdleTime is in nanoseconds)."""
    m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', ioreg)
    return int(m.group(1)) / 1e9 if m else None


def parse_on_ac(batt: str) -> bool:
    return "'AC Power'" in (batt.splitlines() or [''])[0]


def parse_display_held(assertions: str) -> bool:
    """The summary line `PreventUserIdleDisplaySleep 1` = some app keeps the display on."""
    m = re.search(r'^\s*PreventUserIdleDisplaySleep\s+(\d+)\s*$', assertions, re.M)
    return bool(m and int(m.group(1)))


def parse_graphics(systemstate: str) -> bool:
    m = re.search(r'Current System Capabilities are:(.*)', systemstate)
    return bool(m and 'Graphics' in m.group(1).split())


def parse_int(text: str, default: int) -> int:
    try:
        return int(text.strip())
    except ValueError:
        return default


def foreign_song2logic(ps: str, own_pgids: Iterable[int]) -> bool:
    """A song2logic scan/study running outside our process groups (e.g. started from scan-ui)."""
    own = set(own_pgids)
    for line in ps.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[1].isdigit() and int(parts[1]) not in own and SONG2LOGIC_RE.search(parts[2] + ' '):
            return True
    return False


def snapshot(own_pgids: Iterable[int] = ()) -> dict[str, Any]:
    logic = _out(['pgrep', '-x', 'Logic Pro']) + _out(['pgrep', '-x', 'Logic Pro X'])
    return {
        'idle_s': parse_idle(_out(['ioreg', '-c', 'IOHIDSystem'])),
        'on_ac': parse_on_ac(_out(['pmset', '-g', 'batt'])),
        'display_held': parse_display_held(_out(['pmset', '-g', 'assertions'])),
        'graphics': parse_graphics(_out(['pmset', '-g', 'systemstate'])),
        'thermal': parse_int(_out(['osascript', '-l', 'JavaScript', '-e', THERMAL_JS]), 3),
        'pressure': parse_int(_out(['sysctl', '-n', 'kern.memorystatus_vm_pressure_level']), 4),
        'logic': bool(logic.strip()),
        'foreign': foreign_song2logic(_out(['ps', '-axo', 'pid=,pgid=,command=']), own_pgids),
    }


def away(s: dict[str, Any], idle_min: float) -> bool:
    return s['idle_s'] is not None and s['idle_s'] >= idle_min * 60 and not s['display_held'] and not s['logic']


def can_start(s: dict[str, Any]) -> bool:
    return bool(s['on_ac'] and s['graphics'] and s['thermal'] == 0 and s['pressure'] == 1)


def must_stop(s: dict[str, Any]) -> str | None:
    if not s['on_ac']:
        return 'bateria'
    if s['thermal'] >= 2:
        return f'temperatura (thermalState {s["thermal"]})'
    if s['pressure'] >= 2:
        return f'pamięć (pressure {s["pressure"]})'
    return None
