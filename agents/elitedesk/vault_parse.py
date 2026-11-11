"""vault_parse — the small YAML subset the planner vault's frontmatter uses.

Flat `key: value` pairs (quotes stripped, bare ints cast) plus lists, which
the project map needs for its relation keys (`depends_on`, `feeds`, `hosts`,
`projects`):

    hosts: [mac, uwh]                      flow list
    depends_on: ["[[home-ops]]", "[[ollama]]"]
    feeds:                                 block list (Obsidian's Properties
      - "[[vectordigital]]"                editor writes this form)

List items that are wikilinks come back as their target: `[[1-Projekty/job-radar|JR]]`
→ `job-radar`. Scalars are left exactly as before (a quoted `"[[x]]"` stays
a string) so existing readers of raw_frontmatter don't change. No nesting,
no multi-line strings — anything else is read as a plain string.
"""
from __future__ import annotations

import re
from typing import Any

_WIKILINK_RE = re.compile(r'^\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]$')
_BLOCK_ITEM_RE = re.compile(r'^\s*-\s+(.*)$')


def _unquote(val: str) -> str:
    if len(val) >= 2 and val[0] == val[-1] and val[0] in '"\'':
        return val[1:-1]
    return val


def link_target(item: str) -> str:
    """`[[path/to/note|alias]]` → `note`; anything else unchanged (unquoted)."""
    item = _unquote(item.strip())
    m = _WIKILINK_RE.match(item)
    if not m:
        return item
    target = m.group(1).strip().rsplit('/', 1)[-1]
    return target[:-3] if target.endswith('.md') else target


def _split_flow(inner: str) -> list[str]:
    """Split `a, "b, c", [[d]]` on top-level commas (quotes/brackets respected)."""
    items: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    depth = 0
    for ch in inner:
        if quote:
            quote = None if ch == quote else quote
        elif ch in '"\'':
            quote = ch
        elif ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
        elif ch == ',' and depth == 0:
            items.append(''.join(buf))
            buf = []
            continue
        buf.append(ch)
    items.append(''.join(buf))
    return [link_target(i) for i in items if i.strip()]


def _scalar(val: str) -> Any:
    val = _unquote(val)
    if val.isdigit() or (val.startswith('-') and val[1:].isdigit()):
        return int(val)
    return val


def _is_flow_list(val: str) -> bool:
    # `[[x]]` alone is a wikilink scalar, not a one-item list.
    return val.startswith('[') and val.endswith(']') and not _WIKILINK_RE.match(val)


def parse_frontmatter(block: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    pending: str | None = None  # key whose value was empty — may open a block list
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith('#'):
            continue
        item = _BLOCK_ITEM_RE.match(line)
        if item and pending is not None:
            if not isinstance(out[pending], list):
                out[pending] = []
            value = item.group(1)
            if value[:1] not in '"\'':
                value = re.sub(r'\s+#.*$', '', value)  # trailing YAML comment
            out[pending].append(link_target(value))
            continue
        pending = None
        if ':' not in line:
            continue
        key, _, val = line.partition(':')
        key, val = key.strip(), val.strip()
        if not val:
            out[key] = ''
            pending = key
        elif _is_flow_list(val):
            out[key] = _split_flow(val[1:-1])
        else:
            out[key] = _scalar(val)
    return out


def as_list(value: Any) -> list[str]:
    """A frontmatter value read as a list of strings ('' / None → [])."""
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [link_target(value)]
    return []
