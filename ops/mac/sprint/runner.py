#!/usr/bin/env python3
"""runner.py — the Mac worker: queued tasks through headless Claude Code, within Piotr's limits.

N workers (config `claude.workers`) each loop: STOP file → claim the best task that may start now →
claude_run.py → runs.jsonl + a row in the weekly report (journal.py) → move the task.

May start now (accept_for):
- a Claude model: inside a window (config.py) with its max_minutes still fitting, and budget.py allows it
  (week under 80% and under the pace line, session under 90%); STATE/config.json overrides defaults;
- `local:<ollama model>`: Piotr away from the Mac and the Mac fit for GPU work (machine.py), one at a time,
  at most `local.max_tasks_per_day`; the same harness against Ollama (no subscription use), borrowing the GPU
  from the GPU supervisor (STATE/gpu/borrow); escalates to sonnet when it fails.
What a run means for its task (limit, interrupted, done, retry) is outcomes.py. Housekeeping polls /usage
and feeds the queue (feed.py). lifecycle.py: one runner per STATE (flock); an exception in a thread goes to
logs/runner-errors.jsonl and fails its task; main() exits 1 when a thread is gone, so launchd restarts it;
SIGTERM or that exit first end every run (their process groups are outside the launchd job's).
Env: SPRINT_STATE, SPRINT_PLANNER=0 (no planner/summary tasks), CLAUDE_BIN.  Stop: `touch $SPRINT_STATE/STOP`.
"""
from __future__ import annotations

import os
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
import feed  # noqa: E402
import journal  # noqa: E402
import lifecycle  # noqa: E402
import machine  # noqa: E402
import outcomes  # noqa: E402
import sprint_tasks as q  # noqa: E402

STATE = Path(os.environ.get('SPRINT_STATE', '~/.local/state/home-ops/sprint')).expanduser()
CLAUDE = os.environ.get('CLAUDE_BIN', '/opt/homebrew/bin/claude')
POLL_S = 300
PLANNER = os.environ.get('SPRINT_PLANNER', '1') != '0'
lock = threading.Lock()
budget = b.Budget(STATE, CLAUDE)
paused_until = 0.0


def stopping() -> bool:
    return lifecycle.halted.is_set() or (STATE / 'STOP').exists()


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
            busy = any(q.is_local(t) for t in q.load(STATE / 'running'))
            snap = None if busy else machine.snapshot()
            seen['ok'] = bool(snap and machine.away(snap, cfg['local']['idle_min']) and machine.can_start(snap)
                              and journal.local_runs_today(STATE) < cfg['local']['max_tasks_per_day'])
        return seen['ok']

    return lambda task: local_ok() if q.is_local(task) else claude_reason(task, cfg['claude']) is None


def execute(task: dict[str, Any], cfg: dict[str, Any]) -> None:
    global paused_until
    model = str(task.get('model') or 'sonnet')
    run = claude_run.run(CLAUDE, task, model, STATE, journal.VAULT, cfg['local']['base_url'],
                         local_minutes=cfg['local']['max_minutes'])
    if outcomes.wants_usage(run):  # a limit without a reset hour in the message
        budget.refresh(force=True)
    outcome, meta = outcomes.classify(run, datetime.now(timezone.utc), kind=task.get('kind'), limits=budget.limits,
                                      result_mtime=outcomes.mtime(STATE / 'results' / f'{task["id"]}.md'))
    if meta.get('pause_until'):  # session or weekly limit: no Claude task can start before the reset
        with lock:
            paused_until = max(paused_until, meta['pause_until'].timestamp())
        lifecycle.notify(f'Limit ({meta["scope"]}) wyczerpany. Agenci Claude czekają do {meta["pause_until"].astimezone():%H:%M}.')
    task.update(meta['set'])
    if meta.get('note'):
        task['body'] += f'\n\nPoprzednia próba ({model}, rc {run["rc"]}): {meta["note"]}'
    journal.record(STATE, task, run, outcome, budget.week_start(), lock)
    q.finish(STATE, task, outcome, meta.get('escalate', True))


def worker(n: int) -> None:
    while not stopping():
        task = None
        try:
            cfg = config.load(STATE)
            with lock:
                task = q.claim(STATE, accept_for(cfg))
            if task:
                execute(task, cfg)
                continue
        except Exception:  # noqa: BLE001 — else the thread dies and its task stays in running/
            lifecycle.fail(STATE, f'worker-{n}', task)
        lifecycle.halted.wait(20)


def housekeeping() -> None:
    """Poll /usage inside the windows; keep the Claude queue fed (feed.py)."""
    while not stopping():
        try:
            cfg, now = config.load(STATE)['claude'], datetime.now()
            if config.window_end(cfg['windows'], now) and time.time() - budget.read_at >= POLL_S:
                budget.refresh()
            with lock:
                if PLANNER:
                    ready = len([t for t in q.eligible(STATE) if not q.is_local(t)])
                    feed.feed(STATE, cfg, now, ready, budget.verdict(cfg, 'opus') is None)
        except Exception:  # noqa: BLE001
            lifecycle.log_error(STATE, 'housekeeping')
        time.sleep(60)


def main() -> None:
    instance = lifecycle.single_instance(STATE)  # held until the process ends
    if instance is None:
        print(f'another runner holds {STATE}/runner.lock; exiting', file=sys.stderr)
        return
    q.setup(STATE)
    budget.refresh()
    workers = int(config.load(STATE)['claude']['workers'])
    threads = [threading.Thread(target=worker, args=(i,), name=f'worker-{i}', daemon=True) for i in range(workers)]
    threads.append(threading.Thread(target=housekeeping, name='housekeeping', daemon=True))
    lifecycle.on_sigterm(threads[:-1])  # before the first run can start
    [t.start() for t in threads]
    lifecycle.watch(STATE, threads, stopping)
    lifecycle.notify('Mac worker zatrzymany (STOP). Bieżące zadania dobiegają końca.')
    for t in threads[:-1]:
        t.join(timeout=3600)


if __name__ == '__main__':
    main()
