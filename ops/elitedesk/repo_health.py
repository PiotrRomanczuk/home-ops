"""repo_health — open issues and open blueprint gaps per repo, for the Mapa
pressure queue. Stored by github-repo-sync in repo_meta.issues / repo_meta.gaps.

Takes the same `gh(path) -> parsed JSON | None` getter as github_signals, so
tests run without network. A None result means "no data" (no blueprint, API
error) — the pressure model then counts zero, never guesses.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any, Callable

from gaps_parse import counts_as_blueprint, parse_gaps

Getter = Callable[[str], Any]
PAGE = 100


def _days_since(iso: str | None, now: datetime) -> int | None:
    if not iso:
        return None
    try:
        return (now - datetime.fromisoformat(iso.replace('Z', '+00:00'))).days
    except ValueError:
        return None


def issues_summary(gh: Getter, owner_repo: str, now: datetime | None = None) -> dict[str, Any] | None:
    """Open issues (PRs excluded), how many carry a *bug* label, the oldest age.
    First page only; `capped` says the real number may be higher."""
    items = gh(f'/repos/{owner_repo}/issues?state=open&per_page={PAGE}')
    if not isinstance(items, list):
        return None
    now = now or datetime.now(timezone.utc)
    issues = [i for i in items if isinstance(i, dict) and 'pull_request' not in i]
    bugs = [i for i in issues if any('bug' in str(lbl.get('name', '')).lower() for lbl in i.get('labels') or [])]
    ages = [d for d in (_days_since(i.get('created_at'), now) for i in issues) if d is not None]
    return {'open': len(issues), 'bugs': len(bugs), 'oldest_days': max(ages) if ages else None,
            'capped': len(items) >= PAGE}


def _file_text(gh: Getter, owner_repo: str, path: str, ref: str) -> str | None:
    body = gh(f'/repos/{owner_repo}/contents/{path}?ref={ref}')
    if not isinstance(body, dict) or body.get('encoding') != 'base64' or not body.get('content'):
        return None
    try:
        return base64.b64decode(body['content']).decode('utf-8', errors='replace')
    except (ValueError, TypeError):
        return None


def blueprint_gaps(gh: Getter, owner_repo: str, ref: str) -> dict[str, Any] | None:
    """Open gap IDs from docs/BLUEPRINT.md and docs/app-blueprint/*.md, or None
    when the repo has no blueprint."""
    docs: dict[str, str] = {}
    single = _file_text(gh, owner_repo, 'docs/BLUEPRINT.md', ref)
    if single is not None:
        docs['BLUEPRINT.md'] = single
    listing = gh(f'/repos/{owner_repo}/contents/docs/app-blueprint?ref={ref}')
    for entry in listing if isinstance(listing, list) else []:
        name = str(entry.get('name', ''))
        if entry.get('type') == 'file' and counts_as_blueprint(name):
            text = _file_text(gh, owner_repo, str(entry.get('path')), ref)
            if text is not None:
                docs[name] = text
    if not docs:
        return None
    return {**parse_gaps(docs), 'files': len(docs)}
