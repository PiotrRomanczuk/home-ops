"""vault_processes — BPMN process notes for the project map ("Mapa" tab).

A process is a vault note with `type: process` and a BPMN 2.0 file next to it
(`2-Obszary/mapy/procesy/<slug>.md` + `<slug>.bpmn`). Frontmatter: `process`
(slug), `trigger`, `schedule`, `summary`, `projects` (wikilinks — one per
lane) and `bpmn` (file name). Lane names in the diagram are project slugs or
external nodes; a mismatch with `projects:` is reported as a warning, not an
error, so a half-edited diagram still shows up.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from vault_parse import as_list, parse_frontmatter

FRONTMATTER_RE = re.compile(r'^---\n(.*?)\n---\n', re.DOTALL)
_TITLE_RE = re.compile(r'^# +(.+?)\s*$', re.MULTILINE)
_BPMN_LANE = '{http://www.omg.org/spec/BPMN/20100524/MODEL}lane'
MAX_BPMN_BYTES = 512 * 1024


def bpmn_lanes(xml_text: str) -> list[str]:
    """Lane names in document order (lane id when a lane has no name)."""
    root = ET.fromstring(xml_text)
    return [(lane.get('name') or lane.get('id') or '').strip() for lane in root.iter(_BPMN_LANE)]


def _read_bpmn(path: Path, warnings: list[str]) -> tuple[str | None, str | None, list[str]]:
    try:
        raw = path.read_bytes()
    except OSError:
        warnings.append(f'missing diagram {path.name}')
        return None, None, []
    if len(raw) > MAX_BPMN_BYTES:
        warnings.append(f'diagram {path.name} over {MAX_BPMN_BYTES // 1024} KB, skipped')
        return None, None, []
    text = raw.decode('utf-8', errors='replace')
    digest = hashlib.sha256(raw).hexdigest()
    try:
        return text, digest, bpmn_lanes(text)
    except ET.ParseError as e:
        warnings.append(f'diagram {path.name} is not valid XML: {e}')
        return text, digest, []


def _lane_warnings(lanes: list[str], projects: list[str]) -> list[str]:
    lane_set = {x.lower() for x in lanes}
    proj_set = {x.lower() for x in projects}
    out = []
    stray = [x for x in lanes if x.lower() not in proj_set]
    unused = [x for x in projects if x.lower() not in lane_set]
    if stray:
        out.append('lanes missing from projects: ' + ', '.join(stray))
    if unused and lanes:
        out.append('projects without a lane: ' + ', '.join(unused))
    return out


def parse_process_file(path: Path, vault_root: Path) -> dict[str, Any] | None:
    """Process record, or None when the note isn't a process note."""
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    fm = parse_frontmatter(m.group(1))
    if fm.get('type') != 'process':
        return None
    title_m = _TITLE_RE.search(text[m.end():])
    projects = as_list(fm.get('projects'))
    warnings: list[str] = []
    # Name only: a `bpmn:` value can't point outside the note's folder.
    bpmn_name = Path(str(fm.get('bpmn') or f'{path.stem}.bpmn')).name
    xml, digest, lanes = _read_bpmn(path.parent / bpmn_name, warnings)
    warnings += _lane_warnings(lanes, projects)
    slug = str(fm.get('process') or path.stem)
    return {
        'slug': slug,
        'title': title_m.group(1).strip() if title_m else slug,
        'trigger': str(fm.get('trigger') or '') or None,
        'schedule': str(fm.get('schedule') or '') or None,
        'summary': str(fm.get('summary') or '') or None,
        'projects': projects,
        'lanes': lanes,
        'bpmn_xml': xml,
        'bpmn_hash': digest,
        'path': str(path.relative_to(vault_root)),
        'warnings': warnings,
    }


def _is_process_note(path: Path) -> bool:
    try:
        head = path.read_text(encoding='utf-8')[:2000]
    except (OSError, UnicodeDecodeError):
        return False
    m = FRONTMATTER_RE.match(head)
    return bool(m) and parse_frontmatter(m.group(1)).get('type') == 'process'


def find_processes(vault_root: Path, dirs: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """All process notes under `dirs` → (records, problems). First slug wins."""
    found: set[Path] = set()
    for rel in dirs:
        base = vault_root / rel
        if base.is_dir():
            found.update(base.rglob('*.md'))
    records: list[dict[str, Any]] = []
    problems: list[str] = []
    seen: set[str] = set()
    for path in sorted(p for p in found if _is_process_note(p)):
        rec = parse_process_file(path, vault_root)
        if rec is None:
            problems.append(f'unreadable process note {path.name}')
        elif rec['slug'] in seen:
            problems.append(f'duplicate process slug "{rec["slug"]}" — ignoring {path.name}')
        else:
            seen.add(rec['slug'])
            records.append(rec)
    return records, problems
