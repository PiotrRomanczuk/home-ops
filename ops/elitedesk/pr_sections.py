"""pr_sections.py — the documentation pr-decide files for a PR's review page (migration 033).

The review page (/review/:id in ingest) is the only place a merge is accepted; it shows the
pr-review verdict plus whatever was filed here for the same head commit. pr-decide files the
basics every PR has: description, changed files, CI checks, and links to the manual test
reports the PR adds. Repos can file more for the same commit (Strummy CI: screen gallery,
backend changes) through the same endpoint.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable

Gh = Callable[[list[str]], str]
MAX_FILES = 200


def _files(files: list[dict[str, Any]], total: int) -> str:
    rows = [f"- `{f.get('path', '?')}` +{f.get('additions', 0)} / −{f.get('deletions', 0)}" for f in files[:MAX_FILES]]
    shown = min(len(files), MAX_FILES)
    more = f'\n- … i {total - shown} więcej (lista z gh jest obcięta)' if total > shown else ''
    return '\n'.join(rows) + more if rows else '_(brak zmienionych plików)_'


def _checks(rollup: list[dict[str, Any]]) -> str:
    rows = [f"- {c.get('name') or c.get('context') or '?'}: "
            f"{(c.get('conclusion') or c.get('state') or 'pending').lower()}" for c in rollup]
    return '\n'.join(rows) or '_(brak checków CI)_'


def collect(run: Gh, owner: str, repo: str, number: int, sha: str) -> list[dict[str, Any]]:
    """Sections for the review page of `repo#number` at `sha`."""
    v = json.loads(run(['pr', 'view', str(number), '-R', f'{owner}/{repo}', '--json',
                        'body,files,changedFiles,statusCheckRollup,baseRefName,headRefName']))
    files = v.get('files') or []
    # `files` is capped by gh (about 100); changedFiles is the real count.
    total = v.get('changedFiles') or len(files)
    snapshot = datetime.now().astimezone().strftime('%H:%M')
    head, base = v.get('headRefName') or '?', v.get('baseRefName') or '?'
    out = [
        {'key': 'summary', 'title': f'Opis PR ({head} → {base})', 'position': 10,
         'body_md': (v.get('body') or '').strip() or '_(PR bez opisu)_'},
        {'key': 'files', 'title': f'Zmienione pliki ({total})', 'position': 20, 'body_md': _files(files, total)},
        {'key': 'checks', 'title': f'CI (stan z {snapshot})', 'position': 30,
         'body_md': _checks(v.get('statusCheckRollup') or [])},
    ]
    reports = [f['path'] for f in files if str(f.get('path', '')).startswith('docs/manual-tests/')]
    if reports:
        links = '\n'.join(f'- [{p}](https://github.com/{owner}/{repo}/blob/{sha}/{p})' for p in reports)
        out.append({'key': 'manual-test', 'title': f'Raporty testów ręcznych ({len(reports)})', 'position': 40,
                    'body_md': links})
    return out


def file(post: Callable[[str, dict[str, Any]], Any], run: Gh, owner: str, repo: str, number: int, sha: str) -> None:
    post('/api/reviews/sections', {'repo': repo, 'number': number, 'head_sha': sha, 'source': 'pr-decide',
                                   'sections': collect(run, owner, repo, number, sha)})
