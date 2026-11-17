"""bench_result.py — `kind: bench` answers in its final message; the runner writes the result file.

A local model under `--permission-mode auto` is blocked by the classifier on every Write, so a bench task gets
read-only tools (claude_run.py) and no instruction to write; this module saves `res.result` as
STATE/results/<id>.md, which is what outcomes.classify expects to find (outcomes.py stays unchanged).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

KIND = 'bench'


def write_result(state: Path, task: dict[str, Any], run: dict[str, Any]) -> bool:
    """Save the answer of a successful bench run; False (nothing written) for any other kind or outcome."""
    res = run.get('res') or {}
    answer = str(res.get('result') or '').strip()
    if task.get('kind') != KIND or run.get('rc') != 0 or res.get('is_error') or not answer:
        return False
    when = time.strftime('%Y-%m-%d %H:%M', time.localtime())
    out = state / 'results' / f'{task["id"]}.md'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f'# {task["id"]} — wynik bench (zapisany przez runner)\n- Model: {run.get("model")}\n'
                   f'- Czas: {when}, {run.get("seconds")} s\n\n{answer}\n')
    return True
