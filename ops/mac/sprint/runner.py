#!/usr/bin/env python3
"""runner.py — the Mac worker: queued tasks through headless Claude Code, within Piotr's limits.

N workers (config `claude.workers`) each loop: STOP file → claim the best task that may start now →
claude_run.py → runs.jsonl + a row in the weekly report (journal.py) → move the task.

May start now (accept()):
- a Claude model: inside a window (config.py) with its max_minutes still fitting, and budget.py allows
  it (week under 80% and under the pace line, session under 90%); STATE/config.json overrides defaults;
- `local:<ollama model>`: Piotr away from the Mac and the Mac fit for GPU work (machine.py), one at a time,
  at most `local.max_tasks_per_day`; the same harness against Ollama, so no subscription use. It borrows
  the GPU from the GPU supervisor (STATE/gpu/borrow) and escalates to sonnet when it fails.
A usage-limit message is checked against /usage: really used up → pause until that reset, else a retry.
Housekeeping polls /usage in windows, adds a planner when the Claude queue runs low (every planner_every_h
at most) and a daily summary.  Env: SPRINT_STATE, SPRINT_PLANNER=0 (none of those tasks), CLAUDE_BIN.
Stop: `touch $SPRINT_STATE/STOP`.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE.parent / 'gpu'))  # repo layout; the installed copies sit side by side
import budget as b  # noqa: E402
import claude_run  # noqa: E402
import config  # noqa: E402
import journal  # noqa: E402
import machine  # noqa: E402
import sprint_tasks as q  # noqa: E402

STATE = Path(os.environ.get('SPRINT_STATE', '~/.local/state/home-ops/sprint')).expanduser()
CLAUDE = os.environ.get('CLAUDE_BIN', '/opt/homebrew/bin/claude')
LIMIT_RE = re.compile(r'usage.?limit|session.?limit|weekly.?limit|limit.?reached|rate.?limit|hit your .{0,20}limit|out of .*usage', re.I)
LOW_QUEUE, POLL_S = 6, 300
PLANNER = os.environ.get('SPRINT_PLANNER', '1') != '0'
lock = threading.Lock()
budget = b.Budget(STATE, CLAUDE)
paused_until = 0.0


def notify(text: str) -> None:  # macOS notification centre
    subprocess.run(['osascript', '-e', f'display notification "{text}" with title "Mac worker"'], check=False)


def stopping() -> bool:
    return (STATE / 'STOP').exists()


def is_local(task: dict[str, Any]) -> bool:
    return str(task.get('model') or '').startswith('local:')


def claude_reason(task: dict[str, Any], cfg: dict[str, Any]) -> str | None:
    if time.time() < paused_until:
        return 'limit wyczerpany, pauza do resetu'
    if not config.fits(cfg['windows'], datetime.now(), task['max_minutes']):
        return 'poza oknem'
    return budget.verdict(cfg, str(task.get('model') or 'sonnet'))


def accept_for(cfg: dict[str, dict[str, Any]]) -> Any:
    seen: dict[str, bool] = {}

    def local_ok() -> bool:  # computed once per claim: probing the Mac takes a few subprocesses
        if 'ok' not in seen:
            busy = any(is_local(q.parse(p)) for p in (STATE / 'running').glob('*.md'))
            snap = None if busy else machine.snapshot()
            seen['ok'] = bool(snap and machine.away(snap, cfg['local']['idle_min']) and machine.can_start(snap)
                              and journal.local_runs_today(STATE) < cfg['local']['max_tasks_per_day'])
        return seen['ok']

    return lambda task: local_ok() if is_local(task) else claude_reason(task, cfg['claude']) is None


def worker(n: int) -> None:
    global paused_until
    while not stopping():
        cfg = config.load(STATE)
        with lock:
            task = q.claim(STATE, accept_for(cfg))
        if not task:
            time.sleep(20)
            continue
        model = str(task.get('model') or 'sonnet')
        run = claude_run.run(CLAUDE, task, model, STATE, journal.VAULT, cfg['local']['base_url'])
        ok = run['rc'] == 0 and not run['res'].get('is_error')
        outcome = 'done' if ok else 'retry'
        if not ok and not model.startswith('local:') and LIMIT_RE.search(json.dumps(run['res'])[:4000] + run['stderr']):
            budget.refresh(force=True)
            until = b.exhausted_until(budget.limits, model, datetime.now(timezone.utc))
            if until:  # really used up; otherwise "limit" was just a word in an ordinary failure
                with lock:
                    paused_until = max(paused_until, until.timestamp())
                notify(f'Limit wyczerpany. Agenci Claude czekają do {until.astimezone():%H:%M}.')
                outcome = 'limit'
        journal.record(STATE, task, run, outcome, budget.week_start(), lock)
        q.finish(STATE, task, 'requeue' if outcome == 'limit' else outcome)


def newest(prefix: str) -> float:
    return max((p.stat().st_mtime for d in ('queue', 'running', 'done', 'failed') for p in (STATE / d).glob(f'{prefix}*.md')), default=0.0)


def housekeeping() -> None:
    """Poll /usage inside the windows; keep the Claude queue fed (planner); one summary a day."""
    while not stopping():
        cfg, now = config.load(STATE)['claude'], datetime.now()
        if config.window_end(cfg['windows'], now) and time.time() - budget.read_at >= POLL_S:
            budget.refresh()
        with lock:
            ready = [t for t in q.eligible(STATE) if not is_local(t)]
            if (PLANNER and len(ready) < LOW_QUEUE and newest('planner-') < time.time() - cfg['planner_every_h'] * 3600
                    and config.fits(cfg['windows'], now, 30) and budget.verdict(cfg, 'opus') is None):
                (STATE / 'queue' / f'planner-{int(time.time())}.md').write_text((HERE / 'planner.md').read_text())
            summary = f'summary-{now:%Y%m%d}'
            if PLANNER and now.strftime('%H:%M') >= cfg['summary_at'] and not newest(summary):
                (STATE / 'queue' / f'{summary}.md').write_text((HERE / 'summary.md').read_text())
        time.sleep(60)


def main() -> None:
    q.setup(STATE)
    budget.refresh()
    workers = int(config.load(STATE)['claude']['workers'])
    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(workers)]
    threads.append(threading.Thread(target=housekeeping, daemon=True))
    [t.start() for t in threads]
    while not stopping():
        time.sleep(15)
    notify('Mac worker zatrzymany (STOP). Bieżące zadania dobiegają końca.')
    for t in threads[:-1]:
        t.join(timeout=3600)


if __name__ == '__main__':
    main()
