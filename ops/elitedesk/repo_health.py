"""repo_health — open issues and open blueprint gaps per repo, for the Mapa
pressure queue. Stored by github-repo-sync in repo_meta.issues / repo_meta.gaps.

Takes the same `gh(path) -> parsed JSON | None` getter as github_signals, so
tests run without network. A None result means "no data"; an optional
`gh.status(path)` (last HTTP status) lets blueprint_gaps tell a missing
blueprint (404) from an API error, which it reports as `{'error': 'api'}`.
"""
from __future__ import annotations

import base64
import re
from datetime import datetime, timezone
from typing import Any, Callable

from gaps_parse import counts_as_blueprint, parse_gaps

Getter = Callable[[str], Any]
PAGE = 100
_BUG_RE = re.compile(r'(?<![a-z])bug(?![a-z])')


def _days_since(iso: str | None, now: datetime) -> int | None:
    if not iso:
        return None
    try:
        return (now - datetime.fromisoformat(iso.replace('Z', '+00:00'))).days
    except ValueError:
        return None


def _is_bug(label: Any) -> bool:
    name = str(label.get('name', '')).lower() if isinstance(label, dict) else ''
    return bool(_BUG_RE.search(name)) and not re.search(r'not[- ]a[- ]bug', name)


def issues_summary(gh: Getter, owner_repo: str, now: datetime | None = None) -> dict[str, Any] | None:
    """Open issues (PRs excluded), how many carry a *bug* label, the oldest age.
    First page only; `capped` says the real number may be higher."""
    items = gh(f'/repos/{owner_repo}/issues?state=open&per_page={PAGE}')
    if not isinstance(items, list):
        return None
    now = now or datetime.now(timezone.utc)
    issues = [i for i in items if isinstance(i, dict) and 'pull_request' not in i]
    bugs = [i for i in issues if any(_is_bug(lbl) for lbl in i.get('labels') or [])]
    ages = [d for d in (_days_since(i.get('created_at'), now) for i in issues) if d is not None]
    return {'open': len(issues), 'bugs': len(bugs), 'oldest_days': max(ages) if ages else None,
            'capped': len(items) >= PAGE}


def _missing(gh: Getter, path: str) -> bool:
    """True when the last request for `path` failed with something other than a
    plain 404. Getters without `status` (tests, old callers) count as 404."""
    status = getattr(gh, 'status', None)
    code = status(path) if callable(status) else 404
    return code not in (404, 200)


def _file_text(gh: Getter, owner_repo: str, path: str, ref: str) -> str | None:
    body = gh(f'/repos/{owner_repo}/contents/{path}?ref={ref}')
    if not isinstance(body, dict) or body.get('encoding') != 'base64' or not body.get('content'):
        return None
    try:
        return base64.b64decode(body['content']).decode('utf-8', errors='replace')
    except (ValueError, TypeError):
        return None


def blueprint_gaps(gh: Getter, owner_repo: str, ref: str) -> dict[str, Any] | None:
    """Open gap IDs from docs/BLUEPRINT.md and docs/app-blueprint/*.md; None when
    the repo has no blueprint (404); `{'error': 'api'}` when GitHub failed
    (rate limit, timeout) and nothing could be read; `partial: True` when some
    files could not be fetched, so the count may be low."""
    docs: dict[str, str] = {}
    single_path = f'/repos/{owner_repo}/contents/docs/BLUEPRINT.md?ref={ref}'
    single = _file_text(gh, owner_repo, 'docs/BLUEPRINT.md', ref)
    failed = _missing(gh, single_path) if single is None else False
    if single is not None:
        docs['BLUEPRINT.md'] = single
    list_path = f'/repos/{owner_repo}/contents/docs/app-blueprint?ref={ref}'
    listing = gh(list_path)
    if not isinstance(listing, list) and _missing(gh, list_path):
        failed = True
    for entry in listing if isinstance(listing, list) else []:
        name = str(entry.get('name', ''))
        if entry.get('type') == 'file' and counts_as_blueprint(name):
            text = _file_text(gh, owner_repo, str(entry.get('path')), ref)
            if text is not None:
                docs[name] = text
            else:
                failed = True
    if not docs:
        return {'error': 'api'} if failed else None
    return {**parse_gaps(docs), 'files': len(docs), **({'partial': True} if failed else {})}
