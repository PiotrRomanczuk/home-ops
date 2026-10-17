#!/usr/bin/env python3
"""brief-pull — mirror day briefs from the daily-brief repo into home-ops.

A cloud routine commits briefs/YYYY-MM-DD-<slot>.md to the private GitHub repo
PiotrRomanczuk/daily-brief. The console API is LAN/Tailscale-only, so this
host pulls instead: `git pull --ff-only`, then every brief file added or
changed since the last processed commit is POSTed to /api/briefs (upsert on
date+slot, so re-sending is harmless). The state file only advances when every
file went through; a failed POST (network, 5xx) is retried on the next tick (every 15 min).

Env (systemd EnvironmentFile ~/.config/home-ops/brief-pull.env):
  BRIEF_REPO_DIR   clone path            default ~/code/daily-brief
  BRIEF_REPO_URL   remote for first clone default git@github-daily-brief:PiotrRomanczuk/daily-brief.git
  BRIEF_STATE      last processed commit default ~/.local/state/home-ops/brief-pull.state
  BRIEF_MAX_DAYS   first-run backfill window (days) default 120
  INGEST_URL, INGEST_TOKEN  falls back to ~/.config/elitedesk-watcher.env, like daily-digest.sh
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))
sys.path.insert(0, str(_here.parent.parent))
from agents._common import IngestClient  # noqa: E402
from brief_parse import NAME_RE, BriefError, brief_payload  # noqa: E402

HOME = Path.home()
REPO = Path(os.environ.get('BRIEF_REPO_DIR') or HOME / 'code' / 'daily-brief')
REMOTE = os.environ.get('BRIEF_REPO_URL') or 'git@github-daily-brief:PiotrRomanczuk/daily-brief.git'
STATE = Path(os.environ.get('BRIEF_STATE') or HOME / '.local' / 'state' / 'home-ops' / 'brief-pull.state')
MAX_DAYS = int(os.environ.get('BRIEF_MAX_DAYS', '120'))
WATCHER_ENV = Path(os.environ.get('DIGEST_API_ENV') or HOME / '.config' / 'elitedesk-watcher.env')


def load_watcher_env() -> None:
    """Borrow INGEST_URL / INGEST_TOKEN from the watcher's env file if unset."""
    if (os.environ.get('INGEST_URL') and os.environ.get('INGEST_TOKEN')) or not WATCHER_ENV.is_file():
        return
    for line in WATCHER_ENV.read_text().splitlines():
        k, sep, v = line.strip().partition('=')
        if sep and k in ('INGEST_URL', 'INGEST_TOKEN') and not os.environ.get(k):
            os.environ[k] = v.strip().strip('"\'')


def git(*args: str) -> str:
    r = subprocess.run(['git', '-C', str(REPO), *args], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f'git {" ".join(args)}: {r.stderr.strip()[:300]}')
    return r.stdout.strip()


def sync_repo() -> str:
    """Clone on first run, else fast-forward. Returns HEAD."""
    if not (REPO / '.git').is_dir():
        REPO.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'clone', '--quiet', REMOTE, str(REPO)], check=True, timeout=300)
    else:
        git('pull', '--ff-only', '--quiet')
    return git('rev-parse', 'HEAD')


def changed_files(last: str | None, head: str) -> list[str]:
    """Brief files touched since `last`; everything recent when there is no usable `last`."""
    if last:
        try:
            git('cat-file', '-e', f'{last}^{{commit}}')
            out = git('diff', '--name-only', '--diff-filter=AM', last, head, '--', 'briefs/')
            return sorted(p for p in out.splitlines() if NAME_RE.match(p))
        except RuntimeError:
            pass  # history rewritten or state corrupt → full rescan (idempotent)
    cutoff = (date.today() - timedelta(days=MAX_DAYS)).isoformat()
    names = git('ls-files', '--', 'briefs/').splitlines()
    return sorted(p for p in names if (m := NAME_RE.match(p)) and m.group(1) >= cutoff)


def push_files(ic: IngestClient, url: str, files: list[str]) -> int:
    """POST each file; returns the number of retryable failures.

    A file that breaks the contract (parse error, HTTP 400) is logged and
    skipped — retrying it every 15 min would only repeat the error until the
    routine rewrites it, which shows up as a new commit anyway."""
    retry = 0
    for rel in files:
        try:
            body = brief_payload(rel, (REPO / rel).read_text(encoding='utf-8'))
        except (BriefError, OSError, UnicodeDecodeError) as e:
            ic.post_log('error', f'brief-pull: skipped {rel}: {e}')
            continue
        status, resp = ic.request(url, body, timeout=20)
        if 200 <= status < 300:
            print(f'{rel}: {"inserted" if (resp or {}).get("inserted") else "updated"}')
            continue
        ic.post_log('error', f'brief-pull: POST {rel} → {status} {(resp or {}).get("error", "")}'.strip())
        if status != 400:
            retry += 1
    return retry


def main() -> int:
    load_watcher_env()
    ic = IngestClient.from_env(host=os.environ.get('HOST_NAME', 'elitedesk'), source='agent:brief-pull', timeout=20)
    url = ic.events_url.replace('/api/ingest', '/api/briefs')
    try:
        head = sync_repo()
    except (RuntimeError, subprocess.SubprocessError) as e:
        ic.post_log('error', f'brief-pull: git failed: {e}')
        return 1
    last = STATE.read_text().strip() if STATE.is_file() else None
    if last == head:
        return 0
    files = changed_files(last, head)
    failures = push_files(ic, url, files)
    if failures:
        print(f'{failures} of {len(files)} briefs failed (retryable); state not advanced', file=sys.stderr)
        return 1
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(head + '\n')
    print(f'{len(files)} brief files processed at {head[:7]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
