"""storage_md — parse the vault storage register (one note per place in
2-Obszary/mapy/miejsca/) into JSON-able dicts that planner-sync POSTs to
/api/storage/sync.

Created 2026-11-12. Contract: docs/adr/2026-11-12-storage-places.md.

Frontmatter is flat YAML, written by the vault template or by hand. Values
are passed through as they are and validated server-side
(ingest/src/storage-model.ts), so a typo in a status shows up as a rejected
row in the sync log instead of being silently guessed here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PLACES_DIR = '2-Obszary/mapy/miejsca'
FIELDS = (
    'nazwa', 'gdzie', 'sciezka', 'rola', 'stan', 'porzadek', 'backup',
    'sprawdzone', 'test_odtworzenia', 'sprawdzenie', 'problem',
)

_FRONTMATTER_RE = re.compile(r'^---\n(.*?)\n---(?:\n|$)', re.DOTALL)
_INT_RE = re.compile(r'-?\d+')
_COMMENT_RE = re.compile(r'(^|\s+)#.*$')
_PREFIX_RE = re.compile(r'^(\d+)-.*\.md$')


def _value(raw: str) -> Any:
    """One YAML scalar: double-quoted (JSON escapes), single-quoted, int or bare text
    (a trailing ` # comment` is cut off bare text only)."""
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw[1:-1]
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1].replace("''", "'")
    raw = _COMMENT_RE.sub('', raw)
    if _INT_RE.fullmatch(raw):
        return int(raw)
    return raw


def parse_frontmatter(text: str) -> dict[str, Any] | None:
    m = _FRONTMATTER_RE.match(text.lstrip('\ufeff').replace('\r\n', '\n'))
    if not m:
        return None
    out: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith('#') or ':' not in line:
            continue
        key, _, val = line.partition(':')
        out[key.strip()] = _value(val)
    return out


def _place_id(fm: dict[str, Any], note_path: str) -> Any:
    """`id` from frontmatter (digit strings become int); the file-name prefix when it is missing."""
    raw = fm.get('id')
    if isinstance(raw, str) and raw.strip().isdigit():
        return int(raw.strip())
    if raw is None or raw == '':
        m = _PREFIX_RE.match(Path(note_path).name)
        return int(m.group(1)) if m else None
    return raw


def parse_place(text: str, note_path: str) -> dict[str, Any] | None:
    """A place record, or None when the note is not a place (`type: miejsce`)."""
    fm = parse_frontmatter(text)
    if not fm or fm.get('type') != 'miejsce':
        return None
    rec: dict[str, Any] = {key: fm.get(key) if fm.get(key) != '' else None for key in FIELDS}
    rec.update(id=_place_id(fm, note_path), note_path=note_path,
               updated_at=fm.get('updated') or None, raw_frontmatter=fm)
    return rec


def _stub(prefix: str, note_path: str, reason: str) -> dict[str, Any]:
    """Placeholder for a numbered note that cannot be read as a place: the server rejects it
    (`nazwa required`) but keeps the row of that id, so a damaged note never erases a place."""
    return {'id': int(prefix), 'note_path': note_path, 'nazwa': None, 'unparsed': reason,
            'raw_frontmatter': {}}


def parse_places(vault_root: Path) -> list[dict[str, Any]]:
    """Every `NN-*.md` note under PLACES_DIR, sorted by file name; [] when the folder is missing.
    Files without the `NN-` prefix (README, template) are skipped; a numbered file that is
    unreadable or not a place becomes a stub (see `_stub`)."""
    base = vault_root / PLACES_DIR
    if not base.is_dir():
        return []
    places = []
    for path in sorted(base.glob('*.md')):
        m = _PREFIX_RE.match(path.name)
        if not m:
            continue
        rel = str(path.relative_to(vault_root))
        try:
            text = path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as exc:
            places.append(_stub(m.group(1), rel, f'unreadable: {type(exc).__name__}'))
            continue
        fm = parse_frontmatter(text)
        if fm is None:
            places.append(_stub(m.group(1), rel, 'no frontmatter'))
        elif fm.get('type') != 'miejsce':
            places.append(_stub(m.group(1), rel, f"type is {fm.get('type')!r}, not 'miejsce'"))
        else:
            places.append(parse_place(text, rel))
    return places
