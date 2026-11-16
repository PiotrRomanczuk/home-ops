"""gaps_parse — open gap IDs from a repo's blueprint docs (pure, no network).

Blueprint convention (global documentation rules): every gap has a stable ID
(`LES-1`, `LN-5`, `CORE-3`) defined once in a domain doc's "Gaps & planned
work" section; `90-roadmap.md` orders them; a shipped gap is deleted, leaving
at most an `_Shipped YYYY-MM-DD: …_` line. Repos write the definition five
ways, all accepted:

    ### SKL-1 · Student can reach …            heading (strummy)
    - **LN-5 Raport tygodniowy …**             bold bullet (lesson-notes, daily-news, monitor-manager)
    | BLD-1 | Import builds … |                 table row (d4-build-agent, 90-roadmap)
    | CORE-1 | Jeden przepływ … |               table row (social-hub "Luki")
    1. SRC-1 — Źródła …                        numbered list (coupon-ocr "90 · Roadmap")

Only gap sections count (an h2 mentioning gaps/luki/planned work), plus the
whole roadmap. Testing strategy, runbooks and audits (91+) are skipped. IDs on
`_Shipped …_` notes (outside parentheses) or struck through (`~~X-1~~`) are treated as done.
"""
from __future__ import annotations

import re

ID = r'[A-Z][A-Z0-9]{1,5}-\d{1,3}'
_ID_RE = re.compile(rf'\b({ID})\b')
_DEFINITIONS = [
    re.compile(rf'^#{{3,4}}\s+(?:~~)?({ID})\b'),
    re.compile(rf'^\s*[-*]\s+(?:\[[ xX]\]\s+)?(?:\*\*|__)?(?:~~)?({ID})\b'),
    re.compile(rf'^\|\s*(?:\*\*)?(?:~~)?({ID})\s*(?:~~)?(?:\*\*)?\s*\|'),
    re.compile(rf'^\s*\d+[.)]\s+(?:\*\*|__)?(?:~~)?({ID})\b'),
]
# Technical terms that look like IDs (`SHA-256`, `UTF-8`) at the start of a bullet.
_NOT_GAP = {'SHA', 'UTF', 'ISO', 'RFC', 'ES', 'TLS', 'HTTP'}
_PAREN_RE = re.compile(r'\([^)]*\)', re.DOTALL)
_STRUCK_RE = re.compile(rf'~~\s*({ID})\b')
_SHIPPED_RE = re.compile(r'^\s*_?\s*shipped\b', re.IGNORECASE)
_H2_RE = re.compile(r'^##\s+(.*)$')
_GAP_SECTION_RE = re.compile(r'gap|luk|planned work|roadmap', re.IGNORECASE)
_DOC_RE = re.compile(r'^(\d{2})-[\w.-]+\.md$')


def counts_as_blueprint(name: str) -> bool:
    """`BLUEPRINT.md`, domain docs `NN-*.md` below 90, and `90-roadmap.md`."""
    if name == 'BLUEPRINT.md':
        return True
    m = _DOC_RE.match(name)
    return bool(m) and (int(m.group(1)) < 90 or name == '90-roadmap.md')


def _gap_lines(name: str, text: str) -> list[str]:
    if name == '90-roadmap.md':
        return text.splitlines()
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        h2 = _H2_RE.match(line)
        if h2:
            inside = bool(_GAP_SECTION_RE.search(h2.group(1)))
            continue
        if inside:
            out.append(line)
    return out


def _shipped_ids(note: str) -> list[str]:
    """IDs of a finished `_Shipped …_` note; parenthesised mentions ("depends on
    SKL-1") are references, not shipped gaps."""
    return _ID_RE.findall(_PAREN_RE.sub(' ', note))


def _definition(line: str) -> str | None:
    for rx in _DEFINITIONS:
        m = rx.match(line)
        if m and m.group(1).split('-')[0] not in _NOT_GAP:
            return m.group(1)
    return None


def parse_gaps(docs: dict[str, str]) -> dict[str, object]:
    """{file name: markdown} → {count, ids, by_prefix}; ids sorted naturally."""
    defined: set[str] = set()
    done: set[str] = set()
    for name, text in docs.items():
        if not counts_as_blueprint(name):
            continue
        note: list[str] = []  # an `_Shipped …_` note can wrap over several lines
        for line in _gap_lines(name, text) + ['']:
            gap_id = _definition(line)
            if note and (not line.strip() or gap_id):
                done.update(_shipped_ids(' '.join(note)))
                note = []
            if note or _SHIPPED_RE.match(line):
                note.append(line)
                continue
            done.update(_STRUCK_RE.findall(line))
            if gap_id:
                defined.add(gap_id)
    open_ids = sorted(defined - done, key=lambda i: (i.split('-')[0], int(i.split('-')[1])))
    by_prefix: dict[str, int] = {}
    for gap_id in open_ids:
        prefix = gap_id.split('-')[0]
        by_prefix[prefix] = by_prefix.get(prefix, 0) + 1
    return {'count': len(open_ids), 'ids': open_ids, 'by_prefix': by_prefix}
