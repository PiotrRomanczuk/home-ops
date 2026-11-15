"""Checkbox flip in a Now/Next/Later section of a project note (pure text).

Split out of planner-sync.py (UI toggle → markdown writeback).
"""
from __future__ import annotations

import re

TOGGLE_LINE_RE = re.compile(r'^(\s*[-*]\s+\[)([ xX])(\]\s+)(.+?)(\s*)$')


def flip_task_in_section(text: str, section: str, idx: int, done: bool,
                         task_text: str | None = None,
                         idx_fallback: bool = True) -> str | None:
    """Walk the markdown file. Find the `## <section>` header (case-insensitive
    match on the canonical name OR a "<Name> — ..." variant). Inside that
    section, flip the checkbox line whose text equals `task_text`; when there
    is no text anchor (or no match — e.g. the task was reworded since the UI
    rendered), fall back to the Nth `- [ ]` / `- [x]` line — unless
    `idx_fallback` is False (the caller knows the text should have matched, so
    a stale index would flip an unrelated line). Return the modified text, or
    None if the task wasn't resolvable."""
    target = section.lower()
    lines = text.split('\n')
    in_section = False
    candidates: list[tuple[int, re.Match[str]]] = []
    for i, raw in enumerate(lines):
        header = re.match(r'^##\s+(.+?)\s*$', raw)
        if header:
            name = header.group(1).strip().lower()
            # Match 'now' / 'next' / 'later' or 'now — ...' variants
            canonical = name.split(' ')[0] if name else ''
            in_section = canonical == target or (target == 'pain' and name.startswith('pain'))
            continue
        if not in_section:
            continue
        m = TOGGLE_LINE_RE.match(raw)
        if m:
            candidates.append((i, m))

    chosen: tuple[int, re.Match[str]] | None = None
    if task_text:
        chosen = next(((i, m) for i, m in candidates if m.group(4).strip() == task_text), None)
    if chosen is None and idx_fallback and 0 <= idx < len(candidates):
        chosen = candidates[idx]
    if chosen is None:
        return None
    i, m = chosen
    new_marker = 'x' if done else ' '
    lines[i] = f'{m.group(1)}{new_marker}{m.group(3)}{m.group(4)}{m.group(5)}'
    return '\n'.join(lines)
