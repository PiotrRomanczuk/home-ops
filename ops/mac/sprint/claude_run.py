"""claude_run.py — one task through headless Claude Code.

Fresh session in the task's cwd (or `--resume <session>` when the task carries `resume:` after a limit,
with a "continue where you stopped" prompt), the task's model and effort, rules.md appended to the system prompt,
no MCP servers, permission mode auto with nobody to answer (what would ask is denied). `local:<model>` runs the
same harness against Ollama's Anthropic API (no subscription use) and, for its duration, names this process in
STATE/gpu/borrow so the GPU supervisor pauses its shards.

Hard limit: the run is its own process group (start_new_session). At `max_minutes` (for `local:*` at most the
config's `local.max_minutes`) the whole group gets SIGTERM, ten seconds later SIGKILL. On TERM `claude` ends its
own Bash tool shells, so normally nothing is left; after the KILL (a hung `claude`) the tool's shells, which sit
outside the group, may survive. A worktree the run left behind is named in
`res.orphan_worktree`, never removed here (it may hold unpushed commits).

Its own group also takes the run out of the launchd job's group, so the job's stop no longer reaches it:
run_groups.py keeps track of every live group and ends them when the runner stops.

What stops a worker from merging, ssh-ing or editing the runner's config: the PreToolUse hook
~/.claude/hooks/guard-bash.py (outside this repo, loaded through ~/.claude/settings.json) AND the
`--disallowedTools` list in deny_rules.py, which holds when that hook is missing. Everything else in rules.md is text.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import run_groups as g
from deny_rules import denied

HERE = Path(__file__).resolve().parent
KEEP = 64 * 1024  # stderr and unparsable stdout are kept up to this many characters


def command(claude: str, task: dict[str, Any], model: str, state: Path, vault: Path) -> list[str]:
    tid, session = task['id'], str(task.get('resume') or '')
    head = (f'Kontynuuj zadanie {tid} od miejsca przerwania (limit albo przerwany przebieg). Najpierw sprawdź, '
            'co już zrobiłeś (worktree, branch, commity, PR, plik wyniku), i nie powtarzaj tego.') if session else task['body']
    prompt = f'{head}\n\nID zadania: {tid}. Wynik zapisz w {state}/results/{tid}.md.'
    return [claude, '-p', prompt, *(['--resume', session] if session else []),
            '--disallowedTools', *denied(state),
            '--model', model.split('local:', 1)[-1], '--effort', str(task.get('effort') or 'medium'),
            '--permission-mode', 'auto', '--permission-prompts', 'none', '--output-format', 'json',
            '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--no-chrome',
            '--append-system-prompt', (HERE / 'rules.md').read_text(),
            '--add-dir', str(state), str(vault), '-n', f'sprint:{task["id"]}']


def run(claude: str, task: dict[str, Any], model: str, state: Path, vault: Path, ollama: str,
        timeout: float | None = None, grace: float = g.GRACE_S, local_minutes: float = 20) -> dict[str, Any]:
    local = model.startswith('local:')
    minutes = min(task['max_minutes'], local_minutes) if local else task['max_minutes']
    env = dict(os.environ)
    if local:  # Ollama speaks the Anthropic API; the token is required but ignored
        env.update(ANTHROPIC_BASE_URL=ollama, ANTHROPIC_AUTH_TOKEN='ollama', ANTHROPIC_API_KEY='')
    borrow = state / 'gpu' / 'borrow'
    if local:
        borrow.parent.mkdir(exist_ok=True)
        borrow.write_text(str(os.getpid()))
    cwd = Path(str(task.get('cwd') or '~')).expanduser()
    cwd = cwd if cwd.is_dir() else Path.home()
    t0, timed_out, p = time.time(), False, None
    try:
        p = g.start(command(claude, task, model, state, vault), task, cwd=cwd, env=env)
        if p is None:  # the runner is stopping: nothing started, the task goes back as interrupted
            out, err, rc = '', 'runner stopping\n', -15
        else:
            try:
                out, err = p.communicate(timeout=timeout or minutes * 60)
                rc = p.returncode
            except subprocess.TimeoutExpired:
                (out, err), rc, timed_out = g.stop_group(p, grace), 124, True
    finally:
        g.untrack(p, task)
        if local:
            borrow.unlink(missing_ok=True)
    try:
        res = json.loads(out)
    except ValueError:
        res = None
    if not isinstance(res, dict):
        res = {'result': (out or '')[-KEEP:], 'is_error': True}
    worktree = cwd / '.claude' / 'worktrees' / f'sprint-{task["id"]}'
    if timed_out and worktree.exists():
        res['orphan_worktree'] = str(worktree)
    return {'id': task['id'], 'model': model, 'rc': rc, 'stderr': ('timeout\n' if timed_out else '') + (err or '')[-KEEP:],
            'started': t0, 'seconds': round(time.time() - t0), 'resumed': bool(task.get('resume')), 'res': res}
