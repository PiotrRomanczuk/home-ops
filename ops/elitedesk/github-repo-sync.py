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

Projects come from the vault (frontmatter `repo:` via GET /api/projects,
owner GITHUB_OWNER unless the value has a slash) merged with the JSON mapping,
whose entries win (deploy_url, manifest, local_git_dir, unsupported). For
every GitHub project it also counts daily progress over PROGRESS_DAYS
(github_signals.py) and REPLACES that window in /api/progress/signals, and
puts the latest CI run + last Production deploy into repo_meta.

Env:
  GITHUB_TOKEN   PAT with read access to the owner's repos (including
                 private ones). Optional: when unset, `gh auth token` is used
                 (gh is logged in on elitedesk), else anonymous (60/hr).
  GITHUB_OWNER   default PiotrRomanczuk
  PROGRESS_DAYS  default 84 (12 weeks)
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
sys.path.insert(0, str(_here))
from agents._common import IngestClient, check_url  # noqa: E402
from github_signals import GH_SIGNALS, collect, to_rows  # noqa: E402
from repo_projects import merged_mapping, vault_entries  # noqa: E402

HOST_NAME = os.environ.get('HOST_NAME', 'elitedesk')
PROJECTS_JSON = Path(os.environ.get('PROJECTS_JSON') or (_here / 'github-repo-sync.projects.json'))
GITHUB_API = 'https://api.github.com'
GITHUB_OWNER = os.environ.get('GITHUB_OWNER', 'PiotrRomanczuk')
PROGRESS_DAYS = int(os.environ.get('PROGRESS_DAYS', '84'))


def _token() -> str:
    if os.environ.get('GITHUB_TOKEN'):
        return os.environ['GITHUB_TOKEN']
    try:
        p = subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return p.stdout.strip() if p.returncode == 0 else ''


GITHUB_TOKEN = _token()

ic = IngestClient.from_env(host=HOST_NAME, source='agent:github-repo-sync', timeout=15)
INGEST_BASE = ic.events_url.replace('/api/ingest', '').rstrip('/')
REPO_SYNC_URL = INGEST_BASE + '/api/projects/repo-sync'
SIGNALS_URL = INGEST_BASE + '/api/progress/signals'


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
        'default_branch': repo.get('default_branch') or 'main',
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


def vault_projects() -> dict[str, dict[str, Any]]:
    req = urllib.request.Request(INGEST_BASE + '/api/projects', headers={'X-Ingest-Token': ic.token})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return vault_entries(json.loads(r.read()).get('projects') or [], GITHUB_OWNER)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return {}


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


def post_signals(rows: list[dict[str, Any]], projects: list[str], since: datetime) -> None:
    today = datetime.now(timezone.utc).astimezone().date().isoformat()
    replace = {'from': since.astimezone().date().isoformat(), 'to': today, 'projects': projects, 'signals': GH_SIGNALS}
    status, body = ic.request(SIGNALS_URL, {'rows': rows, 'replace': replace}, timeout=30)
    if not (200 <= status < 300):
        post_log('error', f'progress signals POST failed: status={status}', {'body': body})


def main() -> int:
    if not PROJECTS_JSON.is_file():
        post_log('error', f'projects mapping not found: {PROJECTS_JSON}')
        return 1
    mapping = merged_mapping(load_mapping(PROJECTS_JSON), vault_projects())

    if not GITHUB_TOKEN:
        post_log('warn', 'no GITHUB_TOKEN and `gh auth token` failed — GitHub lookups run anonymously')

    since = datetime.now(timezone.utc) - timedelta(days=PROGRESS_DAYS)
    entries, rows, counted = [], [], []
    for slug, cfg in sorted(mapping.items()):
        try:
            meta = build_repo_meta(cfg)
            if meta.get('github_repo') and 'error' not in meta:
                counts, summary = collect(_gh_request, meta['github_repo'], meta['default_branch'], since)
                meta.update(summary)
                rows += to_rows(slug, counts)
                counted.append(slug)
        except Exception as e:  # noqa: BLE001 — one project's bug must not drop the batch
            meta = {'source': 'github-api', 'error': str(e)[:300]}
        entries.append({'slug': slug, 'repo_meta': meta, 'source': meta.get('source', 'github-api')})

    status, body = ic.request(REPO_SYNC_URL, {'entries': entries})
    if not (200 <= status < 300):
        post_log('error', f'repo-sync POST failed: status={status}', {'body': body})
        return 1
    if counted:
        post_signals(rows, counted, since)

    updated = (body or {}).get('updated', 0)
    unknown = (body or {}).get('unknownSlugs', [])
    print(f'synced {updated}/{len(entries)} projects, {len(rows)} progress rows for {len(counted)} repos'
          + (f' (unknown slugs: {unknown})' if unknown else ''))
    if unknown:
        post_log('warn', f'repo-sync: slugs not found in projects table: {unknown}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
