#!/usr/bin/env python3
"""flow_ops.py — git/gh steps shared by the jobs of .github/workflows/flow.yml (CLI: flow_cli.py).

HAS_FLOW_TOKEN: checkout and gh use secrets.FLOW_TOKEN. Its pushes start `check` by themselves and may
change .github/workflows. GITHUB_TOKEN pushes do neither: without the token `check` is dispatched, and
a refused workflow change becomes one issue with the manual push.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from typing import Callable, NamedTuple

REFUSED = re.compile(r'refusing to allow .*workflow', re.I | re.S)


class Res(NamedTuple):
    rc: int
    out: str
    err: str


Run = Callable[[list[str]], Res]


def sh(args: list[str]) -> Res:
    p = subprocess.run(args, capture_output=True, text=True)
    return Res(p.returncode, p.stdout, p.stderr)


class Flow:
    def __init__(self, run: Run, has_token: bool, run_url: str, repo: str) -> None:
        self.run, self.has_token, self.run_url, self.repo = run, has_token, run_url, repo

    def ok(self, args: list[str]) -> str:
        res = self.run(args)
        if res.rc:
            raise RuntimeError(f'{" ".join(args[:3])}: {res.err.strip()}')
        return res.out

    def issue(self, title: str, body: str, label: str | None = None, refresh: bool = False) -> None:
        """One open issue per title, so a failure that repeats on every run does not pile up."""
        listed = json.loads(self.ok(['gh', 'issue', 'list', '--state', 'open', '--limit', '200',
                                     '--json', 'number,title']) or '[]')
        same = [str(i['number']) for i in listed if i['title'] == title]
        if same:
            print(f'issue #{same[0]} already open: {title}')
            if refresh:
                self.ok(['gh', 'issue', 'edit', same[0], '--body', body])
            return
        self.ok(['gh', 'issue', 'create', '--title', title, '--body', body, *(['--label', label] if label else [])])

    def dispatch(self, ref: str) -> None:
        if not self.has_token:  # a FLOW_TOKEN push already started `check`
            self.ok(['gh', 'workflow', 'run', 'check.yml', '--ref', ref])

    def head(self) -> str:
        return self.ok(['git', 'rev-parse', 'HEAD']).strip()

    def merge(self, ref: str) -> bool:
        if self.run(['git', 'merge', '--no-edit', ref]).rc == 0:
            return True
        self.run(['git', 'merge', '--abort'])
        return False

    def push(self, target: str, source: str) -> bool:
        """Push HEAD to target; if target moved meanwhile, merge it in and try once more."""
        for attempt in range(2):
            res = self.run(['git', 'push', 'origin', f'HEAD:{target}'])
            if res.rc == 0:
                return True
            print(res.err, file=sys.stderr)
            if REFUSED.search(res.err):
                self.refused(target, source)
                return False
            if attempt or self.run(['git', 'fetch', 'origin', target]).rc or not self.merge(f'origin/{target}'):
                return False
        return False

    def refused(self, target: str, source: str) -> None:
        why = ('FLOW_TOKEN nie ma uprawnienia workflows (write)' if self.has_token
               else 'sekret FLOW_TOKEN nie jest ustawiony, a GITHUB_TOKEN nie może zmieniać .github/workflows')
        self.issue(f'flow: {source} → {target} wymaga ręcznego pushu (zmiana w workflows)', (
            f'Push na `{target}` odrzucony: {why} ({self.run_url}).\n\n'
            f'Ręcznie (Mac, poza Actions):\n```bash\ngit fetch origin\n'
            f'git push origin origin/{source}:{target}   # gdy {target} jest przodkiem {source}\n'
            f'# inaczej: git checkout {target} && git merge --ff-only origin/{target} && '
            f'git merge --no-edit origin/{source} && git push origin {target}\n```\n'
            'Na stałe: sekret FLOW_TOKEN (docs/RUNBOOK.md, sekcja Branches). Zamknij issue po pushu.'))

    def advance(self, source: str, target: str) -> int:
        """Merge origin/<source> into the checked-out <target> and push (promote dev → test, sync main → dev)."""
        before = self.head()
        if not self.merge(f'origin/{source}'):
            self.issue(f'flow: {source} nie wchodzi czysto na {target}',
                       f'Konflikt przy scalaniu {source} → {target} ({self.run_url}). Rozwiąż przez PR do dev.',
                       'back-to-dev')
            return 1
        if self.head() == before:
            print(f'{target} already has {source}')
            return 0
        if not self.push(target, source):
            return 1
        self.dispatch(target)
        return 0
