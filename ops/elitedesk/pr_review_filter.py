"""pr_review_filter.py — whose PRs pr-review checks out and pr-decide asks about.

Only PRs from a branch of the same repo (`isCrossRepository == false`) opened by the
owner or a bot on ALLOWED_AUTHORS. Anything else is skipped before `checkout`: a
stranger's branch could carry `.claude/settings.json` hooks or a `CLAUDE.md` that the
reviewer on uwh would load (security audit 2026-11-15, S1). Unknown fork status
counts as a fork.

Env: PR_OWNER, PR_REVIEW_AUTHORS (comma-separated logins; replaces the default list).
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable

OWNER = os.environ.get('PR_OWNER', 'PiotrRomanczuk')
ALLOWED_AUTHORS = frozenset(a.strip().casefold() for a in os.environ.get(
    'PR_REVIEW_AUTHORS', f'{OWNER},dependabot[bot],app/dependabot').split(',') if a.strip())
FIELDS = 'isCrossRepository,author,headRepositoryOwner'

Gh = Callable[[list[str]], str]
Log = Callable[[str], None]


def login(p: dict[str, Any]) -> str:
    return str((p.get('author') or {}).get('login') or '?')


def author_ok(p: dict[str, Any]) -> bool:
    return login(p).casefold() in ALLOWED_AUTHORS


def same_repo(p: dict[str, Any]) -> bool:
    head = (p.get('headRepositoryOwner') or {}).get('login')
    return p.get('isCrossRepository') is False and (head is None or head.casefold() == OWNER.casefold())


def allowed(p: dict[str, Any], repo: str, num: int, log: Log) -> bool:
    """True if the PR may be reviewed; otherwise logs why it was skipped."""
    why = 'autor' if not author_ok(p) else 'fork' if not same_repo(p) else ''
    if why:
        log(f'pominięty ({why}): {repo}#{num} {login(p)}')
    return not why


def allowed_pr(run: Gh, p: dict[str, Any], log: Log) -> bool:
    """For a `gh search prs` row (no fork info): author first, then `gh pr view` for the fork fields."""
    repo, num = p['repository']['name'], p['number']
    if not author_ok(p):
        return allowed(p, repo, num, log)
    meta = json.loads(run(['pr', 'view', str(num), '-R', f'{OWNER}/{repo}', '--json', FIELDS]) or '{}')
    return allowed(meta, repo, num, log)
