#!/usr/bin/env python3
"""runner.py — run queued tasks through headless Claude Code until the deadline.

N workers (SPRINT_WORKERS, default 3) each loop: stop file / deadline → claim
the best eligible task (sprint_tasks.py) → `claude -p` in the task's cwd, fresh
session, the task's model, sprint rules appended to the system prompt, no MCP
servers, permission mode auto with nobody to answer prompts (what would ask is
denied; ~/.claude/hooks/guard-bash.py still blocks merges and prod) → log the
full JSON result, append a row to the vault report, move the task.

Usage limit hit → the task goes back to the queue and all workers pause; a
Fable task is first retried on Opus (the Fable allowance is separate).
When the queue runs low a `planner` task is added (planner.md): Claude itself
decides what to do next and on which model.

Env: SPRINT_PLANNER=0 (dry run: no planner/summary tasks), SPRINT_STATE (~/.local/state/home-ops/sprint), SPRINT_DEADLINE
(ISO local time), SPRINT_WORKERS, SPRINT_REPORT (markdown file in the vault).
Stop: `touch $SPRINT_STATE/STOP`.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import sprint_tasks as q

HERE = Path(__file__).resolve().parent
STATE = Path(os.environ.get('SPRINT_STATE', '~/.local/state/home-ops/sprint')).expanduser()
DEADLINE = datetime.fromisoformat(os.environ.get('SPRINT_DEADLINE', '2026-11-16T16:30:00'))
WORKERS = int(os.environ.get('SPRINT_WORKERS', '3'))
REPORT = Path(os.environ.get('SPRINT_REPORT', '~/Obsidian/MainCV-Planner/3-Zasoby/analysis/2026-11-14-sprint-48h.md')).expanduser()
CLAUDE = os.environ.get('CLAUDE_BIN', '/opt/homebrew/bin/claude')
LIMIT_RE = re.compile(r'usage limit|limit reached|rate limit|hit your limit|out of .*usage', re.I)
PAUSE_S, LOW_QUEUE, SUMMARY_EVERY_S = 600, 6, 5 * 3600
PLANNER = os.environ.get('SPRINT_PLANNER', '1') != '0'  # 0 = dry runs: never add planner/summary tasks
lock = threading.Lock()
paused_until = 0.0


def notify(text: str) -> None:  # macOS notification centre
    subprocess.run(['osascript', '-e', f'display notification "{text}" with title "Sprint Claude"'], check=False)


def stopping() -> bool:
    return (STATE / 'STOP').exists() or datetime.now() >= DEADLINE


def run_claude(task: dict[str, Any], model: str) -> dict[str, Any]:
    cwd = Path(str(task.get('cwd') or '~')).expanduser()
    prompt = f'{task["body"]}\n\nID zadania: {task["id"]}. Wynik zapisz w {STATE}/results/{task["id"]}.md.'
    cmd = [CLAUDE, '-p', prompt, '--model', model, '--effort', str(task.get('effort') or 'medium'),
           '--permission-mode', 'auto', '--permission-prompts', 'none', '--output-format', 'json',
           '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--no-chrome',
           '--append-system-prompt', (HERE / 'rules.md').read_text(),
           '--add-dir', str(STATE), str(REPORT.parent.parent.parent), '-n', f'sprint:{task["id"]}']
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd if cwd.is_dir() else Path.home(), capture_output=True, text=True,
                           timeout=task['max_minutes'] * 60)
        out, rc, err = p.stdout, p.returncode, p.stderr[-2000:]
    except subprocess.TimeoutExpired as e:
        out, rc, err = (e.stdout or b'').decode(errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or ''), 124, 'timeout'
    try:
        res = json.loads(out)
    except ValueError:
        res = {'result': out[-2000:], 'is_error': True}
    return {'id': task['id'], 'model': model, 'rc': rc, 'stderr': err, 'seconds': round(time.time() - t0), 'res': res}


def record(task: dict[str, Any], run: dict[str, Any], outcome: str) -> None:
    with (STATE / 'logs' / 'runs.jsonl').open('a') as f:
        f.write(json.dumps({'ts': datetime.now().isoformat(timespec='seconds'), 'outcome': outcome,
                            'project': task.get('project'), 'kind': task.get('kind'), **run}, ensure_ascii=False) + '\n')
    res = run['res']
    usage = res.get('usage') or {}
    tokens = sum(int(usage.get(k) or 0) for k in ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'))
    line = (f'| {datetime.now():%d.%m %H:%M} | {task["id"]} | {task.get("project") or "-"} | {run["model"]} | '
            f'{run["seconds"] // 60} min | {tokens // 1000} k | {res.get("total_cost_usd") or 0:.2f} | {outcome} |\n')
    with lock, REPORT.open('a') as f:
        f.write(line)


def worker(n: int) -> None:
    global paused_until
    while not stopping():
        if time.time() < paused_until:
            time.sleep(30)
            continue
        with lock:
            task = q.claim(STATE)
        if not task:
            time.sleep(20)
            continue
        model = str(task.get('model') or 'sonnet')
        run = run_claude(task, model)
        text = json.dumps(run['res'])[:4000] + run['stderr']
        limited = (run['rc'] != 0 or run['res'].get('is_error')) and LIMIT_RE.search(text)
        if limited and model == 'fable':  # Fable has its own allowance — try Opus before pausing everyone
            notify('Limit Fable? Zadania Fable idą na Opus. Możesz kliknąć reset Fable.')
            task['model'] = 'opus'
            record(task, run, 'limit-fable')
            q.finish(STATE, task, 'requeue')
        elif limited:
            paused_until = time.time() + PAUSE_S
            notify('Limit sesji wyczerpany. Workerzy czekają i próbują co 10 min.')
            record(task, run, 'limit')
            q.finish(STATE, task, 'requeue')
        else:
            ok = run['rc'] == 0 and not run['res'].get('is_error')
            record(task, run, 'done' if ok else 'retry')
            q.finish(STATE, task, 'done' if ok else 'retry')


def housekeeping() -> None:
    """Keep the queue fed (planner) and the report summarised (every 5 h)."""
    last_summary = time.time()
    while PLANNER and not stopping():
        time.sleep(60)
        with lock:
            pending = q.ids(STATE, 'queue') | q.ids(STATE, 'running')
            if len(q.eligible(STATE)) < LOW_QUEUE and not any(i.startswith('planner-') for i in pending):
                (STATE / 'queue' / f'planner-{int(time.time())}.md').write_text((HERE / 'planner.md').read_text())
            if time.time() - last_summary > SUMMARY_EVERY_S:
                last_summary = time.time()
                (STATE / 'queue' / f'summary-{int(time.time())}.md').write_text((HERE / 'summary.md').read_text())


def main() -> None:
    q.setup(STATE)
    if not REPORT.exists():
        REPORT.write_text((HERE / 'report-head.md').read_text())
    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(WORKERS)]
    threads.append(threading.Thread(target=housekeeping, daemon=True))
    [t.start() for t in threads]
    while not stopping():
        time.sleep(15)
    notify('Sprint zatrzymany (STOP albo termin). Bieżące zadania dobiegają końca.')
    for t in threads[:-1]:
        t.join(timeout=3600)


if __name__ == '__main__':
    main()
