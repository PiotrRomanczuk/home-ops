"""gpu_jobs.py — the fixed GPU job list and how far it got.

The list (gpu-jobs.json, root-owned: an agent running as the user cannot edit it, but the commands it
names may still run code from directories the user can write to, e.g. worktrees):

    [{"name": "s2l-strummy",
      "argv": ["/opt/homebrew/bin/uv", "run", "--project", "~/code/…", "song2logic", "study", "…",
               "--shard", "{shard}/{shards}"],
      "cwd": "~/code/…", "env": {"KEY": "value"}, "shards": 2, "unload_ollama": false}, …]

argv is run without a shell; `~` at the start of an item and of cwd is expanded, `{shard}` and
`{shards}` are filled in per shard. Jobs run strictly in list order. Progress (done shards, failure
counts) lives in STATE/gpu/progress.json, so a restart skips what is finished.
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any

MAX_FAILS = 3


def load(path: Path) -> list[dict[str, Any]]:
    jobs = json.loads(path.read_text())
    names = set()
    for job in jobs:
        if not job.get('name') or job['name'] in names:
            raise ValueError(f'job without a unique name: {job!r}')
        if not (isinstance(job.get('argv'), list) and job['argv'] and all(isinstance(a, str) for a in job['argv'])):
            raise ValueError(f'{job["name"]}: argv must be a non-empty list of strings')
        names.add(job['name'])
        job['shards'] = max(1, int(job.get('shards', 1)))
        job['cwd'] = os.path.expanduser(job.get('cwd') or '~')
        job['env'] = {str(k): str(v) for k, v in (job.get('env') or {}).items()}
    return jobs


def argv_for(job: dict[str, Any], shard: int) -> list[str]:
    return [os.path.expanduser(a).replace('{shard}', str(shard)).replace('{shards}', str(job['shards']))
            for a in job['argv']]


class Progress:
    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            data = json.loads(path.read_text())
        except (FileNotFoundError, ValueError):
            data = {}
        self.done: dict[str, list[int]] = data.get('done', {})
        self.fails: dict[str, int] = data.get('fails', {})

    def save(self) -> None:
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'done': self.done, 'fails': self.fails}, indent=1))
        tmp.replace(self.path)

    def shard_done(self, job: dict[str, Any], shard: int) -> bool:
        return shard in self.done.get(job['name'], [])

    def mark_done(self, job: dict[str, Any], shard: int) -> None:
        self.done.setdefault(job['name'], []).append(shard)
        self.save()

    def fail(self, job: dict[str, Any], shard: int) -> int:
        key = f'{job["name"]}.{shard}'
        self.fails[key] = self.fails.get(key, 0) + 1
        self.save()
        return self.fails[key]

    def job_finished(self, job: dict[str, Any]) -> bool:
        gave_up = any(self.fails.get(f'{job["name"]}.{n}', 0) >= MAX_FAILS for n in range(1, job['shards'] + 1))
        return gave_up or all(self.shard_done(job, n) for n in range(1, job['shards'] + 1))

    def current(self, jobs: list[dict[str, Any]]) -> dict[str, Any] | None:
        return next((job for job in jobs if not self.job_finished(job)), None)


def unload_ollama(base: str = 'http://127.0.0.1:11434') -> list[str]:
    """Ask Ollama to drop every loaded model (keep_alive 0), so the next job gets the memory."""
    try:
        with urllib.request.urlopen(f'{base}/api/ps', timeout=10) as r:
            names = [m['name'] for m in json.load(r).get('models', [])]
        for name in names:
            body = json.dumps({'model': name, 'keep_alive': 0}).encode()
            req = urllib.request.Request(f'{base}/api/generate', data=body, headers={'Content-Type': 'application/json'})
            urllib.request.urlopen(req, timeout=60).read()
        return names
    except (OSError, ValueError, KeyError):
        return []
