"""pr_gate.py — what may happen to a PR right now, for pr-decide.

"Second pair of eyes" (2026-11-11): Piotr is asked about a PR only after
pr-review has reviewed its current head commit. The options follow the
review: ok → Scal; findings → Popraw (pr-agent fixes, max MAX_ROUNDS) or
Scal mimo to. A decision's ref carries the reviewed SHA (`repo#12@<sha>`), so
an answer given for an older commit can never merge newer, unreviewed code.
"""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any, Callable

OWNER_DEFAULT = 'PiotrRomanczuk'
MAX_ROUNDS = 2
MERGE = {'key': 'yes', 'label': 'Scal'}
FORCE = {'key': 'force', 'label': 'Scal mimo to'}
FIX = {'key': 'fix', 'label': 'Popraw'}
CLOSE = {'key': 'no', 'label': 'Odrzuć'}
LATER = {'key': 'later', 'label': 'Później'}
RED = ('FAILURE', 'ERROR', 'TIMED_OUT', 'CANCELLED')
ROUND_RE = re.compile(r'^fix-round:(\d+)$')

Gh = Callable[[list[str]], str]


def ref_of(repo: str, number: int | str, sha: str) -> str:
    return f'{repo}#{number}@{sha}'


def split_ref(ref: str) -> tuple[str, str, str | None] | None:
    """`repo#12@sha` → (repo, '12', sha); legacy `repo#12` → (repo, '12', None)."""
    head, _, sha = ref.partition('@')
    repo, _, num = head.partition('#')
    return (repo, num, sha or None) if repo and num.isdigit() else None


def pr_key(ref: str) -> str:
    return ref.partition('@')[0]


def state(run: Gh, owner: str, repo: str, number: int) -> dict[str, Any]:
    """Head SHA, whether it can merge, and a one-line size/why-not."""
    v = json.loads(run(['pr', 'view', str(number), '-R', f'{owner}/{repo}', '--json',
                        'headRefOid,mergeable,statusCheckRollup,additions,deletions']))
    size = f'+{v.get("additions", 0)} / −{v.get("deletions", 0)} linii'
    red = [c.get('name') or c.get('context') for c in v.get('statusCheckRollup') or []
           if (c.get('conclusion') or c.get('state') or '').upper() in RED]
    if v.get('mergeable') == 'CONFLICTING':
        why = 'konflikt z gałęzią bazową'
    elif red:
        why = f'CI czerwone: {", ".join(red[:3])}'
    else:
        why = ''
    return {'sha': v.get('headRefOid') or '', 'ok': not why, 'line': f'{size} · {why}' if why else size}


def merge_reviewed(run: Gh, owner: str, repo: str, num: str, sha: str | None, log: Callable[[str], None]) -> None:
    """Squash-merge only the commit that was reviewed, and only while it can merge."""
    if not sha:
        log(f'{repo}#{num}: question predates reviews — waiting for pr-review, not merging')
        return
    st = state(run, owner, repo, int(num))
    if st['sha'] != sha:
        log(f'{repo}#{num}: head moved {sha[:7]} → {st["sha"][:7]} — not merging unreviewed code')
    elif not st['ok']:
        log(f'{repo}#{num}: cannot merge now ({st["line"]})')
    else:
        run(['pr', 'merge', num, '-R', f'{owner}/{repo}', '--squash', '--delete-branch', '--match-head-commit', sha])
        log(f'{repo}#{num} merged at {sha[:7]}')


def set_labels(run: Gh, owner: str, repo: str, number: int | str, add: tuple[str, ...] = (),
               remove: tuple[str, ...] = ()) -> None:
    """Labels through the REST issues API. Not `gh pr edit`: gh 2.46 (Ubuntu on uwh) queries the
    sunset Projects (classic) there and fails (2026-11-11). Removing an absent label is not an error."""
    path = f'repos/{owner}/{repo}/issues/{number}/labels'
    if add:
        run(['api', '-X', 'POST', path, *(arg for name in add for arg in ('-f', f'labels[]={name}'))])
    for name in remove:
        try:
            run(['api', '-X', 'DELETE', f'{path}/{name}'])
        except subprocess.CalledProcessError as exc:
            if '404' not in f'{exc.stderr or ""}{exc.stdout or ""}':
                raise


def rounds(labels: list[dict[str, Any]]) -> int:
    """Fix rounds done by pr-agent, from its `fix-round:N` labels."""
    found = [int(m.group(1)) for lb in labels if (m := ROUND_RE.match(lb.get('name', '')))]
    return max(found, default=0)


def options(review: dict[str, Any], ci_ok: bool, done_rounds: int) -> list[dict[str, str]]:
    """Choices for Piotr; never offers a merge that would fail (red CI / conflict)."""
    can_fix = done_rounds < MAX_ROUNDS
    if review['verdict'] == 'ok':  # red CI on a clean review: pr-agent can still try the failing checks
        return [MERGE, CLOSE, LATER] if ci_ok else ([FIX] if can_fix else []) + [CLOSE, LATER]
    picks = ([FIX] if can_fix else []) + ([FORCE] if ci_ok else []) + [CLOSE, LATER]
    return picks[:4]


def detail(review: dict[str, Any], st: dict[str, Any], age_days: int, author: str, done_rounds: int) -> str:
    findings = review.get('findings') or []
    worst = ', '.join(sorted({f['severity'] for f in findings})) or 'brak uwag'
    parts = [f'Recenzja: {review["verdict"]} ({worst}) — {review["summary"]}',
             f'{st["line"]} · {age_days} dni · autor {author}' + (f' · rundy poprawek: {done_rounds}' if done_rounds else '')]
    if review.get('comment_url'):
        parts.append(f'Uwagi: {review["comment_url"]}')
    parts.append('Scal = squash-merge tego commitu; Popraw = pr-agent poprawia uwagi; Odrzuć = zamknięcie z '
                 'powodem; Później = wraca za 7 dni.')
    return '\n'.join(parts)
