"""feed.py — what housekeeping adds to queue/: a planner when the Claude queue runs low, one summary a day."""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

import config

HERE = Path(__file__).resolve().parent
LOW_QUEUE = 6


def newest(state: Path, prefix: str) -> float:
    """mtime of the latest `<prefix>*.md` anywhere (failed/ included, so a planner that dies is not respawned every minute)."""
    return max((p.stat().st_mtime for d in ('queue', 'running', 'done', 'failed') for p in (state / d).glob(f'{prefix}*.md')), default=0.0)


def feed(state: Path, cfg: dict[str, Any], now: datetime, ready: int, opus_ok: bool) -> None:
    if (ready < LOW_QUEUE and newest(state, 'planner-') < time.time() - cfg['planner_every_h'] * 3600
            and config.fits(cfg['windows'], now, 30) and opus_ok):
        (state / 'queue' / f'planner-{int(time.time())}.md').write_text((HERE / 'planner.md').read_text())
    summary = f'summary-{now:%Y%m%d}'
    if now.strftime('%H:%M') >= cfg['summary_at'] and not newest(state, summary):
        (state / 'queue' / f'{summary}.md').write_text((HERE / 'summary.md').read_text())
