#!/usr/bin/env python3
"""planner-sync — pulls the Obsidian planner repo and syncs project state
into Postgres via POST /api/projects/sync.

Runs on elitedesk (where the planner bare repo lives anyway). Pulls every
SYNC_INTERVAL seconds, parses projects/*.md frontmatter + Now/Next/Later
sections, POSTs the full set. The server-side handler upserts each row
and deletes any slug missing from the payload, so vault deletes
propagate without a separate command.

Env:
  INGEST_URL       (required) e.g. http://127.0.0.1:64421/api/ingest
  INGEST_TOKEN     (required) shared secret
  HOST_NAME        defaults to 'elitedesk'
  PLANNER_REMOTE   git URL to clone if PLANNER_DIR is missing
                   (e.g. file:///home/<user>/git/planner.git)
  PLANNER_DIR      local working clone, defaults to ~/planner-mirror
  SYNC_INTERVAL    seconds between syncs, default 60
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))
sys.path.insert(0, str(_here.parent))
from _common import IngestClient, Shutdown  # noqa: E402

HOST_NAME = os.environ.get('HOST_NAME', 'elitedesk')
PLANNER_REMOTE = os.environ.get('PLANNER_REMOTE', '')
PLANNER_DIR = Path(os.environ.get('PLANNER_DIR') or (Path.home() / 'planner-mirror'))
SYNC_INTERVAL = float(os.environ.get('SYNC_INTERVAL', '60'))
TOGGLE_INTERVAL = float(os.environ.get('TOGGLE_INTERVAL', '2'))

ic = IngestClient.from_env(host=HOST_NAME, source='agent:planner-sync', timeout=10)
shutdown = Shutdown()

INGEST_BASE = ic.events_url.replace('/api/ingest', '').rstrip('/')
SYNC_URL = INGEST_BASE + '/api/projects/sync'
TOGGLES_URL = INGEST_BASE + '/api/task_toggles'
BOARD_URL = INGEST_BASE + '/api/board'
BOARD_IMPORT_URL = INGEST_BASE + '/api/board/import'
BOARD_SLUG = os.environ.get('BOARD_SLUG', 'home-ops')


def post_log(level: str, message: str, data: dict[str, Any] | None = None) -> None:
    ic.post_log(level, message, data)


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


# ── task writeback (UI checkbox toggle → markdown file → git push) ────

_TOGGLE_LINE_RE = re.compile(r'^(\s*[-*]\s+\[)([ xX])(\]\s+)(.+?)(\s*)$')


def _flip_task_in_section(text: str, section: str, idx: int, done: bool) -> str | None:
    """Walk the markdown file. Find the `## <section>` header (case-insensitive
    match on the canonical name OR a "<Name> — ..." variant). Inside that
    section, find the Nth `- [ ]` / `- [x]` line and flip it. Return the
    modified text, or None if section/idx wasn't resolvable."""
    target = section.lower()
    lines = text.split('\n')
    in_section = False
    task_count = 0
    for i, raw in enumerate(lines):
        header = re.match(r'^##\s+(.+?)\s*$', raw)
        if header:
            name = header.group(1).strip().lower()
            # Match 'now' / 'next' / 'later' or 'now — ...' variants
            canonical = name.split(' ')[0] if name else ''
            in_section = canonical == target or (target == 'pain' and name.startswith('pain'))
            task_count = 0
            continue
        if not in_section:
            continue
        m = _TOGGLE_LINE_RE.match(raw)
        if not m:
            continue
        if task_count == idx:
            new_marker = 'x' if done else ' '
            lines[i] = f'{m.group(1)}{new_marker}{m.group(3)}{m.group(4)}{m.group(5)}'
            return '\n'.join(lines)
        task_count += 1
    return None


