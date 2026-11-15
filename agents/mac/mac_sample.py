"""mac_sample.py — the macOS-only readings for mac-watcher, without sudo.

  gpu()            Apple Silicon GPU load + memory from `ioreg -c IOAccelerator`
                   (Activity Monitor's numbers; per-process GPU needs root)
  NetCounter       per-process network from `nettop` — its counters are
                   cumulative since process start, so this keeps the last
                   reading and returns per-interval deltas
  ollama_models()  models loaded in the local Ollama (GET /api/ps)
  on_home_lan()    any interface on the Orange LAN → ship over LAN, else Tailscale

Parsers take the raw command output so tests can feed recorded samples.
"""
from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from typing import Any

_IOREG_KEYS = {
    'Device Utilization %': 'gpu_pct',
    'Renderer Utilization %': 'renderer_pct',
    'In use system memory': 'mem_bytes',
}
_IOREG_RE = re.compile(r'"(Device Utilization %|Renderer Utilization %|In use system memory)"\s*=\s*(\d+)')
_NETTOP_LINE = re.compile(r'^(?P<name>.+)\.(?P<pid>\d+),(?P<rx>\d+),(?P<tx>\d+),?$')


def _run(cmd: list[str], timeout: float = 10.0) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ''


def parse_ioreg(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for key, value in _IOREG_RE.findall(text):
        out.setdefault(_IOREG_KEYS[key], int(value))
    return out


def gpu() -> dict[str, int]:
    return parse_ioreg(_run(['ioreg', '-r', '-d', '1', '-c', 'IOAccelerator']))


def parse_nettop(text: str) -> dict[int, tuple[str, int, int]]:
    """pid → (name, bytes_in, bytes_out), cumulative."""
    out: dict[int, tuple[str, int, int]] = {}
    for line in text.splitlines():
        m = _NETTOP_LINE.match(line.strip())
        if m:
            out[int(m['pid'])] = (m['name'], int(m['rx']), int(m['tx']))
    return out


class NetCounter:
    def __init__(self) -> None:
        self.last: dict[int, tuple[int, int]] = {}

    def deltas(self, text: str | None = None) -> dict[int, tuple[str, int, int]]:
        """pid → (name, rx, tx) bytes since the previous call. First call → {}."""
        if text is None:
            text = _run(['nettop', '-P', '-L', '1', '-x', '-J', 'bytes_in,bytes_out'])
        now = parse_nettop(text)
        out: dict[int, tuple[str, int, int]] = {}
        for pid, (name, rx, tx) in now.items():
            if pid in self.last:
                prx, ptx = self.last[pid]
                drx, dtx = max(rx - prx, 0), max(tx - ptx, 0)
                if drx or dtx:
                    out[pid] = (name, drx, dtx)
        self.last = {pid: (rx, tx) for pid, (_, rx, tx) in now.items()}
        return out


def ollama_models(url: str = 'http://127.0.0.1:11434/api/ps') -> list[dict[str, Any]] | None:
    """Loaded models, or None when Ollama isn't running."""
    try:
        with urllib.request.urlopen(url, timeout=1.5) as r:
            body = json.loads(r.read() or b'{}')
    except (OSError, ValueError):
        return None
    return [{'name': m.get('name'), 'vram_mb': int(m.get('size_vram') or 0) // 2**20}
            for m in body.get('models') or [] if isinstance(m, dict)]


def on_home_lan(addrs: dict[str, list[Any]], prefix: str = '192.168.1.') -> bool:
    """addrs = psutil.net_if_addrs(); True when any IPv4 is on the home subnet."""
    return any(str(getattr(a, 'address', '')).startswith(prefix) for lst in addrs.values() for a in lst)
