"""gpu_report.py — what the GPU supervisor leaves behind: log.jsonl (every event, appended)
and status.json (the current state, rewritten atomically for the status page)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now().isoformat(timespec='seconds')


def log(gpu: Path, event: str, **data: Any) -> None:
    with (gpu / 'log.jsonl').open('a') as f:
        f.write(json.dumps({'ts': now(), 'event': event, **data}, ensure_ascii=False) + '\n')


def status(gpu: Path, job: str | None, reason: str | None, s: dict[str, Any] | None,
           jobs_done: int, jobs_total: int, shards: dict[int, dict[str, Any]]) -> None:
    idle = s.get('idle_s') if s else None
    data = {'ts': now(), 'job': job, 'reason': reason, 'jobs_done': jobs_done, 'jobs_total': jobs_total,
            'shards': {str(n): 'pauza' if sh['paused'] else 'pracuje' for n, sh in shards.items()},
            'thermal': s['thermal'] if s else None, 'pressure': s['pressure'] if s else None,
            'idle_min': round(idle / 60) if idle is not None else None}
    tmp = gpu / 'status.tmp'
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.replace(gpu / 'status.json')