def _apply_one_toggle(toggle: dict[str, Any]) -> tuple[str, str | None]:
    """Returns (status, error). status ∈ {'applied', 'conflict', 'failed'}."""
    slug = toggle['slug']
    section = toggle['section']
    idx = int(toggle['idx'])
    done = bool(toggle['done'])

    md_path = PLANNER_DIR / 'projects' / f'{slug}.md'
    if not md_path.exists():
        return 'failed', f'projects/{slug}.md not found in clone'

    # Pull first — keeps us aligned with any Obsidian edits that landed since
    # the last 60s sync tick.
    pull_r = _run_git('pull', '--ff-only')
    if pull_r.returncode != 0:
        return 'conflict', f'pre-edit pull failed: {pull_r.stderr.strip()[-300:]}'

    try:
        text = md_path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as e:
        return 'failed', f'read failed: {e}'

    new_text = _flip_task_in_section(text, section, idx, done)
    if new_text is None:
        return 'failed', f'task not found: section={section} idx={idx}'
    if new_text == text:
        # Already in the desired state. Treat as applied — UI got there
        # first (e.g. concurrent toggle).
        return 'applied', None

    md_path.write_text(new_text, encoding='utf-8')

    add_r = _run_git('add', str(md_path.relative_to(PLANNER_DIR)))
    if add_r.returncode != 0:
        return 'failed', f'git add: {add_r.stderr.strip()[-300:]}'
    commit_r = _run_git('-c', 'user.name=planner-sync', '-c', 'user.email=planner-sync@home-ops',
                        'commit', '-m', f'task toggle: {slug}/{section}/{idx} → {"done" if done else "open"}')
    if commit_r.returncode != 0:
        return 'failed', f'git commit: {commit_r.stderr.strip()[-300:]}'
    push_r = _run_git('push')
    if push_r.returncode != 0:
        return 'conflict', f'git push: {push_r.stderr.strip()[-300:]}'
    return 'applied', None


