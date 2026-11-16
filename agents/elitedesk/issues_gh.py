"""GitHub REST calls for the issues pilot (see issues_md.py): list open
issues of a repo and close/reopen one. Token: GITHUB_TOKEN, else
`gh auth token` (gh is logged in on elitedesk), else anonymous.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from typing import Any

GITHUB_API = 'https://api.github.com'


_token_cache = ''


def _token() -> str:
    """GITHUB_TOKEN, else `gh auth token` (gh is logged in on elitedesk).
    Only a non-empty token is cached: a failed first lookup is retried."""
    global _token_cache
    if _token_cache:
        return _token_cache
    token = os.environ.get('GITHUB_TOKEN', '')
    if not token:
        try:
            p = subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True, timeout=10)
            token = p.stdout.strip() if p.returncode == 0 else ''
        except (OSError, subprocess.TimeoutExpired):
            token = ''
    _token_cache = token
    return token


def _gh(method: str, url: str, payload: dict[str, Any] | None = None) -> tuple[Any, str]:
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'home-ops-planner-sync'}
    if _token():
        headers['Authorization'] = f'Bearer {_token()}'
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b'null'), r.headers.get('Link') or ''


def fetch_open_issues(repo: str) -> list[dict[str, Any]] | None:
    """All open issues (PRs included — the caller filters). None on error."""
    url, items = f'{GITHUB_API}/repos/{repo}/issues?state=open&per_page=100', []
    try:
        while url:
            page, link = _gh('GET', url)
            if not isinstance(page, list):
                return None
            items.extend(page)
            nxt = re.search(r'<([^>]+)>;\s*rel="next"', link)
            url = nxt.group(1) if nxt else ''
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return items


def set_issue_state(repo: str, number: int, done: bool) -> bool:
    if not _token():
        return False  # anonymous PATCH can only fail
    payload = {'state': 'closed', 'state_reason': 'completed'} if done else {'state': 'open'}
    try:
        _gh('PATCH', f'{GITHUB_API}/repos/{repo}/issues/{number}', payload)
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return True
