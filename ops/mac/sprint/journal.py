"""journal.py — what the runner writes down: every run in full (STATE/logs/runs.jsonl: `ts` with its UTC offset,
the task's frontmatter as `task` — attempts, interrupts, not_before, resume, … —, then the run with its whole
stderr up to 64 KB) and one row per run in the weekly vault report
(3-Zasoby/analysis/<week start>-mac-worker-tydzien.md, started from report-head.md). The week starts at the
subscription's weekly reset (budget.week_start)."""
from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
VAULT = Path(os.environ.get('SPRINT_VAULT', '~/Obsidian/MainCV-Planner')).expanduser()  # tests point it elsewhere


def report_path(week_start: date) -> Path:
    return VAULT / '3-Zasoby' / 'analysis' / f'{week_start:%Y-%m-%d}-mac-worker-tydzien.md'


def record(state: Path, task: dict[str, Any], run: dict[str, Any], outcome: str, week_start: date,
           lock: threading.Lock) -> None:
    meta = {k: v for k, v in task.items() if k not in ('body', 'path')}  # as the task stands after this run
    with (state / 'logs' / 'runs.jsonl').open('a') as f:
        f.write(json.dumps({'ts': datetime.now().astimezone().isoformat(timespec='seconds'), 'outcome': outcome,
                            'project': task.get('project'), 'kind': task.get('kind'), 'task': meta, **run},
                           ensure_ascii=False) + '\n')
    res = run['res']
    usage = res.get('usage') or {}
    tokens = sum(int(usage.get(k) or 0) for k in ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'))
    line = (f'| {datetime.now():%d.%m %H:%M} | {task["id"]} | {task.get("project") or "-"} | {run["model"]} | '
            f'{run["seconds"] // 60} min | {tokens // 1000} k | {res.get("total_cost_usd") or 0:.2f} | {outcome} |\n')
    path = report_path(week_start)
    with lock:
        if not path.exists():
            path.write_text((HERE / 'report-head.md').read_text().replace('{week}', f'{week_start:%Y-%m-%d}'))
        with path.open('a') as f:
            f.write(line)


def local_runs_today(state: Path) -> int:
    """Runs on a local model started today (the runner caps them per day)."""
    today = date.today().isoformat()
    try:
        lines = (state / 'logs' / 'runs.jsonl').read_text().splitlines()
    except FileNotFoundError:
        return 0
    count = 0
    for line in reversed(lines):
        if not line.startswith('{"ts": "' + today):
            break
        if '"model": "local:' in line:
            count += 1
    return count