def _fetch_queued_toggles(limit: int = 20) -> list[dict[str, Any]]:
    """GET /api/task_toggles?status=queued. Returns [] on any error so the
    drain loop just retries next tick."""
    req = urllib.request.Request(
        f'{TOGGLES_URL}?status=queued&limit={limit}',
        headers={'X-Ingest-Token': ic.token},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            payload = json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        post_log('warn', f'task_toggles fetch failed: {type(e).__name__}', {'err': str(e)[:300]})
        return []
    return payload.get('toggles') or []


def _drain_toggles_once() -> None:
    """Fetch queued toggles, apply each. Best-effort; per-toggle errors are
    surfaced via the mark + a warn event, but don't take down the loop."""
    toggles = _fetch_queued_toggles()

    if not toggles:
        return

    for t in toggles:
        status, err = _apply_one_toggle(t)
        mark_status, mark_body = ic.request(
            f'{TOGGLES_URL}/{t["id"]}/mark',
            {'status': status, 'error': err},
            timeout=5,
        )
        if mark_status != 200:
            post_log('warn', f'mark toggle {t["id"]} {status} failed', {'http': mark_status})

        if status == 'conflict':
            # Surface in the affected project's drill page via app:home-ops
            # event with data.slug so projLogs(slug) picks it up.
            post_log('warn', f'vault conflict on task toggle for {t["slug"]}', {
                'slug': t['slug'],
                'section': t['section'],
                'idx': t['idx'],
                'error': (err or '')[:300],
            })


def toggles_loop() -> None:
    while not shutdown.wait(TOGGLE_INTERVAL):
        try:
            _drain_toggles_once()
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            post_log('error', f'toggles tick raised: {type(e).__name__}', {'err': str(e)[:500]})


# ── board sync (DB-authoritative board_tasks ↔ vault markdown) ────────
#
# The Board tab writes board_tasks (Postgres, authoritative). Each vault-sync
# tick we render those rows back into the Now/Next/Later sections of
# projects/<BOARD_SLUG>.md and push, so Obsidian + the digest stay consistent.
# Obsidian-only edits (board untouched) are imported back into the board.
# Reconciliation is watermark + managed-section-hash based; see board_sync_once.

_MANAGED = (('Now', 'now'), ('Next', 'next'), ('Later', 'later'))

# Reconciliation baseline. Persisted across restarts: without it the first
# tick after a restart takes the "DB is authoritative" branch and overwrites
# any Obsidian edits made while the agent was down.
STATE_FILE = Path(os.environ.get('STATE_FILE') or f'{PLANNER_DIR}.state.json')


def _load_state() -> dict[str, Any]:
    try:
        raw = json.loads(STATE_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'watermark': None, 'hash': None}
    return {'watermark': raw.get('watermark'), 'hash': raw.get('hash')}


def _save_state() -> None:
    try:
        STATE_FILE.write_text(json.dumps(_board_last), encoding='utf-8')
    except OSError as e:
        post_log('warn', f'state file write failed: {e}', {'path': str(STATE_FILE)})


_board_last: dict[str, Any] = _load_state()


def _hash(text: str) -> str:
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def _parse_section_tasks(md: str | None) -> list[tuple[str, bool]]:
    """Extract [(text, done)] from a Now/Next/Later section's markdown."""
    out: list[tuple[str, bool]] = []
    for line in (md or '').split('\n'):
        m = _TOGGLE_LINE_RE.match(line)
        if m:
            out.append((m.group(4).strip(), m.group(2).lower() == 'x'))
    return out


def render_sections_md(tasks: list[dict[str, Any]]) -> dict[str, list[str]]:
    """DB rows → { 'Now': ['- [ ] a', ...], 'Next': [...], 'Later': [...] }.
    Ordered by position; newlines in a task collapse to spaces so each card
    stays a single checkbox line."""
    rendered: dict[str, list[str]] = {disp: [] for disp, _ in _MANAGED}
    by_key = {key: disp for disp, key in _MANAGED}
    ordered = sorted(tasks, key=lambda t: (t.get('position') or 0, t.get('id') or 0))
    for t in ordered:
        disp = by_key.get(t.get('column_key'))
        if disp is None:
            continue
        marker = 'x' if t.get('done') else ' '
        text = ' '.join(str(t.get('text') or '').split('\n')).strip()
        rendered[disp].append(f'- [{marker}] {text}')
    return rendered


def _header_canonical(line: str) -> str | None:
    m = re.match(r'^##\s+(.+?)\s*$', line)
    if not m:
        return None
    raw = m.group(1).strip()
    for disp, _ in _MANAGED:
        if raw == disp or raw.startswith(disp + ' ') or raw.startswith(disp + ' —'):
            return disp
    return None


def replace_managed_sections(md_text: str, rendered: dict[str, list[str]]) -> str:
    """Rewrite ONLY the Now/Next/Later section bodies from `rendered`, leaving
    frontmatter, title, Pain points, Notes and anything else untouched."""
    lines = md_text.split('\n')
    out: list[str] = []
    seen: set[str] = set()
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        canon = _header_canonical(line)
        if canon and canon not in seen and canon in rendered:
            seen.add(canon)
            out.append(line)          # keep the header verbatim
            out.append('')
            out.extend(rendered[canon])
            out.append('')
            i += 1
            while i < n and not re.match(r'^#{1,6}\s', lines[i]):
                i += 1                # drop the old body up to the next header
            continue
        out.append(line)
        i += 1
    return '\n'.join(out)


def _managed_hash(md_text: str) -> str:
    s = _split_sections(md_text)
    return _hash('\n----\n'.join(s.get(disp, '') for disp, _ in _MANAGED))


def _board_get(slug: str) -> dict[str, Any] | None:
    req = urllib.request.Request(
        f'{BOARD_URL}?slug={slug}', headers={'X-Ingest-Token': ic.token})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        post_log('warn', f'board fetch failed: {type(e).__name__}', {'err': str(e)[:300]})
        return None


def _board_import(slug: str, parsed: dict[str, Any], focus_text: str | None) -> dict[str, Any] | None:
    tasks: list[dict[str, Any]] = []
    for disp, key in _MANAGED:
        for text, done in _parse_section_tasks(parsed.get(f'{key}_md')):
            tasks.append({'column': key, 'text': text, 'done': done})
    status, body = ic.request(
        BOARD_IMPORT_URL, {'slug': slug, 'tasks': tasks, 'focusText': focus_text}, timeout=10)
    if status == 200:
        return body
    post_log('warn', 'board import failed', {'status': status})
    return None


def _write_commit_push(md_path: Path, new_text: str, msg: str) -> bool:
    pr = _run_git('pull', '--ff-only')
    if pr.returncode != 0:
        post_log('warn', 'board-sync pre-push pull failed', {'stderr': pr.stderr.strip()[-300:]})
        return False
    md_path.write_text(new_text, encoding='utf-8')
    if _run_git('add', str(md_path.relative_to(PLANNER_DIR))).returncode != 0:
        return False
    commit = _run_git('-c', 'user.name=planner-sync', '-c', 'user.email=planner-sync@home-ops',
                      'commit', '-m', msg)
    if commit.returncode != 0:
        post_log('warn', 'board-sync commit failed', {'stderr': commit.stderr.strip()[-300:]})
        return False
    push = _run_git('push')
    if push.returncode != 0:
        post_log('warn', 'board-sync push conflict', {'stderr': push.stderr.strip()[-300:]})
        return False
    return True


def board_sync_once() -> None:
    """Reconcile board_tasks (authoritative) with the vault markdown.
      board changed  → render DB→vault and push (DB wins).
      vault changed, board untouched → import Obsidian edits into the board.
      first tick with an empty board → seed the board from the vault.
    Loop-safe: after each write we store the managed-section hash, so our own
    commit is not seen as an external edit next tick."""
    md_path = PLANNER_DIR / 'projects' / f'{BOARD_SLUG}.md'
    if not md_path.exists():
        return
    board = _board_get(BOARD_SLUG)
    if board is None:
        return
    tasks = board.get('tasks') or []
    watermark = board.get('updatedAt')
    try:
        current = md_path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return

    # Seed an empty board from the vault on first run.
    if not tasks and _board_last['watermark'] is None:
        parsed = parse_project_file(md_path)
        res = _board_import(BOARD_SLUG, parsed or {}, None) if parsed else None
        if res:
            _board_last['watermark'] = res.get('updatedAt')
            _board_last['hash'] = _managed_hash(current)
            _save_state()
        return

    rendered = render_sections_md(tasks)
    new_md = replace_managed_sections(current, rendered)
    first = _board_last['watermark'] is None
    board_changed = (not first) and (watermark != _board_last['watermark'])

    if first or board_changed:
        # DB is authoritative — author the vault (write only if it differs).
        if new_md != current and not _write_commit_push(md_path, new_md, f'board sync: {BOARD_SLUG}'):
            return  # retry next tick; don't advance the baseline
        _board_last['watermark'] = watermark
        _board_last['hash'] = _managed_hash(new_md)
        _save_state()
    elif _managed_hash(current) != _board_last['hash']:
        # Board untouched but the vault's managed sections changed in Obsidian.
        focus_text = next((t['text'] for t in tasks if t.get('is_focus')), None)
        parsed = parse_project_file(md_path)
        res = _board_import(BOARD_SLUG, parsed or {}, focus_text) if parsed else None
        if res:
            _board_last['watermark'] = res.get('updatedAt')
            _board_last['hash'] = _managed_hash(current)
            _save_state()


# ── main loop ─────────────────────────────────────────────────────────

def sync_once() -> None:
    if not ensure_clone():
        return
    if not pull():
        # We still try to parse with whatever's on disk — partial outage on
        # the git remote shouldn't blank out the projects table.
        pass

    # Board tab: reconcile board_tasks ↔ vault. Runs before the parse below so
    # the projects table reflects any DB→vault render from this same tick.
    try:
        board_sync_once()
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        post_log('error', f'board-sync raised: {type(e).__name__}', {'err': str(e)[:500]})

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

    status, body = ic.request(SYNC_URL, {'projects': records}, timeout=15)
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
    shutdown.install()
    post_log('info', f'planner-sync up: sync={SYNC_INTERVAL}s toggle={TOGGLE_INTERVAL}s dir={PLANNER_DIR}')
    # Task toggles drain in their own thread at TOGGLE_INTERVAL so UI feedback
    # is sub-5s instead of waiting on the 60s vault-sync tick.
    threading.Thread(target=toggles_loop, daemon=True, name='toggles').start()
    # Main vault-sync loop. wait() returns True on shutdown, breaking cleanly.
    while True:
        try:
            sync_once()
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            post_log('error', f'sync tick raised: {type(e).__name__}', {'err': str(e)[:500]})
        if shutdown.wait(SYNC_INTERVAL):
            break
    post_log('info', 'planner-sync down (signal)')


if __name__ == '__main__':
    main()
