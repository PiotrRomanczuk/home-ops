"""activity_gha — GitHub Actions jobs that ran on this host's self-hosted runners.

Repos come from the runners themselves (~/actions-runner/*/.runner →
gitHubUrl), so a new runner shows up without config. Talks to GitHub through
the `gh` CLI, which is already logged in on elitedesk — no extra token.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

OK_CONCLUSIONS = {'success', 'skipped', 'neutral'}


def discover_runners(root: Path) -> list[dict[str, str]]:
    """[{name, repo, dir}] for every configured runner under root."""
    out = []
    for cfg in sorted(root.glob('*/.runner')):
        try:
            data = json.loads(cfg.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        url = str(data.get('gitHubUrl') or '').rstrip('/')
        parts = url.split('/')
        if len(parts) >= 2 and data.get('agentName'):
            out.append({'name': data['agentName'], 'repo': f'{parts[-2]}/{parts[-1]}', 'dir': str(cfg.parent)})
    return out


def job_to_run(job: dict[str, Any], wf_run: dict[str, Any], repo: str, runners: set[str]) -> dict[str, Any] | None:
    """One GitHub job → one unit_runs row, or None if it ran elsewhere."""
    if job.get('runner_name') not in runners or not job.get('started_at'):
        return None
    done = job.get('status') == 'completed'
    conclusion = job.get('conclusion') or ''
    branch = wf_run.get('head_branch') or ''
    return {
        'kind': 'gha',
        'unit': f"{wf_run.get('name') or 'workflow'} / {job.get('name') or 'job'}",
        'invocation_id': f"gha:{job['id']}",
        'project_slug': repo.split('/')[-1].lower(),
        'started_at': job['started_at'],
        'finished_at': job.get('completed_at') if done else None,
        'result': ('ok' if conclusion in OK_CONCLUSIONS else 'failed') if done else 'running',
        'url': job.get('html_url'),
        'detail': ' · '.join(x for x in (job.get('runner_name'), branch, wf_run.get('event'), conclusion) if x),
    }


def gh_api(path: str, timeout: float = 30) -> Any:
    try:
        p = subprocess.run(['gh', 'api', path], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)
    except ValueError:
        return None


class GhaPoller:
    """Polls recent workflow runs; a completed run is fetched once and then
    remembered, so a steady state costs one API call per repo."""

    def __init__(self, root: Path, api: Any = gh_api, per_page: int = 20) -> None:
        self.root, self.api, self.per_page = root, api, per_page
        self.finished: set[int] = set()
        self.active: list[dict[str, Any]] = []

    def poll(self) -> list[dict[str, Any]]:
        runners = discover_runners(self.root)
        names = {r['name'] for r in runners}
        out: list[dict[str, Any]] = []
        for repo in sorted({r['repo'] for r in runners}):
            listing = self.api(f'repos/{repo}/actions/runs?per_page={self.per_page}') or {}
            for wf_run in listing.get('workflow_runs') or []:
                if wf_run.get('id') in self.finished:
                    continue
                jobs = (self.api(f"repos/{repo}/actions/runs/{wf_run['id']}/jobs") or {}).get('jobs')
                if jobs is None:
                    continue  # API hiccup — retry next poll
                out += [r for job in jobs if (r := job_to_run(job, wf_run, repo, names))]
                if wf_run.get('status') == 'completed':
                    self.finished.add(wf_run['id'])
        self.active = [r for r in out if r['result'] == 'running']
        return out
