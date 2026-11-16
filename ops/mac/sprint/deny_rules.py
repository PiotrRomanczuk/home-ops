"""deny_rules.py — the `--disallowedTools` list of every headless run (claude_run.command).

rules.md is text. The only hard stop behind it is the PreToolUse hook ~/.claude/hooks/guard-bash.py (merge,
approve, prod, sudo), and that hook lives outside this repo and reaches the session through
~/.claude/settings.json: if its symlink or that file breaks, nothing but rules.md forbids those commands.
These deny rules repeat the worst of them in a form the CLI enforces without the hook:
merging and approving PRs, ssh, force-push, writes under ~/.claude, and the runner's own config.json
(budget caps) and STOP file. Edit rules cover Write too, so both tools are listed anyway.
"""
from __future__ import annotations

from pathlib import Path

BASH = ('gh pr merge', 'gh pr review --approve', 'ssh', 'git push --force', 'git push -f')


def pattern(path: Path) -> str:
    """Edit/Write rule path: `~/…` under the home directory, `//…` for any other absolute path."""
    path = path.expanduser()
    try:
        return f'~/{path.relative_to(Path.home())}'
    except ValueError:
        return f'/{path}'


def denied(state: Path) -> list[str]:
    guarded = [f'{pattern(Path("~/.claude"))}/**', pattern(state / 'config.json'), pattern(state / 'STOP')]
    return [*(f'Bash({prefix}:*)' for prefix in BASH), *(f'{tool}({g})' for g in guarded for tool in ('Edit', 'Write'))]
