#!/usr/bin/env python3
"""day-summary — the Mac's day as one card on Dziś, written by the local model.

launchd runs it at 21:30; if the Mac slept through it launchd runs it at wake-up,
which is the next morning — so without an argument it takes today only from
21:00 on and yesterday before that (day_prompt.pick_day):
  1. GET /api/journal/day for that day (and the one before it, for the trend);
  2. GET /api/today for the Now tasks of hot/warm projects;
  3. ask the local Ollama (DAY_MODEL if installed, else the first installed of
     qwen3.5:9b / gemma4:12b / gemma4:26b / qwen3.5:35b) for "Dzień" + "Co
     dalej" — private, free; if Ollama is down the card stays factual;
  4. POST /api/journal (rollup + summary → day_journal, kept for good) and the
     card "mac-dziennik" via routine_report.

Usage: day-summary.py [YYYY-MM-DD]   (default: pick_day(now), local time)
Env: INGEST_URL / INGEST_TOKEN, HOST_NAME (default mac), DAY_MODEL, OLLAMA_URL.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))
sys.path.insert(0, str(_here.parent))
from day_prompt import build_prompt, card, next_steps, pick_day  # noqa: E402
from routine_report import Reporter  # noqa: E402

HOST = os.environ.get('HOST_NAME', 'mac')
OLLAMA = os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
# First one installed wins — models come and go on this Mac (benchmarks pull and drop them).
PREFERRED = [m for m in [os.environ.get('DAY_MODEL')] if m] + ['qwen3.5:9b', 'gemma4:12b', 'gemma4:26b', 'qwen3.5:35b']


def pick_model() -> str | None:
    try:
        with urllib.request.urlopen(OLLAMA + '/api/tags', timeout=5) as r:
            names = [m.get('name') for m in json.loads(r.read()).get('models') or []]
    except (OSError, ValueError):
        return None
    return next((m for m in PREFERRED if m in names), None)


def ask_ollama(prompt: str, model: str) -> str | None:
    body = {'model': model, 'messages': [{'role': 'user', 'content': prompt}], 'stream': False,
            'think': False, 'options': {'temperature': 0.3}}
    req = urllib.request.Request(OLLAMA + '/api/chat', data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            text = (json.loads(r.read()).get('message') or {}).get('content') or ''
    except (OSError, ValueError) as e:
        print(f'ollama unavailable ({e}); card stays factual', file=sys.stderr)
        return None
    return text.strip() or None


def now_tasks(today: dict[str, Any]) -> list[str]:
    return [f'{g.get("slug")}: {t.get("title") or t.get("text")}'
            for g in today.get('tasks') or [] for t in g.get('tasks') or []]


def main(argv: list[str]) -> int:
    day = date.fromisoformat(argv[1]) if len(argv) > 1 else pick_day(datetime.now())
    r = Reporter.from_env('mac-dziennik')
    journal = r._call('GET', f'/api/journal/day?host={HOST}&day={day.isoformat()}')
    prev = r._call('GET', f'/api/journal/day?host={HOST}&day={(day - timedelta(days=1)).isoformat()}')
    prev_active = ((prev.get('claude') or {}).get('totals') or {}).get('active_min')
    model = pick_model()
    text = ask_ollama(build_prompt(journal, now_tasks(r._call('GET', '/api/today'))), model) if model else None
    rollup = {k: v for k, v in journal.items() if k != 'journal'}
    r._call('POST', '/api/journal', {'host': HOST, 'day': day.isoformat(), 'rollup': rollup,
                                     'summary_md': text, 'model': model if text else None})
    c = card(journal, next_steps(text or ''), prev_active)
    r.card(c['headline'], status='ok' if text else 'warn', items=c['items'], metric=c['metric'])
    print(c['headline'])
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
