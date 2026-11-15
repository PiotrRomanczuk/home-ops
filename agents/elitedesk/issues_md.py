"""GitHub Issues → Now/Next/Later blocks in a vault project note.

Pilot since 2026-11-14 (Strummy). A project note opts in with frontmatter
`zadania: github` + `repo:`. Open issues labelled plan/now|next|later are
rendered as planner-rubric task lines between START/END markers inside each
section; lines outside the markers (confidential tasks kept only in the
vault) are never touched. Pure functions; HTTP lives in issues_gh.py.
"""
from __future__ import annotations

import re
from typing import Any

START = '<!-- github-issues:start — generowane z GitHub Issues przez planner-sync, nie edytuj -->'
END = '<!-- github-issues:end -->'
SECTIONS = (('Now', 'now'), ('Next', 'next'), ('Later', 'later'))
CLASSES = {'klasa/ryzyko': '🔴', 'klasa/przychod': '💰', 'klasa/fokus': '🎯',
           'klasa/higiena': '🧹', 'klasa/pomysl': '💡'}
SIZES = {'size-s': 'S', 'size-m': 'M', 'size-l': 'L', 'size-xl': 'XL'}

_DATE_RE = re.compile(r'<!--\s*planner-date:\s*(\d{4}-\d{2}-\d{2})\s*-->')
_LINK_RE = re.compile(r'—\s\[#(\d+)\]\(https://github\.com/([\w.-]+/[\w.-]+)/issues/(\d+)\)\s*$')
_TASK_RE = re.compile(r'^\s*[-*]\s+\[[ xX]\]\s+(.+?)\s*$')


def _sort_key(issue: dict[str, Any]) -> tuple[int, int, int, int]:
    names = {lb['name'] for lb in issue.get('labels') or []}
    cls = next((i for i, lb in enumerate(CLASSES) if lb in names), len(CLASSES))
    size = next((i for i, lb in enumerate(SIZES) if lb in names), len(SIZES))
    return cls, 0 if 'odblokowuje' in names else 1, size, issue['number']


def issue_line(issue: dict[str, Any]) -> str:
    """`- [ ] 💰 L ⛓ 2026-11-12 **Title** — [#1028](url)` (rubric §8). The link
    goes last, after " — ", so the Dziś title cut drops it."""
    names = {lb['name'] for lb in issue.get('labels') or []}
    date = _DATE_RE.search(issue.get('body') or '')
    parts = [
        next((e for lb, e in CLASSES.items() if lb in names), ''),
        next((s for lb, s in SIZES.items() if lb in names), ''),
        '⛓' if 'odblokowuje' in names else '',
        '🖥' if 'tor-lokalny' in names else '',
        date.group(1) if date else (issue.get('created_at') or '')[:10],
        f"**{' '.join(issue['title'].split())}** — [#{issue['number']}]({issue['html_url']})",
    ]
    return '- [ ] ' + ' '.join(p for p in parts if p)


def render_issue_blocks(issues: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Section key → sorted task lines. PRs and unplanned issues are skipped."""
    out: dict[str, list[dict[str, Any]]] = {key: [] for _, key in SECTIONS}
    for issue in issues:
        if 'pull_request' in issue:
            continue
        names = {lb['name'] for lb in issue.get('labels') or []}
        key = next((k for _, k in SECTIONS if f'plan/{k}' in names), None)
        if key:
            out[key].append(issue)
    return {key: [issue_line(i) for i in sorted(items, key=_sort_key)] for key, items in out.items()}


def _is_header(line: str, name: str) -> bool:
    m = re.match(r'^## +(.+?)\s*$', line)
    return bool(m) and (m.group(1) == name or m.group(1).startswith(name + ' '))


def _block_bounds(lines: list[str], start: int, end: int) -> tuple[int, int] | None:
    s = next((i for i in range(start, end) if lines[i].startswith('<!-- github-issues:start')), None)
    e = next((i for i in range(s + 1, end) if lines[i].strip() == END), None) if s is not None else None
    return (s, e) if e is not None else None


def replace_issue_blocks(md: str, rendered: dict[str, list[str]]) -> str:
    """Swap the generated block of each Now/Next/Later section; insert it right
    under the header when missing. Sections absent from the note are skipped."""
    lines = md.split('\n')
    for name, key in SECTIONS:
        head = next((i for i, line in enumerate(lines) if _is_header(line, name)), None)
        if head is None:
            continue
        end = next((j for j in range(head + 1, len(lines)) if lines[j].startswith('## ')), len(lines))
        block = rendered.get(key, [])
        bounds = _block_bounds(lines, head + 1, end)
        if bounds:
            lines[bounds[0]:bounds[1] + 1] = [START, *block, END]
            continue
        if lines[head + 1:head + 2] == ['']:  # header already followed by a blank line
            lines[head + 2:head + 2] = [START, *block, END, '']
        else:
            lines[head + 1:head + 1] = ['', START, *block, END, '']
    return '\n'.join(lines)


def in_issue_block(md: str, task_text: str) -> bool:
    """True when `task_text` is a task line inside a generated block — a Dziś
    toggle on such a line closes the issue instead of editing markdown."""
    inside = False
    for line in md.split('\n'):
        if line.startswith('<!-- github-issues:start'):
            inside = True
        elif line.strip() == END:
            inside = False
        elif inside and (m := _TASK_RE.match(line)) and m.group(1) == task_text.strip():
            return True
    return False


def issue_ref(task_text: str) -> tuple[str, int] | None:
    """Repo and number from the trailing ` — [#n](url)` link only, so a link
    inside the title cannot redirect a toggle to another issue."""
    m = _LINK_RE.search(task_text)
    return (m.group(2), int(m.group(1))) if m and m.group(1) == m.group(3) else None
