"""config.py — the Mac worker's settings: STATE/config.json laid over DEFAULTS, and its time windows.

A window is "<days> HH:MM-HH:MM"; days = daily | mon-fri | sat-sun | mon,wed,fri (ranges and lists).
An end at or before the start runs past midnight into the next day ("daily 22:00-02:00").
Claude tasks start only inside a window and only if their max_minutes still fit before its end,
so nothing spills into Piotr's evening.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, dict[str, Any]] = {
    'claude': {'windows': ['mon-fri 08:30-16:00', 'daily 00:00-07:00'], 'workers': 3,
               'weekly_cap': 80, 'pace_head_start': 10, 'session_cap': 90, 'fable_weekly_cap': 80,
               'planner_every_h': 3, 'summary_at': '05:30'},
    'local': {'max_tasks_per_day': 8, 'idle_min': 10, 'base_url': 'http://127.0.0.1:11434',
              'max_minutes': 20},  # a hard cap on every local:* run, whatever the task says
}
DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')


def load(state: Path) -> dict[str, dict[str, Any]]:
    try:
        user = json.loads((state / 'config.json').read_text())
    except (FileNotFoundError, ValueError):
        user = {}
    return {key: {**value, **(user.get(key) or {})} for key, value in DEFAULTS.items()}


def days(spec: str) -> set[int]:
    if spec == 'daily':
        return set(range(7))
    out: set[int] = set()
    for part in spec.split(','):
        first, _, last = part.partition('-')
        out |= set(range(DAYS.index(first), DAYS.index(last or first) + 1))
    return out


def _clock(hhmm: str) -> timedelta:
    hours, minutes = hhmm.split(':')
    return timedelta(hours=int(hours), minutes=int(minutes))


def spans(windows: list[str], now: datetime) -> list[tuple[datetime, datetime]]:
    """Concrete (start, end) of each window opening yesterday or today (yesterday's may run past midnight)."""
    out = []
    for window in windows:
        spec, times = window.split()
        start_s, end_s = times.split('-')
        for back in (1, 0):
            day = (now - timedelta(days=back)).replace(hour=0, minute=0, second=0, microsecond=0)
            if day.weekday() in days(spec):
                start, end = day + _clock(start_s), day + _clock(end_s)
                out.append((start, end if end > start else end + timedelta(days=1)))
    return out


def window_end(windows: list[str], now: datetime) -> datetime | None:
    """End of the window `now` is in (the later one if two overlap), None outside every window."""
    ends = [end for start, end in spans(windows, now) if start <= now < end]
    return max(ends) if ends else None


def fits(windows: list[str], now: datetime, minutes: int) -> bool:
    end = window_end(windows, now)
    return end is not None and now + timedelta(minutes=minutes) <= end
