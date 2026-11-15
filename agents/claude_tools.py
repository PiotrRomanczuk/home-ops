"""claude_tools.py — tool calls, git pushes and PRs inside a Claude transcript.

tool_events() reads an assistant message's tool_use blocks: every call bumps
the per-tool counter; Bash, edits, subagents, skills and MCP calls also become
claude_events (keyed by the tool_use id, so a re-read never duplicates them).
git_events() and pr_event() turn Claude Code's gitOperation / pr-link records
into pushes and PRs.
"""
from __future__ import annotations

from typing import Any

from claude_parts import event

EDIT_TOOLS = ('Edit', 'Write', 'MultiEdit', 'NotebookEdit')
AGENT_TOOLS = ('Agent', 'Task')


def _bump(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def tool_events(st: dict[str, Any], content: Any, ts: str, agent: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for b in content if isinstance(content, list) else []:
        if not isinstance(b, dict) or b.get('type') != 'tool_use' or not b.get('id'):
            continue
        name, tid = str(b.get('name') or '?'), b['id']
        inp = b.get('input') if isinstance(b.get('input'), dict) else {}
        st['tool_calls_n'] += 1
        _bump(st['tools'], name)
        if name.startswith('mcp__'):
            server = name.split('__')[1] if name.count('__') >= 2 else name
            _bump(st['mcp'], server)
            out.append(event(st, tid, ts, 'mcp', name, agent=agent))
        elif name == 'Bash':
            out.append(event(st, tid, ts, 'bash', str(inp.get('command') or ''), agent=agent,
                             description=inp.get('description'), background=inp.get('run_in_background')))
        elif name in EDIT_TOOLS:
            path = str(inp.get('file_path') or inp.get('notebook_path') or '')
            if path:
                if path in st['files_edited']:
                    st['files_edited'].remove(path)
                st['files_edited'].append(path)
                out.append(event(st, tid, ts, 'edit', path, agent=agent, tool=name))
        elif name in AGENT_TOOLS:
            kind = str(inp.get('subagent_type') or 'general-purpose')
            _bump(st['subagents'], kind)
            out.append(event(st, tid, ts, 'agent', str(inp.get('description') or ''), agent=agent, type=kind))
        elif name == 'Skill' and inp.get('skill'):
            _bump(st['skills'], str(inp['skill']))
            out.append(event(st, tid, ts, 'skill', str(inp['skill']), agent=agent))
    return out


def pr_event(st: dict[str, Any], url: Any, number: Any, repo: Any, ts: Any) -> list[dict[str, Any]]:
    """First sighting of a PR URL in this session → one 'pr' event."""
    if not url or not ts or any(p['url'] == url for p in st['prs']):
        return []
    num = int(number) if str(number).isdigit() else None
    st['prs'].append({'url': url, 'number': num, 'repo': repo})
    return [event(st, f'pr:{url}', ts, 'pr', str(url), number=num, repo=repo)]


def git_events(st: dict[str, Any], git: dict[str, Any], uuid: str, ts: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    push = git.get('push') if isinstance(git.get('push'), dict) else None
    if push and push.get('branch'):
        if push['branch'] not in st['pushes']:
            st['pushes'].append(push['branch'])
        out.append(event(st, f'git:{uuid}', ts, 'git', f'push {push["branch"]}'))
    pr = git.get('pr') if isinstance(git.get('pr'), dict) else None
    if pr and pr.get('url'):
        out += pr_event(st, pr['url'], pr.get('number'), None, ts)
    return out
