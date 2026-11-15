"""mac_procs.py — which Claude session started a process, and which processes matter.

Attribution (no sudo): walk a process's ancestors; it belongs to a session when
  * an ancestor's pid is in Claude Code's registry (~/.claude/sessions/<pid>.json), or
  * an ancestor's command line points into a session scratchpad
    (/private/tmp/claude-<uid>/<cwd>/<session-id>/…) — this catches jobs a
    session left running after it detached them (ppid 1).

Tracker decides what is worth a host_logs line ("proc start" / "proc stop"):
  * a session's process that is not the session's own MCP server or shell and
    has lived ≥ 2 min (a background job, a long command), or
  * ≥ 25 % CPU in two consecutive samples, or
  * ≥ 1 MB/s of network in one sample.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_SCRATCH_RE = re.compile(r'/claude-\d+/[^/\s]+/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/')
SHELLS = {'zsh', 'bash', 'sh', 'fish', 'login'}
LONG_S, HOT_PCT, NET_BPS = 120, 25.0, 1_000_000


def registry(path: Path) -> dict[int, dict[str, str]]:
    """pid → {session_id, name, status} for Claude Code processes (stale files included —
    callers intersect with the live process table)."""
    out: dict[int, dict[str, str]] = {}
    for f in path.glob('*.json'):
        try:
            rec = json.loads(f.read_text())
            out[int(rec['pid'])] = {'session_id': str(rec['sessionId']), 'name': str(rec.get('name') or ''),
                                    'status': str(rec.get('status') or '')}
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


def session_of(pid: int, procs: dict[int, dict[str, Any]], reg: dict[int, dict[str, str]]) -> str | None:
    """procs: pid → {ppid, cmd}. Walks at most 20 ancestors (cycles are impossible but cheap to guard)."""
    seen = 0
    while pid in procs and seen < 20:
        if pid in reg:
            return reg[pid]['session_id']
        m = _SCRATCH_RE.search(procs[pid].get('cmd') or '')
        if m:
            return m.group(1)
        pid = procs[pid].get('ppid') or 0
        seen += 1
    return reg[pid]['session_id'] if pid in reg else None


class Tracker:
    def __init__(self) -> None:
        self.live: dict[int, dict[str, Any]] = {}     # notable processes still running
        self.hot: dict[int, int] = {}                 # pid → consecutive hot samples

    def update(self, procs: dict[int, dict[str, Any]], reg: dict[int, dict[str, str]],
               net: dict[int, tuple[str, int, int]], now: float, interval: float) -> list[dict[str, Any]]:
        """procs: pid → {name, ppid, cmd, cpu_pct, cpu_s, started}. Returns start/stop records."""
        out: list[dict[str, Any]] = []
        for pid, p in procs.items():
            self.hot[pid] = self.hot.get(pid, 0) + 1 if (p.get('cpu_pct') or 0) >= HOT_PCT else 0
            rx, tx = net.get(pid, ('', 0, 0))[1:]
            if pid in self.live:
                rec = self.live[pid]
                rec['net_bytes'] += rx + tx
                rec['cpu_s'] = p.get('cpu_s') or rec['cpu_s']
                continue
            sid = session_of(pid, procs, reg)
            reason = self._reason(pid, p, procs, reg, sid, (rx + tx) / max(interval, 1), now)
            if reason:
                claude_pid, _ = lineage(pid, procs, reg)
                rec = {'pid': pid, 'name': p.get('name'), 'cmd': p.get('cmd'), 'session_id': sid,
                       'session_name': reg.get(claude_pid or -1, {}).get('name'),
                       'reason': reason, 'started': now if p.get('started') is None else p['started'],
                       'cpu_s': p.get('cpu_s') or 0.0,
                       'net_bytes': rx + tx}
                self.live[pid] = rec
                out.append({'event': 'start', **rec})
        for pid in [p for p in self.live if p not in procs]:
            rec = self.live.pop(pid)
            out.append({'event': 'stop', **rec, 'duration_s': round(now - rec['started'])})
        self.hot = {pid: n for pid, n in self.hot.items() if pid in procs}
        return out

    def _reason(self, pid: int, p: dict[str, Any], procs: dict[int, dict[str, Any]],
                reg: dict[int, dict[str, str]], sid: str | None, bps: float, now: float) -> str | None:
        if bps >= NET_BPS:
            return 'net'
        if self.hot.get(pid, 0) >= 2:
            return 'cpu'
        started = p.get('started')
        if not sid or pid in reg or p.get('name') in SHELLS or started is None or now - started < LONG_S:
            return None
        claude_pid, top = lineage(pid, procs, reg)
        # Bash-tool jobs hang off a shell the session spawned; MCP servers (and
        # their node/uv children) hang off claude directly — those are plumbing.
        if claude_pid is None or procs.get(top or -1, {}).get('name') in SHELLS:
            return 'claude'
        return None


def lineage(pid: int, procs: dict[int, dict[str, Any]], reg: dict[int, dict[str, str]]) -> tuple[int | None, int | None]:
    """(registered claude pid above pid, the ancestor right below it) — (None, None) for orphans."""
    child, seen = None, 0
    while pid in procs and pid not in reg and seen < 20:
        child, pid, seen = pid, procs[pid].get('ppid') or 0, seen + 1
    return (pid, child) if pid in reg else (None, None)
