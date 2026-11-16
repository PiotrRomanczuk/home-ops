"""claude_run.py — one task through headless Claude Code.

Fresh session in the task's cwd (or `--resume <session>` when the task carries `resume:` after a limit,
with a "continue where you stopped" prompt), the task's model and effort, rules.md appended to the system prompt,
no MCP servers, permission mode auto with nobody to answer (what would ask is denied; the guard hook
still blocks merges and prod). `local:<model>` runs the same harness against Ollama's Anthropic API
(no subscription use) and, for its duration, names this process in STATE/gpu/borrow so the GPU
supervisor pauses its shards.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def command(claude: str, task: dict[str, Any], model: str, state: Path, vault: Path) -> list[str]:
    tid, session = task['id'], str(task.get('resume') or '')
    head = (f'Kontynuuj zadanie {tid} od miejsca przerwania (limit albo przerwany przebieg). Najpierw sprawdź, '
            'co już zrobiłeś (worktree, branch, commity, PR, plik wyniku), i nie powtarzaj tego.') if session else task['body']
    prompt = f'{head}\n\nID zadania: {tid}. Wynik zapisz w {state}/results/{tid}.md.'
    return [claude, '-p', prompt, *(['--resume', session] if session else []),
            '--model', model.split('local:', 1)[-1], '--effort', str(task.get('effort') or 'medium'),
            '--permission-mode', 'auto', '--permission-prompts', 'none', '--output-format', 'json',
            '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--no-chrome',
            '--append-system-prompt', (HERE / 'rules.md').read_text(),
            '--add-dir', str(state), str(vault), '-n', f'sprint:{task["id"]}']


def run(claude: str, task: dict[str, Any], model: str, state: Path, vault: Path, ollama: str) -> dict[str, Any]:
    local = model.startswith('local:')
    env = dict(os.environ)
    if local:  # Ollama speaks the Anthropic API; the token is required but ignored
        env.update(ANTHROPIC_BASE_URL=ollama, ANTHROPIC_AUTH_TOKEN='ollama', ANTHROPIC_API_KEY='')
    borrow = state / 'gpu' / 'borrow'
    if local:
        borrow.parent.mkdir(exist_ok=True)
        borrow.write_text(str(os.getpid()))
    cwd = Path(str(task.get('cwd') or '~')).expanduser()
    t0 = time.time()
    try:
        p = subprocess.run(command(claude, task, model, state, vault), cwd=cwd if cwd.is_dir() else Path.home(),
                           env=env, capture_output=True, text=True, timeout=task['max_minutes'] * 60)
        out, rc, err = p.stdout, p.returncode, p.stderr[-2000:]
    except subprocess.TimeoutExpired as e:
        out, rc, err = (e.stdout or b'').decode(errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or ''), 124, 'timeout'
    finally:
        if local:
            borrow.unlink(missing_ok=True)
    try:
        res = json.loads(out)
    except ValueError:
        res = {'result': out[-2000:], 'is_error': True}
    return {'id': task['id'], 'model': model, 'rc': rc, 'stderr': err, 'started': t0, 'seconds': round(time.time() - t0),
            'resumed': bool(task.get('resume')), 'res': res}
