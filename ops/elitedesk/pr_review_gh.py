"""pr_review_gh.py — git and GitHub side of pr-review: a cached clone per repo
checked out at the PR head, the diff the reviewer reads, and publishing (one
comment per reviewed commit + a review:* label).

The diff skips files that are big but carry no logic — manual-test reports
with base64 screenshots (vectordigital#7: 4 MB of a 4.3 MB diff) and lock
files — and tells the reviewer which ones were skipped."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

OWNER = os.environ.get('PR_OWNER', 'PiotrRomanczuk')
CACHE = Path(os.environ.get('PR_REVIEW_CACHE', '~/.cache/pr-review')).expanduser()
SKIP = ('docs/manual-tests/*.html', '**/package-lock.json', '**/pnpm-lock.yaml', '**/yarn.lock', '**/uv.lock')
MAX_DIFF = 400_000  # chars; beyond this the reviewer gets the stat and reads files itself
MARKER = '<!-- pr-review sha={sha} -->'
LABELS = {'ok': ('review:ok', '1f883d'), 'zmiany': ('review:zmiany', 'd29922'), 'bloker': ('review:zmiany', 'd29922')}
SEVERITY = {'bloker': '🔴 bloker', 'ważne': '🟠 ważne', 'drobne': '⚪ drobne'}
VERDICT = {'ok': '✅ Można scalać', 'zmiany': '🟠 Do poprawy przed scaleniem', 'bloker': '🔴 Nie scalać'}


def git(args: list[str], cwd: Path) -> str:
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def checkout(repo: str, number: int, base: str) -> Path:
    """Clone once, then fetch the PR head and the base; leaves a detached HEAD at the PR head."""
    path = CACHE / repo
    if not (path / '.git').is_dir():
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'clone', '-q', f'git@github.com:{OWNER}/{repo}.git', str(path)],
                       check=True, capture_output=True, text=True)
    git(['fetch', '-q', '--force', 'origin', f'pull/{number}/head:pr-review/{number}', base], path)
    git(['checkout', '-q', '--force', '--detach', f'pr-review/{number}'], path)
    git(['clean', '-q', '-fdx'], path)
    return path


def diff(path: Path, base: str) -> tuple[str, str]:
    """(diff without skipped files, stat of the skipped ones)."""
    spec = f'origin/{base}...HEAD'
    body = git(['diff', spec, '--', '.', *(f':(exclude){p}' for p in SKIP)], path)
    skipped = git(['diff', '--stat', spec, '--', *SKIP], path).strip()
    if len(body) > MAX_DIFF:
        stat = git(['diff', '--stat', spec, '--', '.', *(f':(exclude){p}' for p in SKIP)], path)
        body = f'(diff ma {len(body)} znaków — za duży; poniżej lista plików, czytaj je narzędziem Read)\n{stat}'
    return body, skipped


def render(review: dict[str, Any], sha: str) -> str:
    """The PR comment: verdict, summary, findings — Polish, one marker per reviewed commit."""
    lines = [MARKER.format(sha=sha), f'### Recenzja automatyczna — {VERDICT[review["verdict"]]}',
             f'Commit `{sha[:7]}` · niezależny recenzent (świeża sesja, tylko odczyt)', '', review['summary']]
    for f in review.get('findings') or []:
        lines += ['', f'**{SEVERITY.get(f["severity"], f["severity"])}** `{f["file"]}:{f["line"]}` — {f["problem"]}',
                  f'> {f["evidence"]}', f'Propozycja: {f["suggestion"]}']
    if review.get('dropped'):
        lines += ['', f'_Odrzucone przy weryfikacji jako niepotwierdzone: {review["dropped"]}._']
    lines += ['', '_Decyzja na stronie „Dziś” (home-ops). Autor zmian nie scala własnego PR._']
    return '\n'.join(lines)


def publish(run, repo: str, number: int, review: dict[str, Any], sha: str) -> str:
    """Comment + swap the review:* label; returns the comment URL."""
    url = run(['pr', 'comment', str(number), '-R', f'{OWNER}/{repo}', '--body', render(review, sha)]).strip()
    for label, color in {LABELS['ok'], LABELS['zmiany']}:  # both must exist before add/remove
        run(['label', 'create', label, '-R', f'{OWNER}/{repo}', '--color', color, '--force'])
    name = LABELS[review['verdict']][0]
    other = 'review:zmiany' if name == 'review:ok' else 'review:ok'
    run(['pr', 'edit', str(number), '-R', f'{OWNER}/{repo}', '--add-label', name, '--remove-label', other])
    return url
