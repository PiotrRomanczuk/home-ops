"""gaps_parse — open gap IDs from a repo's blueprint docs (pure, no network).

Blueprint convention (global documentation rules): every gap has a stable ID
(`LES-1`, `LN-5`, `CORE-3`) defined once in a domain doc's "Gaps & planned
work" section; `90-roadmap.md` orders them; a shipped gap is deleted, leaving
at most an `_Shipped YYYY-MM-DD: …_` line. Repos write the definition four
ways, all accepted:

    ### SKL-1 · Student can reach …            heading (strummy)
    - **LN-5 Raport tygodniowy …**             bold bullet (lesson-notes, daily-news, monitor-manager)
    | BLD-1 | Import builds … |                 table row (d4-build-agent, 90-roadmap)
    | CORE-1 | Jeden przepływ … |               table row (social-hub "Luki")

Only gap sections count (an h2 mentioning gaps/luki/planned work), plus the
whole roadmap. Testing strategy, runbooks and audits (91+) are skipped. IDs on
`_Shipped …_` lines or struck through (`~~X-1~~`) are treated as done.
"""
from __future__ import annotations

import re

ID = r'[A-Z][A-Z0-9]{1,5}-\d{1,3}'
_ID_RE = re.compile(rf'\b({ID})\b')
_DEFINITIONS = [
    re.compile(rf'^#{{3,4}}\s+(?:~~)?({ID})\b'),
    re.compile(rf'^\s*[-*]\s+(?:\[[ xX]\]\s+)?(?:\*\*|__)?(?:~~)?({ID})\b'),
    re.compile(rf'^\|\s*(?:\*\*)?(?:~~)?({ID})\s*(?:~~)?(?:\*\*)?\s*\|'),
]
_STRUCK_RE = re.compile(rf'~~\s*({ID})\b')
_SHIPPED_RE = re.compile(r'^\s*_?\s*shipped\b', re.IGNORECASE)
_H2_RE = re.compile(r'^##\s+(.*)$')
_GAP_SECTION_RE = re.compile(r'gap|luk|planned work', re.IGNORECASE)
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


def parse_gaps(docs: dict[str, str]) -> dict[str, object]:
    """{file name: markdown} → {count, ids, by_prefix}; ids sorted naturally."""
    defined: set[str] = set()
    done: set[str] = set()
    for name, text in docs.items():
        if not counts_as_blueprint(name):
            continue
        shipped_para = False  # an `_Shipped …_` note can wrap over several lines
        for line in _gap_lines(name, text):
            shipped_para = bool(line.strip()) and (shipped_para or bool(_SHIPPED_RE.match(line)))
            if shipped_para:
                done.update(_ID_RE.findall(line))
                continue
            done.update(_STRUCK_RE.findall(line))
            for rx in _DEFINITIONS:
                m = rx.match(line)
                if m:
                    defined.add(m.group(1))
                    break
    open_ids = sorted(defined - done, key=lambda i: (i.split('-')[0], int(i.split('-')[1])))
    by_prefix: dict[str, int] = {}
    for gap_id in open_ids:
        prefix = gap_id.split('-')[0]
        by_prefix[prefix] = by_prefix.get(prefix, 0) + 1
    return {'count': len(open_ids), 'ids': open_ids, 'by_prefix': by_prefix}
