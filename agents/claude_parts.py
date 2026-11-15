"""claude_parts.py — small pure helpers for claude_transcript.py.

event() builds one claude_events row (text masked and capped), text_of()
extracts a user message's plain text, add_tokens()/cost_state() fold usage
into the session state, surface() names where the session ran.
"""
from __future__ import annotations

import json
from typing import Any

from redact import redact

MAX_TEXT = 4000


def event(st: dict[str, Any], uuid: str, ts: str, kind: str, text: str, **detail: Any) -> dict[str, Any]:
    return {'session_id': st['session_id'], 'uuid': uuid, 'ts': ts, 'kind': kind,
            'text': redact(text or '')[:MAX_TEXT], 'detail': {k: v for k, v in detail.items() if v is not None}}


def text_of(content: Any) -> str | None:
    """Plain text of a user message, or None when it carries tool results."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    blocks = [b for b in content if isinstance(b, dict)]
    if any(b.get('type') == 'tool_result' for b in blocks):
        return None
    parts = [b.get('text', '') for b in blocks if b.get('type') == 'text']
    return '\n'.join(parts) if parts else None


def add_tokens(st: dict[str, Any], model: Any, usage: dict[str, Any]) -> None:
    if not isinstance(model, str) or not model or model.startswith('<'):
        return
    t = st['tokens'].setdefault(model, {'in': 0, 'out': 0, 'cache_read': 0, 'cache_write': 0, 'thinking': 0})
    t['in'] += int(usage.get('input_tokens') or 0)
    t['out'] += int(usage.get('output_tokens') or 0)
    t['cache_read'] += int(usage.get('cache_read_input_tokens') or 0)
    t['cache_write'] += int(usage.get('cache_creation_input_tokens') or 0)
    details = usage.get('output_tokens_details') or {}
    t['thinking'] += int(details.get('thinking_tokens') or 0) if isinstance(details, dict) else 0


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def cost_state(st: dict[str, Any], d: dict[str, Any]) -> None:
    """Claude Code's own running totals (written on exit/resume) — last one wins."""
    cost = _num(d.get('totalCostUSD'))
    if cost is not None:
        st['cost_usd'] = round(cost, 4)
    for key, field in (('lines_added', 'totalLinesAdded'), ('lines_removed', 'totalLinesRemoved')):
        n = _num(d.get(field))
        if n is not None:
            st[key] = int(n)


def surface(st: dict[str, Any]) -> str:
    entry, platform = st.get('entrypoint') or '', st.get('client_platform') or ''
    if entry == 'claude-desktop':
        return 'desktop'
    if entry.startswith('sdk'):
        return 'phone' if platform in ('ios', 'android') else 'headless'
    if entry == 'cli':
        return 'remote' if st.get('bridged') else 'cli'
    return 'unknown'


def tool_result_text(body: Any) -> str:
    return body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
