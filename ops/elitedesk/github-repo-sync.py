#!/usr/bin/env python3
"""github-repo-sync.py — pulls stack/version/deploy/git metadata for Piotr's
other MainCV projects and syncs it into home-ops via POST /api/projects/repo-sync.

Runs on elitedesk only (no Mac dependency) via github-repo-sync.timer, every
4h. Reads github-repo-sync.projects.json (vault slug -> where to find data):
  - owner_repo: calls the GitHub REST API (repo metadata, commits since 30d,
    package.json contents for version/deps; releases/tags as the version
    fallback for manifest-less stacks like .NET).
  - local_git_dir: runs `git --git-dir=<path> log` directly instead — used
    for repos whose remote is itself an elitedesk-local bare repo (stano),
    not GitHub.
  - unsupported: recorded as-is, no network/git call attempted.

Also HEAD/GET-checks each mapped deploy_url for reachability. That check
runs here — not on Piotr's Mac — specifically so a deploy's status never
flaps with his laptop's sleep/wake state (see docs/manual-tests for the
2026-07-16 write-up of this decision).

/api/projects/repo-sync is UPDATE-only: a slug absent from the vault-synced
projects table is reported back in `unknownSlugs`, never inserted.

Env:
  GITHUB_TOKEN   PAT with read access to the owner's repos (including
                 private ones). Optional but strongly recommended — without
                 it, GitHub's anonymous rate limit (60/hr) and private-repo
                 404s will silently degrade most entries to {"error": ...}.
  INGEST_URL     (required) e.g. http://127.0.0.1:64421/api/ingest
  INGEST_TOKEN   (required) shared secret, same one every other agent uses.
  PROJECTS_JSON  path to the mapping file, defaults to
                 github-repo-sync.projects.json next to this script.
  HOST_NAME      defaults to 'elitedesk'

Exit code: 0 if the batch POST to repo-sync succeeded — even if individual
projects were unsupported or had a fetch error, since those are recorded
in repo_meta rather than treated as fatal. Non-zero only on a hard
config/transport error (mapping file missing, repo-sync POST itself failed).
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent.parent))
from agents._common import IngestClient, check_url  # noqa: E402

HOST_NAME = os.environ.get('HOST_NAME', 'elitedesk')
PROJECTS_JSON = Path(os.environ.get('PROJECTS_JSON') or (_here / 'github-repo-sync.projects.json'))
GITHUB_API = 'https://api.github.com'
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')

ic = IngestClient.from_env(host=HOST_NAME, source='agent:github-repo-sync', timeout=15)
INGEST_BASE = ic.events_url.replace('/api/ingest', '').rstrip('/')
REPO_SYNC_URL = INGEST_BASE + '/api/projects/repo-sync'


def post_log(level: str, message: str, data: dict[str, Any] | None = None) -> None:
    ic.post_log(level, message, data)


# ── GitHub API ───────────────────────────────────────────────────────────

def _gh_headers() -> dict[str, str]:
    headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
    if GITHUB_TOKEN:
        headers['Authorization'] = f'Bearer {GITHUB_TOKEN}'
    return headers


def _gh_request(path: str) -> Any:
    """GET against the GitHub REST API. Returns parsed JSON, or None on any
    error (404, rate limit, network) — callers treat that as 'no data', not
    fatal, since one project's API hiccup shouldn't drop the whole sync."""
    req = urllib.request.Request(f'{GITHUB_API}{path}', headers=_gh_headers())
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def _gh_commits_30d(owner_repo: str) -> tuple[int, str | None]:
    # First page only (100/page) — fine for personal projects, which never
    # hit 100 commits in 30 days; not worth the pagination complexity here.
    since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
    commits = _gh_request(f'/repos/{owner_repo}/commits?since={since}&per_page=100')
    if not isinstance(commits, list):
        return 0, None
    last_commit = None
    if commits:
        newest = commits[0].get('commit', {}).get('committer', {}).get('date')
        last_commit = newest[:10] if newest else None
    return len(commits), last_commit


def _gh_package_json_version(owner_repo: str) -> tuple[str | None, list[str]]:
    data = _gh_request(f'/repos/{owner_repo}/contents/package.json')
    if not isinstance(data, dict) or 'content' not in data:
        return None, []
    try:
        pkg = json.loads(base64.b64decode(data['content']).decode('utf-8'))
    except (ValueError, json.JSONDecodeError):
        return None, []
    return pkg.get('version'), list(pkg.get('dependencies', {}).keys())[:8]


def _gh_latest_release_or_tag(owner_repo: str) -> str | None:
    # .NET projects here have no single manifest version field — fall back
    # to the latest GitHub release, then the latest tag.
    rel = _gh_request(f'/repos/{owner_repo}/releases/latest')
    if isinstance(rel, dict) and rel.get('tag_name'):
        return rel['tag_name']
    tags = _gh_request(f'/repos/{owner_repo}/tags?per_page=1')
    if isinstance(tags, list) and tags:
        return tags[0].get('name')
    return None


def sync_via_github(cfg: dict[str, Any]) -> dict[str, Any]:
    owner_repo = cfg['owner_repo']
    manifest = cfg.get('manifest', 'node')
    repo = _gh_request(f'/repos/{owner_repo}')
    if repo is None:
        return {
            'source': 'github-api',
            'github_repo': owner_repo,
            'error': f'GET /repos/{owner_repo} failed (rate-limited, private+no token, or renamed)',
        }

    commits_30d, last_commit = _gh_commits_30d(owner_repo)
    version: str | None = None
    key_deps: list[str] = []
    if manifest == 'node':
        version, key_deps = _gh_package_json_version(owner_repo)
    elif manifest == 'dotnet':
        version = _gh_latest_release_or_tag(owner_repo)
    # manifest in ('python', 'none'): no generic single-file version fetch
    # attempted — a second API call to parse pyproject.toml isn't worth it
    # for a job whose main value here is git activity + deploy reachability.

    meta: dict[str, Any] = {
        'source': 'github-api',
        'github_repo': owner_repo,
        'git': {'last_commit': last_commit, 'commits_30d': commits_30d},
    }
    if manifest != 'none':
        meta['stack'] = {'runtime': manifest, 'key_deps': key_deps}
    if version:
        meta['version'] = version
    return meta


# ── local git (e.g. stano's bare repo already on elitedesk) ──────────────

def sync_via_local_git(cfg: dict[str, Any]) -> dict[str, Any]:
    git_dir = cfg['local_git_dir']
    if not Path(git_dir).exists():
        return {'source': 'local-git', 'error': f'local_git_dir not found: {git_dir}'}

    since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y-%m-%d')
    commits_r = subprocess.run(
        ['git', '--git-dir', git_dir, 'log', f'--since={since}', '--oneline'],
        capture_output=True, text=True, timeout=15,
    )
    commits_30d = len(commits_r.stdout.splitlines()) if commits_r.returncode == 0 else 0

    last_r = subprocess.run(
        ['git', '--git-dir', git_dir, 'log', '-1', '--format=%cd', '--date=short'],
        capture_output=True, text=True, timeout=15,
    )
    last_commit = last_r.stdout.strip() or None if last_r.returncode == 0 else None

    return {'source': 'local-git', 'git': {'last_commit': last_commit, 'commits_30d': commits_30d}}


# ── deploy reachability ────────────────────────────────────────────────

def check_deploy(url: str) -> dict[str, Any]:
    """Reachability verdict for a deploy URL, via the shared _common.check_url
    probe (also used by rpi-sentinel's second vantage point, so both probers
    agree on what "reachable" means). Deliberately runs from elitedesk
    (always-on) rather than a Mac watcher — see module docstring — so
    reachability never flaps with a laptop's sleep/wake state."""
    reachable, status_code = check_url(url, timeout=10)
    return {
        'url': url,
        'reachable': reachable,
        'status_code': status_code,
        'checked_at': datetime.now(timezone.utc).isoformat(),
    }


