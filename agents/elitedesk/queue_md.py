"""queue_md — parse the planner vault's QUEUE.md (the agent queue) into a
JSON-able dict that planner-sync POSTs to /api/queue/sync.

Created 2026-10-20. Contract: docs/adr/2026-10-20-queue-state.md.

The file is hand-edited markdown, so every rule here is tolerant: a line
that does not match is kept as plain text, never dropped. Task line shape
(vault rubric §8): ``- [ ] 🔴 M ⛓ [[projects/Strummy/Strummy|Strummy]] STR-1
treść · fable → sonnet · start 2026-10-19`` with optional indented
continuation lines (the brief).
"""
from __future__ import annotations

import re
from typing import Any

CLASSES = {'🔴': 'risk', '💰': 'money', '🎯': 'focus', '🧹': 'clean', '💡': 'idea'}
FLAGS = {'⛓': 'unblocks', '🖥': 'local', '⏸': 'paused', '🧪': 'experiment'}
SECTIONS = (
    ('W toku', 'in_progress'), ('Kolejka', 'queue'), ('Tor lokalny', 'local'),
    ('Czeka na Piotra', 'waiting'), ('Zrobione', 'done'),
)
MAX_TICKETS = 50

_SECTION_RE = re.compile(r'^## +(.+?)\s*$', re.MULTILINE)
_TASK_RE = re.compile(r'^\s*[-*]\s+\[([ xX])\]\s+(.*)$')
_DATE_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})\s+')
_WIKI_RE = re.compile(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]')
_ID_RE = re.compile(r'^([A-Z]{2,5}-\d{1,4})\b\s*')
_MODEL_RE = re.compile(r'^([\w.:-]+)\s*→\s*([\w.:-]+(?:\s*\([^)]*\))?)$')
_HOURS_RE = re.compile(r'(?<![\w/])(\d+(?:[.,]\d+)?)\s*h\b')
_MINUTES_RE = re.compile(r'(?<![\w/])(\d+)\s*min\b')
_SPAN_RE = re.compile(r'(\d{4}-\d{2}-\d{2})\s*(?:→|->|–|-)\s*(\d{4}-\d{2}-\d{2})')
_CAPACITY_RE = re.compile(r'pojemno[śs][ćc]\s*~?\s*(\d+(?:[.,]\d+)?)\s*h')


def _unwiki(text: str) -> str:
    return _WIKI_RE.sub(lambda m: (m.group(2) or m.group(1)).strip(), text)


def _num(raw: str) -> float:
    return float(raw.replace(',', '.'))


def _hours(text: str) -> float | None:
    """'~1 h' → 1.0, '30 min' → 0.5; None when the line names no duration."""
    h = _HOURS_RE.search(text)
    m = _MINUTES_RE.search(text)
    if not h and not m:
        return None
    return (_num(h.group(1)) if h else 0.0) + (int(m.group(1)) / 60 if m else 0.0)


def _header(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {'window_from': None, 'window_to': None, 'capacity_hours': None,
                           'focus': None, 'rules': None}
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('Okno:'):
            span = _SPAN_RE.search(s)
            if span:
                out['window_from'], out['window_to'] = span.group(1), span.group(2)
            cap = _CAPACITY_RE.search(s)
            if cap:
                out['capacity_hours'] = _num(cap.group(1))
            _, _, focus = s.partition('fokus')
            out['focus'] = _unwiki(focus.lstrip(': ')).strip() or None
        elif s.startswith('Zasady:'):
            out['rules'] = s[len('Zasady:'):].strip() or None
    return out


def _split(body: str) -> dict[str, str]:
    heads = [(m.start(), m.end(), m.group(1).strip()) for m in _SECTION_RE.finditer(body)]
    out: dict[str, str] = {}
    for i, (_, end, name) in enumerate(heads):
        nxt = heads[i + 1][0] if i + 1 < len(heads) else len(body)
        for title, key in SECTIONS:
            if (name == title or name.startswith(title + ' ')) and key not in out:
                out[key] = body[end:nxt]
    return out


def parse_task(line: str) -> dict[str, Any] | None:
    m = _TASK_RE.match(line)
    if not m:
        return None
    rest = m.group(2).strip()
    t: dict[str, Any] = {'done': m.group(1).lower() == 'x', 'cls': None, 'size': None, 'flags': [],
                         'project': None, 'id': None, 'text': '', 'model': None, 'meta': None,
                         'brief': None, 'hours': None, 'date': None}
    tokens = rest.split(' ')
    while tokens:  # class / size / flags / entry date, in any order
        tok = tokens[0]
        if tok in CLASSES and t['cls'] is None:
            t['cls'] = CLASSES[tok]
        elif tok in ('S', 'M', 'L', 'XL') and t['size'] is None:
            t['size'] = tok
        elif tok in FLAGS:
            t['flags'].append(FLAGS[tok])
        elif _DATE_RE.match(tok + ' ') and t['date'] is None:
            t['date'] = tok
        else:
            break
        tokens.pop(0)
    rest = ' '.join(tokens)
    w = _WIKI_RE.match(rest)
    if w:
        t['project'], rest = (w.group(2) or w.group(1).rsplit('/', 1)[-1]).strip(), rest[w.end():].lstrip()
    i = _ID_RE.match(rest)
    if i:
        t['id'], rest = i.group(1), rest[i.end():]
    parts = [p.strip() for p in rest.split(' · ')]
    t['text'] = _unwiki(parts[0]).replace('**', '').strip()
    extras = []
    for p in parts[1:]:
        if t['model'] is None and _MODEL_RE.match(p):
            t['model'] = p
        else:
            extras.append(_unwiki(p))
    t['meta'] = ' · '.join(extras) or None
    t['hours'] = _hours(rest)
    return t


def _tickets(section: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in section.splitlines():
        task = parse_task(raw)
        if task:
            if len(out) < MAX_TICKETS:
                out.append(task)
        elif out and raw.startswith((' ', '\t')) and raw.strip():
            out[-1]['brief'] = ((out[-1]['brief'] or '') + ' ' + _unwiki(raw.strip())).strip()
    return out


def parse_queue_md(text: str) -> dict[str, Any]:
    """Whole file → header fields, sections of tickets, and a small summary."""
    sections = {key: _tickets(body) for key, body in _split(text).items()}
    done = sections.get('done', [])
    summary = {key: len(v) for key, v in sections.items()}
    summary['done_hours'] = round(sum(t['hours'] or 0.0 for t in done), 2)
    return {**_header(text), 'sections': sections, 'summary': summary}
