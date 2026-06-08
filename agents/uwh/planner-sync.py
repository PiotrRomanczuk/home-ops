#!/usr/bin/env python3
"""planner-sync — pulls the Obsidian planner repo and syncs project state
into Postgres via POST /api/projects/sync.

Runs on uwh (where the planner bare repo lives anyway). Pulls every
SYNC_INTERVAL seconds, parses projects/*.md frontmatter + Now/Next/Later
sections, POSTs the full set. The server-side handler upserts each row
and deletes any slug missing from the payload, so vault deletes
propagate without a separate command.

Env:
  INGEST_URL       (required) e.g. http://127.0.0.1:64421/api/ingest
  INGEST_TOKEN     (required) shared secret
  HOST_NAME        defaults to 'uwh'
  PLANNER_REMOTE   git URL to clone if PLANNER_DIR is missing
                   (e.g. file:///home/piotr/git/planner.git)
  PLANNER_DIR      local working clone, defaults to ~/planner-mirror
  SYNC_INTERVAL    seconds between syncs, default 60
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

INGEST_URL = (os.environ.get('INGEST_URL') or '').rstrip('/')
INGEST_TOKEN = os.environ.get('INGEST_TOKEN', '')
HOST_NAME = os.environ.get('HOST_NAME', 'uwh')
PLANNER_REMOTE = os.environ.get('PLANNER_REMOTE', '')
PLANNER_DIR = Path(os.environ.get('PLANNER_DIR') or (Path.home() / 'planner-mirror'))
SYNC_INTERVAL = float(os.environ.get('SYNC_INTERVAL', '60'))

if not INGEST_URL or not INGEST_TOKEN:
    print('INGEST_URL and INGEST_TOKEN required', file=sys.stderr)
    sys.exit(1)

INGEST_BASE = INGEST_URL.replace('/api/ingest', '').rstrip('/')
SYNC_URL = INGEST_BASE + '/api/projects/sync'
LOG_URL = INGEST_BASE + '/api/ingest'


# ── HTTP ──────────────────────────────────────────────────────────────

def _post(url: str, body: dict[str, Any], timeout: float = 10) -> tuple[int, dict[str, Any] | None]:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method='POST',
        headers={'X-Ingest-Token': INGEST_TOKEN, 'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except (json.JSONDecodeError, ValueError):
            return e.code, None
    except (urllib.error.URLError, TimeoutError):
        return 0, None


def post_log(level: str, message: str, data: dict[str, Any] | None = None) -> None:
    body = {'host': HOST_NAME, 'source': 'agent:planner-sync', 'level': level, 'message': message}
    if data:
        body['data'] = data
    _post(LOG_URL, body, timeout=5)


# ── git ───────────────────────────────────────────────────────────────

def _run_git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ['git', '-C', str(PLANNER_DIR), *args],
        capture_output=True, text=True, timeout=30,
    )


def ensure_clone() -> bool:
    """Returns True if the clone is usable, False if we need to skip this tick."""
    if (PLANNER_DIR / '.git').exists():
        return True
    if not PLANNER_REMOTE:
        post_log('error', f'PLANNER_DIR missing and PLANNER_REMOTE unset: {PLANNER_DIR}')
        return False
    PLANNER_DIR.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ['git', 'clone', PLANNER_REMOTE, str(PLANNER_DIR)],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        post_log('error', 'git clone failed', {'stderr': r.stderr[-500:]})
        return False
    post_log('info', 'planner repo cloned', {'remote': PLANNER_REMOTE, 'dir': str(PLANNER_DIR)})
    return True


def pull() -> bool:
    r = _run_git('pull', '--ff-only')
    if r.returncode != 0:
        post_log('warn', 'git pull failed (keeping existing checkout)', {'stderr': r.stderr[-500:]})
        return False
    return True


# ── markdown parsing ──────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r'^---\n(.*?)\n---\n', re.DOTALL)
_SECTION_RE = re.compile(r'^## +(.+?)\s*$', re.MULTILINE)
_TITLE_RE = re.compile(r'^# +(.+?)\s*$', re.MULTILINE)


def _parse_frontmatter(block: str) -> dict[str, Any]:
    """Minimal YAML: flat key/value, optional quoted strings, no nesting."""
    out: dict[str, Any] = {}
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line or line.startswith('#'):
            continue
        if ':' not in line:
            continue
        key, _, val = line.partition(':')
        key = key.strip()
        val = val.strip()
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        elif val.startswith("'") and val.endswith("'"):
            val = val[1:-1]
        # cast bare ints
        if val.isdigit() or (val.startswith('-') and val[1:].isdigit()):
            out[key] = int(val)
        else:
            out[key] = val
    return out


def _split_sections(body: str) -> dict[str, str]:
    """Returns { 'Now': '...', 'Next': '...', 'Later': '...', 'Pain points': '...', 'Notes': '...' }
    using first match of each canonical header. Header text after a hyphen
    is allowed (e.g. '## Next — Session 4 (...)' still maps to 'Next')."""
    canonical = ['Now', 'Next', 'Later', 'Pain points', 'Notes']
    headers: list[tuple[int, int, str]] = []
    for m in _SECTION_RE.finditer(body):
        raw_name = m.group(1).strip()
        for c in canonical:
            if raw_name == c or raw_name.startswith(c + ' ') or raw_name.startswith(c + ' —'):
                headers.append((m.start(), m.end(), c))
                break
    sections: dict[str, str] = {}
    for i, (start, end, name) in enumerate(headers):
        if name in sections:
            continue  # keep first match for each canonical name
        next_start = headers[i + 1][0] if i + 1 < len(headers) else len(body)
        sections[name] = body[end:next_start].strip()
    return sections


def parse_project_file(path: Path) -> dict[str, Any] | None:
    """Returns a project record dict, or None if the file is unparseable."""
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None

    fm: dict[str, Any] = {}
    m = _FRONTMATTER_RE.match(text)
    body = text
    if m:
        fm = _parse_frontmatter(m.group(1))
        body = text[m.end():]

    title_m = _TITLE_RE.search(body)
    title = title_m.group(1).strip() if title_m else fm.get('title') or path.stem

    sections = _split_sections(body)

    slug = str(fm.get('project') or path.stem)
    status = fm.get('status') if fm.get('status') in ('hot', 'warm', 'dormant', 'stalled') else 'dormant'

    return {
        'slug': slug,
        'title': title,
        'status': status,
        'path': fm.get('path'),
        'last_commit': fm.get('last_commit'),
        'commits_30d': int(fm.get('commits_30d') or 0),
        'updated_at': fm.get('updated') or fm.get('updated_at'),
        'now_md': sections.get('Now'),
        'next_md': sections.get('Next'),
        'later_md': sections.get('Later'),
        'pain_md': sections.get('Pain points'),
        'notes_md': sections.get('Notes'),
        'raw_frontmatter': fm,
    }


# ── main loop ─────────────────────────────────────────────────────────

def sync_once() -> None:
    if not ensure_clone():
        return
    if not pull():
        # We still try to parse with whatever's on disk — partial outage on
        # the git remote shouldn't blank out the projects table.
        pass

    projects_dir = PLANNER_DIR / 'projects'
    if not projects_dir.is_dir():
        post_log('error', f'projects/ not found in clone: {projects_dir}')
        return

    records: list[dict[str, Any]] = []
    skipped: list[str] = []
    for md in sorted(projects_dir.glob('*.md')):
        rec = parse_project_file(md)
        if rec is None:
            skipped.append(md.name)
            continue
        records.append(rec)

    status, body = _post(SYNC_URL, {'projects': records}, timeout=15)
    if status == 200 and body:
        post_log('info', 'sync ok', {
            'upserted': body.get('upserted'),
            'removed': body.get('removed'),
            'rejected': len(body.get('rejected') or []),
            'skipped_files': skipped,
        })
    else:
        post_log('error', 'sync failed', {'status': status, 'skipped_files': skipped})


def main() -> None:
    post_log('info', f'planner-sync up: interval={SYNC_INTERVAL}s dir={PLANNER_DIR}')
    try:
        while True:
            try:
                sync_once()
            except KeyboardInterrupt:
                raise
            except (OSError, ValueError, subprocess.SubprocessError) as e:
                post_log('error', f'sync tick raised: {type(e).__name__}', {'err': str(e)[:500]})
            time.sleep(SYNC_INTERVAL)
    except KeyboardInterrupt:
        post_log('info', 'planner-sync shutting down (SIGINT)')


if __name__ == '__main__':
    main()
