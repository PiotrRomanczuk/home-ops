"""claude_state.py — what claude-collector reads besides the transcripts.

  load()/save()   collector state: byte offset per transcript file + the folded
                  session states (claude_transcript.new_state), atomically saved
  git_remote()    owner/repo of a cwd's origin, cached in the state
  live_sessions() Claude Code's process registry (~/.claude/sessions/<pid>.json)
                  → which sessions are running now and their status
  desktop_titles() Claude Desktop's session titles (Mac only; absent elsewhere)

The registry's *.key files hold a peer token — never opened here.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

_REMOTE_RE = re.compile(r'[:/]([^/:\s]+)/([^/\s]+?)(?:\.git)?/?$')


def load(path: Path) -> dict[str, Any]:
    try:
        st = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        st = {}
    for key in ('files', 'sessions', 'remotes'):
        st.setdefault(key, {})
    return st


def save(path: Path, st: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(st, ensure_ascii=False))
    tmp.replace(path)


def normalize_remote(url: str) -> str | None:
    m = _REMOTE_RE.search(url.strip())
    return f'{m.group(1)}/{m.group(2)}' if m else None


def git_remote(st: dict[str, Any], cwd: str | None) -> str | None:
    if not cwd:
        return None
    if cwd in st['remotes']:
        return st['remotes'][cwd]
    if not Path(cwd).is_dir():
        return None  # gone (temp checkout) — don't cache, a later session may recreate it
    try:
        out = subprocess.run(['git', '-C', cwd, 'config', '--get', 'remote.origin.url'],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    st['remotes'][cwd] = normalize_remote(out) if out.strip() else None
    return st['remotes'][cwd]


def _alive(pid: Any) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def live_sessions(registry: Path) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for f in sorted(registry.glob('*.json')):
        try:
            rec = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(rec, dict) and rec.get('sessionId') and _alive(rec.get('pid')):
            out.append({'session_id': str(rec['sessionId']), 'status': str(rec.get('status') or 'running')})
    return out


def desktop_titles(root: Path) -> dict[str, str]:
    titles: dict[str, str] = {}
    for f in root.glob('*/*/local_*.json'):
        try:
            rec = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(rec, dict) and rec.get('cliSessionId') and rec.get('title'):
            titles[str(rec['cliSessionId'])] = str(rec['title'])
    return titles
