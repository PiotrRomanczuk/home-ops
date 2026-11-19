#!/usr/bin/env python3
"""flow_cli.py — what the jobs of .github/workflows/flow.yml run (git/gh helpers: flow_ops.py).

    flow_cli.py advance --source dev --target test [--sha S]  # merge S (default origin/dev) into the checked-out test, push
    flow_cli.py tester --sha <head sha>              # merge a green tests-only PR into test, tests to dev
    flow_cli.py release --sha <green test sha>       # open or refresh the PR test → main (aborts if test moved on)
    flow_cli.py red --sha <sha> --run-url <url>      # test is red: one back-to-dev issue, refreshed each time
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flow_ops import Flow, sh  # noqa: E402
from flow_paths import tests_only  # noqa: E402

RELEASE = 'release: test → main'
RED = 'flow: test czerwony — poprawka na dev'


def tester(flow: Flow, sha: str) -> int:
    """A green PR into test that touches only test files merges, then test flows back to dev."""
    prs = json.loads(flow.ok(['gh', 'pr', 'list', '--base', 'test', '--state', 'open',
                              '--json', 'number,headRefOid']) or '[]')
    num = next((str(p['number']) for p in prs if p['headRefOid'] == sha), '')
    if not num:
        print('not an open PR into test')
        return 0
    if not tests_only(flow.ok(['gh', 'pr', 'view', num, '--json', 'files', '--jq', '.files[].path']).splitlines()):
        print(f'PR #{num} touches non-test files — waits for a human')
        return 0
    flow.ok(['git', 'fetch', 'origin', 'dev', 'test'])
    flow.ok(['git', 'checkout', '-B', 'dev', 'origin/dev'])
    flow.ok(['gh', 'pr', 'merge', num, '--merge', '--delete-branch', '--match-head-commit', sha])
    flow.dispatch('test')
    flow.ok(['git', 'fetch', 'origin', 'test'])
    return flow.advance('test', 'dev')


def red(flow: Flow, sha: str, run_url: str) -> int:
    """One open issue for a red test; SHA and run link go in the body, refreshed on every red run."""
    flow.issue(RED, f'Testy na gałęzi test nie przeszły: {run_url}\nCommit: {sha}\n'
               'Promocja do main stoi. Poprawka idzie przez PR do dev (testy z test są już na dev).',
               'back-to-dev', refresh=True)
    return 0


def release(flow: Flow, sha: str) -> int:
    """test green, ahead of main and with a different tree → one PR test → main, refreshed each run."""
    if flow.head() != sha:
        print(f'test moved past the green {sha[:7]} — the run of the newer commit decides')
        return 0
    ahead = int(flow.ok(['git', 'rev-list', '--count', 'origin/main..HEAD']))
    if not ahead or flow.run(['git', 'diff', '--quiet', 'origin/main', 'HEAD']).rc == 0:
        print('test brings nothing new to main')  # e.g. only the merge commits of a main → dev sync
        return 0
    n = flow.ok(['git', 'rev-list', '--count', '--no-merges', 'origin/main..HEAD']).strip()
    log = flow.ok(['git', 'log', '--no-merges', '--format=- %s', 'origin/main..HEAD']).splitlines()[:40]
    body = (f'Promocja test → main: {n} commitów, testy zielone ({flow.run_url}).\n'
            'Scalać commitem merge (nie squash), gałęzi test nie usuwać.\n\n' + '\n'.join(log))
    open_prs = json.loads(flow.ok(['gh', 'pr', 'list', '--base', 'main', '--head', 'test', '--state', 'open',
                                   '--json', 'number']) or '[]')
    if open_prs:
        flow.ok(['gh', 'pr', 'edit', str(open_prs[0]['number']), '--body', body])
        return 0
    res = flow.run(['gh', 'pr', 'create', '--base', 'main', '--head', 'test', '--title', RELEASE, '--body', body])
    if res.rc == 0:
        return 0
    if 'not permitted to create' not in res.err:
        print(res.err, file=sys.stderr)
        return 1
    flow.issue(f'{RELEASE}: otwórz PR ręcznie', 'Actions nie może otwierać PR-ów w tym repo. Otwórz ręcznie: '
               f'https://github.com/{flow.repo}/compare/main...test\n\n{body}', refresh=True)
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or '').splitlines()[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    adv = sub.add_parser('advance')
    adv.add_argument('--source', required=True)
    adv.add_argument('--target', required=True)
    adv.add_argument('--sha', default='')
    sub.add_parser('tester').add_argument('--sha', required=True)
    sub.add_parser('release').add_argument('--sha', required=True)
    rd = sub.add_parser('red')
    rd.add_argument('--sha', required=True)
    rd.add_argument('--run-url', required=True)
    a = ap.parse_args(argv)
    env = os.environ
    repo = env.get('GITHUB_REPOSITORY', '')
    run_url = f'{env.get("GITHUB_SERVER_URL", "https://github.com")}/{repo}/actions/runs/{env.get("GITHUB_RUN_ID", "")}'
    flow = Flow(sh, env.get('HAS_FLOW_TOKEN') == 'true', run_url, repo)
    if a.cmd == 'advance':
        return flow.advance(a.source, a.target, a.sha)
    if a.cmd == 'red':
        return red(flow, a.sha, a.run_url)
    return tester(flow, a.sha) if a.cmd == 'tester' else release(flow, a.sha)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