# ── dispatch + main ──────────────────────────────────────────────────────

def load_mapping(path: Path) -> dict[str, dict[str, Any]]:
    mapping = json.loads(path.read_text(encoding='utf-8'))
    return {k: v for k, v in mapping.items() if not k.startswith('_')}


def build_repo_meta(cfg: dict[str, Any]) -> dict[str, Any]:
    if 'unsupported' in cfg:
        meta: dict[str, Any] = {'source': 'github-api', 'unsupported': cfg['unsupported']}
    elif 'local_git_dir' in cfg:
        meta = sync_via_local_git(cfg)
    elif 'owner_repo' in cfg:
        meta = sync_via_github(cfg)
    else:
        meta = {'source': 'github-api', 'error': 'mapping entry has no owner_repo/local_git_dir/unsupported'}

    if cfg.get('deploy_url'):
        meta['deploy'] = check_deploy(cfg['deploy_url'])
    return meta


def main() -> int:
    if not PROJECTS_JSON.is_file():
        post_log('error', f'projects mapping not found: {PROJECTS_JSON}')
        return 1
    mapping = load_mapping(PROJECTS_JSON)

    if not GITHUB_TOKEN:
        post_log('warn', 'GITHUB_TOKEN not set — GitHub-hosted projects will fail rate-limited/private lookups')

    entries = []
    for slug, cfg in mapping.items():
        try:
            meta = build_repo_meta(cfg)
        except Exception as e:  # noqa: BLE001 — one project's bug must not drop the batch
            meta = {'source': 'github-api', 'error': str(e)[:300]}
        entries.append({'slug': slug, 'repo_meta': meta, 'source': meta.get('source', 'github-api')})

    status, body = ic.request(REPO_SYNC_URL, {'entries': entries})
    if not (200 <= status < 300):
        post_log('error', f'repo-sync POST failed: status={status}', {'body': body})
        return 1

    updated = (body or {}).get('updated', 0)
    unknown = (body or {}).get('unknownSlugs', [])
    print(f'synced {updated}/{len(entries)} projects' + (f' (unknown slugs: {unknown})' if unknown else ''))
    if unknown:
        post_log('warn', f'repo-sync: slugs not found in projects table: {unknown}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
