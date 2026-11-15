"""claude_transcript.py — fold Claude Code transcript lines into a session + events.

A session's state is a plain dict (JSON-serialisable, so claude-collector can
keep it between runs and feed only the lines appended since). feed() takes one
raw JSONL line and returns the claude_events it produced; row() turns the
state into the POST /api/claude/sessions payload. Subagent transcripts feed
the same state with sidechain=True: their tools and tokens count, their user
turns are not the human's prompts.

Field facts (checked on real transcripts, Claude Code 2.1.31x):
  * a human prompt is a `user` entry with turnOrigin == 'human' (typed, queued,
    accepted suggestion, phone/desktop sdk) and text content, not tool_result;
  * one API response is split over several `assistant` lines that repeat the
    same usage → count each message.id once;
  * `api-request*` lines are raw request bodies → skipped unparsed.
"""
from __future__ import annotations

import json
from typing import Any

from claude_parts import add_tokens, cost_state, event, surface, text_of, tool_result_text
from claude_tools import git_events, pr_event, tool_events

RECENT_IDS = 64


def new_state(session_id: str) -> dict[str, Any]:
    return {
        'session_id': session_id, 'cwd': None, 'git_branch': None, 'entrypoint': None, 'version': None,
        'client_platform': None, 'bridged': False, 'title_ai': None, 'title_custom': None,
        'started_at': None, 'last_at': None, 'active_ms': 0, 'prompts_n': 0, 'tool_calls_n': 0,
        'tool_errors_n': 0, 'compactions_n': 0, 'tools': {}, 'skills': {}, 'subagents': {}, 'mcp': {},
        'tokens': {}, 'cost_usd': None, 'lines_added': None, 'lines_removed': None,
        'prs': [], 'pushes': [], 'files_edited': [], 'recent_ids': [],
    }


def feed(st: dict[str, Any], line: str, sidechain: bool = False) -> list[dict[str, Any]]:
    if line.startswith('{"type":"api-r') or not line.strip():
        return []
    try:
        d = json.loads(line)
    except json.JSONDecodeError:
        return []
    if not isinstance(d, dict):
        return []
    t = d.get('type')
    if t == 'ai-title':
        st['title_ai'] = d.get('aiTitle') or st['title_ai']
    elif t == 'custom-title':
        st['title_custom'] = d.get('customTitle') or st['title_custom']
    elif t == 'bridge-session':
        st['bridged'] = True
    elif t == 'cost-state' and not sidechain:
        cost_state(st, d)
    elif t == 'pr-link':
        return pr_event(st, d.get('prUrl'), d.get('prNumber'), d.get('prRepository'), d.get('timestamp'))
    elif t in ('user', 'assistant', 'system') and d.get('uuid') and d.get('timestamp'):
        _meta(st, d, sidechain)
        if t == 'system':
            return _system(st, d)
        if t == 'assistant':
            return _assistant(st, d, sidechain)
        return _user(st, d, sidechain)
    return []


def _meta(st: dict[str, Any], d: dict[str, Any], sidechain: bool) -> None:
    if not sidechain:
        # cwd: where the session started (a later `cd` elsewhere is not its project);
        # branch / version: the latest.
        if d.get('cwd') and not st['cwd']:
            st['cwd'] = d['cwd']
        for key, field in (('git_branch', 'gitBranch'), ('entrypoint', 'entrypoint'),
                           ('version', 'version'), ('client_platform', 'clientPlatform')):
            if d.get(field):
                st[key] = d[field]
    ts = d['timestamp']
    st['started_at'] = min(st['started_at'] or ts, ts)
    st['last_at'] = max(st['last_at'] or ts, ts)


def _assistant(st: dict[str, Any], d: dict[str, Any], sidechain: bool) -> list[dict[str, Any]]:
    msg = d.get('message') if isinstance(d.get('message'), dict) else {}
    mid = msg.get('id')
    if mid and mid not in st['recent_ids']:
        st['recent_ids'] = (st['recent_ids'] + [mid])[-RECENT_IDS:]
        add_tokens(st, msg.get('model'), msg.get('usage') or {})
    return tool_events(st, msg.get('content'), d['timestamp'], agent=d.get('agentId') if sidechain else None)


def _user(st: dict[str, Any], d: dict[str, Any], sidechain: bool) -> list[dict[str, Any]]:
    uuid, ts = d['uuid'], d['timestamp']
    msg = d.get('message') if isinstance(d.get('message'), dict) else {}
    content = msg.get('content')
    out: list[dict[str, Any]] = []
    for b in content if isinstance(content, list) else []:
        if isinstance(b, dict) and b.get('type') == 'tool_result' and b.get('is_error'):
            st['tool_errors_n'] += 1
            text = tool_result_text(b.get('content'))[:500]
            out.append(event(st, f'err:{b.get("tool_use_id") or uuid}', ts, 'error', text))
    result = d.get('toolUseResult')
    git = result.get('gitOperation') if isinstance(result, dict) else None
    if isinstance(git, dict):
        out += git_events(st, git, uuid, ts)
    text = text_of(content)
    if d.get('isCompactSummary'):
        out.append(event(st, uuid, ts, 'compact', text or ''))
    elif not sidechain and not d.get('isMeta') and d.get('turnOrigin') == 'human' and text:
        st['prompts_n'] += 1
        out.append(event(st, uuid, ts, 'prompt', text, source=d.get('promptSource')))
    return out


def _system(st: dict[str, Any], d: dict[str, Any]) -> list[dict[str, Any]]:
    sub = d.get('subtype')
    if sub == 'turn_duration' and not d.get('isSidechain'):
        st['active_ms'] += int(d.get('durationMs') or 0)
    elif sub == 'compact_boundary':
        st['compactions_n'] += 1
    elif sub == 'away_summary' and d.get('content'):
        return [event(st, d['uuid'], d['timestamp'], 'summary', str(d['content']))]
    return []


ROW_KEYS = ('session_id', 'cwd', 'git_branch', 'started_at', 'last_at', 'active_ms', 'prompts_n',
            'tool_calls_n', 'tool_errors_n', 'compactions_n', 'tools', 'skills', 'subagents', 'mcp',
            'tokens', 'cost_usd', 'lines_added', 'lines_removed', 'prs', 'pushes', 'entrypoint', 'version')


def row(st: dict[str, Any]) -> dict[str, Any] | None:
    """POST payload, or None until the session has a timestamped entry."""
    if not st['started_at']:
        return None
    out = {k: st[k] for k in ROW_KEYS}
    out['surface'] = surface(st)
    out['title'] = st['title_custom'] or st['title_ai']
    out['files_edited'] = st['files_edited'][-200:]
    return out
