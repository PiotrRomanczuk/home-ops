#!/usr/bin/env python3
"""vault-ticks-backfill — seeds project_signals tasks_done / tasks_added for
past weeks from the vault's git history (the planner-mirror clone on
elitedesk), so the Postęp tab is not empty before planner-sync's live tick
tracking has seen anything.

For every commit in the window, each changed project note is compared with
its previous version (agents/elitedesk/task_ticks.py — the same keys
planner-sync uses live) and the difference is counted on the commit's local
day. Renamed/moved notes are a baseline, not a burst of "new" tasks.

It REPLACES its window for tasks_done/tasks_added, so re-running is safe.
The vault only knows what was pushed: a week committed in one go lands on one
day.

  python3 ops/elitedesk/vault-ticks-backfill.py [--days 84] [--dry-run]

Env: INGEST_URL / INGEST_TOKEN (elitedesk-watcher.env), PLANNER_DIR
(default ~/code/planner-mirror), PROJECT_DIRS (as planner-sync).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent.parent))
sys.path.insert(0, str(_here.parent.parent / 'agents' / 'elitedesk'))
from agents._common import IngestClient  # noqa: E402
from task_ticks import diff, note_slug, note_tasks  # noqa: E402

PLANNER_DIR = Path(os.environ.get('PLANNER_DIR') or Path.home() / 'code' / 'planner-mirror')
PROJECT_DIRS = [d.strip() for d in os.environ.get(
    'PROJECT_DIRS', 'projects,1-Projekty,2-Obszary,3-Zasoby/pomysly,4-Archiwum').split(',') if d.strip()]
SIGNALS = ['tasks_done', 'tasks_added']


def git(*args: str) -> str | None:
    p = subprocess.run(['git', '-C', str(PLANNER_DIR), *args], capture_output=True, text=True, timeout=60)
    return p.stdout if p.returncode == 0 else None


def known_slugs(ic: IngestClient) -> set[str]:
    base = ic.events_url.rsplit('/api/', 1)[0]
    req = urllib.request.Request(base + '/api/projects', headers={'X-Ingest-Token': ic.token})
    with urllib.request.urlopen(req, timeout=15) as r:
        return {p['slug'] for p in json.loads(r.read()).get('projects') or []}


def count(days: int, slugs: set[str]) -> tuple[Counter, str]:
    log = git('log', f'--since={days} days ago', '--reverse', '--format=%H%x09%cI', '--', *PROJECT_DIRS) or ''
    counts: Counter = Counter()
    first = None
    for line in log.splitlines():
        sha, when = line.split('\t')
        day = datetime.fromisoformat(when).astimezone().date().isoformat()
        first = first or day
        files = git('diff-tree', '--no-commit-id', '--name-only', '-r', '-M', sha, '--', *PROJECT_DIRS) or ''
        for path in (f for f in files.splitlines() if f.endswith('.md')):
            before, after = git('show', f'{sha}^:{path}'), git('show', f'{sha}:{path}')
            if before is None or after is None:
                continue  # new, moved or deleted note: a baseline, not a burst
            slug = note_slug(after, Path(path).stem)
            if slug not in slugs:
                continue
            for s, (done, added) in diff({slug: note_tasks(before)}, {slug: note_tasks(after)}).items():
                counts[(s, day, 'tasks_done')] += done
                counts[(s, day, 'tasks_added')] += added
    return counts, first or datetime.now().date().isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=84)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    ic = IngestClient.from_env(host=os.environ.get('HOST_NAME', 'elitedesk'), source='agent:vault-ticks-backfill')
    slugs = known_slugs(ic)
    counts, first = count(args.days, slugs)
    rows = [{'project_slug': s, 'day': d, 'signal': sig, 'n': n} for (s, d, sig), n in sorted(counts.items()) if n]
    per_project = Counter()
    for r in rows:
        per_project[(r['project_slug'], r['signal'])] += r['n']
    for (slug, sig), n in sorted(per_project.items()):
        print(f'{slug:28} {sig:12} {n}')
    if args.dry_run:
        print(f'dry run: {len(rows)} rows from {first}, nothing written')
        return 0
    today = datetime.now().date().isoformat()
    replace = {'from': first, 'to': today, 'projects': sorted(slugs), 'signals': SIGNALS}
    status, body = ic.request(ic.events_url.rsplit('/api/', 1)[0] + '/api/progress/signals',
                              {'rows': rows, 'replace': replace}, timeout=30)
    print(f'POST /api/progress/signals → {status} {body}')
    return 0 if 200 <= status < 300 else 1


if __name__ == '__main__':
    raise SystemExit(main())
