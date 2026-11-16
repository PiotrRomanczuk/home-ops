"""budget.py — how much of Piotr's Claude subscription the background may use right now.

`claude -p /usage` (headless, costs no tokens) returns `usage_report.rate_limits.limits[]`: the 5-hour
session, the week for all models and per-model weeks (Fable), each with `percent` and `resets_at`.
One Budget object caches the last reading (STATE/usage.json for the status page). A Claude task may
start only when (verdict() returns None):
- the week is under `weekly_cap` (80%: the rest stays Piotr's), and under the pace line —
  cap × the share of the week since the last reset + `pace_head_start`, so one night can't burn it all;
- the session is under `session_cap` (room for Piotr's own sessions, Remote Control included);
- a Fable task: the Fable week is under `fable_weekly_cap`.
A reading older than STALE_S blocks starts. Local models (`local:*`) never reach this module.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

WEEK = timedelta(days=7)
MIN_GAP_S, STALE_S = 60, 15 * 60
Limits = dict[str, dict[str, Any]]


def when(value: Any) -> datetime | None:
    return datetime.fromisoformat(str(value).replace('Z', '+00:00')) if value else None


def parse(report: dict[str, Any]) -> Limits:
    """usage_report → {'session' | 'weekly' | '<model, lower case>': {'percent': float, 'resets_at': datetime|None}}."""
    out: Limits = {}
    for item in (report.get('rate_limits') or {}).get('limits') or []:
        model = (((item.get('scope') or {}).get('model') or {}).get('display_name') or '').lower()
        key = {'session': 'session', 'weekly_all': 'weekly'}.get(item.get('kind')) or (model or None)
        if key:
            out[key] = {'percent': float(item.get('percent') or 0), 'resets_at': when(item.get('resets_at'))}
    return out


def fetch(claude: str) -> dict[str, Any] | None:
    cmd = [claude, '-p', '/usage', '--output-format', 'stream-json', '--verbose', '--no-session-persistence']
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in out.splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if isinstance(msg, dict) and msg.get('usage_report'):
            return msg['usage_report']
    return None


def pace(cap: float, head: float, resets_at: datetime | None, now: datetime) -> float:
    if resets_at is None:
        return cap
    share = 1 - (resets_at - now) / WEEK
    return min(cap, cap * max(0.0, min(1.0, share)) + head)


def verdict(limits: Limits, cfg: dict[str, Any], model: str, now: datetime) -> str | None:
    """None when a task on `model` may start now, else the reason (shown on the status page)."""
    week, session = limits.get('weekly'), limits.get('session')
    if week is None or session is None:
        return 'brak odczytu limitów'
    line = pace(cfg['weekly_cap'], cfg['pace_head_start'], week['resets_at'], now)
    if week['percent'] >= cfg['weekly_cap']:
        return f'tydzień {week["percent"]:.0f}% ≥ {cfg["weekly_cap"]}%'
    if week['percent'] >= line:
        return f'tempo: tydzień {week["percent"]:.0f}% ≥ linia {line:.0f}%'
    if session['percent'] >= cfg['session_cap']:
        return f'sesja {session["percent"]:.0f}% ≥ {cfg["session_cap"]}%'
    scoped = limits.get(model)
    if model not in ('session', 'weekly') and scoped and scoped['percent'] >= cfg['fable_weekly_cap']:
        return f'{model} tydzień {scoped["percent"]:.0f}% ≥ {cfg["fable_weekly_cap"]}%'
    return None


def exhausted_until(limits: Limits, now: datetime, keys: tuple[str, ...] = ('session', 'weekly')) -> datetime | None:
    """Latest reset among `keys` that are really used up (≥ 99%). The default — session and week — is what pauses
    every Claude worker; a model's own week (('fable',)) only holds that model's task (outcomes.py)."""
    times = [v['resets_at'] for k, v in limits.items() if k in keys and v['percent'] >= 99 and v['resets_at'] and v['resets_at'] > now]
    return max(times) if times else None


class Budget:
    def __init__(self, state: Path, claude: str) -> None:
        self.path, self.claude = state / 'usage.json', claude
        self.lock = threading.Lock()
        self.limits: Limits = {}
        self.read_at = 0.0

    def refresh(self, force: bool = False) -> None:
        with self.lock:
            if not force and time.time() - self.read_at < MIN_GAP_S:
                return
            report = fetch(self.claude)
            if report is None:
                return
            self.limits, self.read_at = parse(report), time.time()
            dump = {k: {'percent': v['percent'], 'resets_at': v['resets_at'] and v['resets_at'].isoformat()} for k, v in self.limits.items()}
            self.path.write_text(json.dumps({'read_at': self.read_at, 'limits': dump}))

    def verdict(self, cfg: dict[str, Any], model: str) -> str | None:
        if time.time() - self.read_at > STALE_S:
            return 'odczyt limitów nieaktualny'
        return verdict(self.limits, cfg, model, datetime.now(timezone.utc))

    def week_start(self) -> date:
        """Local date of the last weekly reset (names the weekly report); Monday of this week before the first reading."""
        resets = (self.limits.get('weekly') or {}).get('resets_at')
        if resets:
            return (resets - WEEK).astimezone().date()
        today = date.today()
        return today - timedelta(days=today.weekday())
