"""Pure parsing for brief-pull: a daily-brief markdown file → POST /api/briefs body.

File contract (docs/adr/2026-10-17-daily-briefs.md):

    ---
    date: 2026-10-17
    slot: morning            # morning | evening
    generated_at: 2026-10-17T06:03:12+02:00
    title: "Sobota — spokojny dzień"
    sources: [calendar, planner]
    ---
    ## Kalendarz
    - …

Only the flat subset of YAML the routine writes is supported (scalars, a flow
list `[a, b]` or a block list of `- item` lines) — stdlib only, no PyYAML.
"""
from __future__ import annotations

import re
from typing import Any

NAME_RE = re.compile(r'^briefs/(\d{4}-\d{2}-\d{2})-(morning|evening)\.md$')
MAX_BODY = 20_000


class BriefError(ValueError):
    """The file breaks the contract; skip it and report."""


def _scalar(raw: str) -> str:
    v = raw.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
        return v[1:-1]
    return v.split(' #', 1)[0].strip()


def _flow_list(raw: str) -> list[str]:
    inner = raw.strip()[1:-1]
    return [_scalar(x) for x in inner.split(',') if x.strip()]


def parse_frontmatter(lines: list[str]) -> dict[str, Any]:
    """Parse `key: value` lines (plus block lists) into a dict."""
    out: dict[str, Any] = {}
    key: str | None = None
    for line in lines:
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        item = re.match(r'^\s+-\s+(.*)$', line) or re.match(r'^-\s+(.*)$', line)
        if item and key is not None and isinstance(out.get(key), list):
            out[key].append(_scalar(item.group(1)))
            continue
        m = re.match(r'^([A-Za-z_][\w-]*)\s*:\s*(.*)$', line)
        if not m:
            raise BriefError(f'unreadable frontmatter line: {line[:60]!r}')
        key, val = m.group(1), m.group(2).strip()
        if val.startswith('[') and val.endswith(']'):
            out[key] = _flow_list(val)
        elif val == '':
            out[key] = []  # a block list follows (or the key is empty)
        else:
            out[key] = _scalar(val)
    return out


def split_file(text: str) -> tuple[dict[str, Any], str]:
    """Split `---` frontmatter from the markdown body."""
    lines = text.lstrip('﻿').splitlines()
    if not lines or lines[0].strip() != '---':
        raise BriefError('missing frontmatter (file must start with ---)')
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == '---')
    except StopIteration:
        raise BriefError('frontmatter not closed with ---') from None
    return parse_frontmatter(lines[1:end]), '\n'.join(lines[end + 1:]).strip()


def brief_payload(rel_path: str, text: str) -> dict[str, Any]:
    """Build the POST /api/briefs body; the filename and frontmatter must agree."""
    m = NAME_RE.match(rel_path)
    if not m:
        raise BriefError('name must be briefs/YYYY-MM-DD-morning|evening.md')
    fm, body = split_file(text)
    date, slot = str(fm.get('date') or m.group(1)), str(fm.get('slot') or m.group(2))
    if (date, slot) != (m.group(1), m.group(2)):
        raise BriefError(f'frontmatter {date}/{slot} does not match the filename')
    if not body:
        raise BriefError('empty body')
    if len(body) > MAX_BODY:
        raise BriefError(f'body over {MAX_BODY} chars')
    sources = fm.get('sources') or []
    if not isinstance(sources, list):
        sources = [str(sources)]
    title = fm.get('title')
    return {
        'date': date,
        'slot': slot,
        'title': str(title) if title else None,
        'body_md': body,
        'sources': [str(s) for s in sources][:20],
        'generated_at': str(fm['generated_at']) if fm.get('generated_at') else None,
    }
