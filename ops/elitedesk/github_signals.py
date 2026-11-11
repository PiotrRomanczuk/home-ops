"""github_signals — daily progress counts for one GitHub repo, for the Postęp tab.

Counts per Warsaw-local day since `since`:
  commits    on the default branch
  pr_opened  / pr_merged (PRs walked newest-updated first, stop past the window)
  deploys    to the "Production" environment (Vercel writes these)
  ci_ok / ci_failed  workflow runs on the default branch
plus a summary for repo_meta: the latest finished CI run and the last deploy.

`get(path)` is github-repo-sync's GitHub GET (parsed JSON or None), so this
module stays network-free and testable with a fake.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Callable, Iterator
from zoneinfo import ZoneInfo

WARSAW = ZoneInfo('Europe/Warsaw')
GH_SIGNALS = ['commits', 'pr_opened', 'pr_merged', 'deploys', 'ci_ok', 'ci_failed']
CI_OK = {'success'}
CI_FAILED = {'failure', 'timed_out', 'startup_failure'}  # cancelled/skipped say nothing
PER_PAGE, MAX_PAGES = 100, 10

Getter = Callable[[str], Any]


def local_day(ts: str | None) -> str | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone(WARSAW).date().isoformat()
    except ValueError:
        return None


def paged(get: Getter, path: str, key: str | None = None) -> Iterator[dict[str, Any]]:
    """Items across pages until a short page, an error, or MAX_PAGES."""
    sep = '&' if '?' in path else '?'
    for page in range(1, MAX_PAGES + 1):
        data = get(f'{path}{sep}per_page={PER_PAGE}&page={page}')
        items = (data or {}).get(key) if key else data
        if not isinstance(items, list):
            return
        yield from items
        if len(items) < PER_PAGE:
            return


def collect(get: Getter, owner_repo: str, branch: str, since: datetime) -> tuple[Counter, dict[str, Any]]:
    """→ (Counter{(day, signal): n}, summary for repo_meta)."""
    first = since.astimezone(WARSAW).date().isoformat()
    since_iso = since.strftime('%Y-%m-%dT%H:%M:%SZ')
    counts: Counter = Counter()

    def add(ts: str | None, signal: str) -> None:
        day = local_day(ts)
        if day and day >= first:
            counts[(day, signal)] += 1

    for c in paged(get, f'/repos/{owner_repo}/commits?sha={branch}&since={since_iso}'):
        add(((c.get('commit') or {}).get('committer') or {}).get('date'), 'commits')

    for pr in paged(get, f'/repos/{owner_repo}/pulls?state=all&sort=updated&direction=desc'):
        if (local_day(pr.get('updated_at')) or '') < first:
            break
        add(pr.get('created_at'), 'pr_opened')
        add(pr.get('merged_at'), 'pr_merged')

    last_deploy = None
    for d in paged(get, f'/repos/{owner_repo}/deployments?environment=Production'):
        last_deploy = last_deploy or d.get('created_at')
        if (local_day(d.get('created_at')) or '') < first:
            break
        add(d.get('created_at'), 'deploys')

    ci = None
    for run in paged(get, f'/repos/{owner_repo}/actions/runs?branch={branch}&created=%3E%3D{first}', key='workflow_runs'):
        conclusion = run.get('conclusion')
        if ci is None and conclusion in CI_OK | CI_FAILED:  # skipped/cancelled say nothing
            ci = {'conclusion': conclusion, 'workflow': run.get('name'), 'at': run.get('created_at'), 'url': run.get('html_url')}
        if conclusion in CI_OK:
            add(run.get('created_at'), 'ci_ok')
        elif conclusion in CI_FAILED:
            add(run.get('created_at'), 'ci_failed')

    return counts, {'ci': ci, 'last_deploy_at': last_deploy}


def to_rows(slug: str, counts: Counter) -> list[dict[str, Any]]:
    return [{'project_slug': slug, 'day': day, 'signal': signal, 'n': n} for (day, signal), n in sorted(counts.items())]
