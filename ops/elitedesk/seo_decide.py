#!/usr/bin/env python3
"""seo_decide.py — the weekly SEO PR asks before it lands (ADR 2026-10-13).

Twice a day (seo-decide.timer) and at the start of every seo-improve run:

  1. act on answers: yes → squash-merge the PR, no → close it with the reason
     and send its hypotheses back to 'proposed' (not 'ready', so next week's
     run does not reopen the same change)
  2. ask about every open `seo-auto` PR that has no question waiting yet

The merge itself flips seo_plan in_pr → shipped later (seo_plan_db.mark_shipped_if_merged).
An answer whose action failed stays unconsumed, so the next run retries it.

Env: INGEST_URL + INGEST_TOKEN (seo-collect.env), SEO_SITE_GH_REPO.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agents.routine_report import Reporter  # noqa: E402

ROUTINE = 'seo-improve'
LABEL = 'seo-auto'
REPO = os.environ.get('SEO_SITE_GH_REPO', 'PiotrRomanczuk/gitara-lekcje')
OPTIONS = [{'key': 'yes', 'label': 'Scal'}, {'key': 'no', 'label': 'Odrzuć'}]
EXPIRES_H = 24 * 7  # weekly cadence: the question lives until the next PR

Gh = Callable[[list[str]], str]


def gh(args: list[str]) -> str:
    return subprocess.run(['gh', *args, '-R', REPO], check=True, capture_output=True, text=True).stdout


def open_prs(run: Gh) -> list[dict[str, Any]]:
    out = run(['pr', 'list', '--label', LABEL, '--state', 'open', '--json', 'number,title,url,additions,deletions'])
    return json.loads(out or '[]')


def act(r: Reporter, run: Gh, retire: Callable[[str], None], log: Callable[[str], None]) -> set[str]:
    """Carry out answered decisions. Returns the PR refs acted on (consumed)."""
    done: set[str] = set()
    for d in r.answers():
        pr = str(d.get('ref') or '')
        try:
            if not pr.isdigit():
                log(f'decision {d["id"]}: no PR ref — consuming without action')
            elif d.get('answer') == 'yes':
                run(['pr', 'merge', pr, '--squash', '--delete-branch'])
                log(f'PR #{pr} merged (decision {d["id"]})')
            else:
                why = d.get('reason') or 'bez powodu'
                run(['pr', 'close', pr, '--delete-branch', '--comment', f'Odrzucone w home-ops Decisions: {why}'])
                retire(d.get('context_url') or '')
                log(f'PR #{pr} closed: {why} (decision {d["id"]})')
        except subprocess.CalledProcessError as e:
            log(f'PR #{pr}: gh failed ({(e.stderr or "").strip()[:200]}) — will retry next run')
            continue
        r.consume(d['id'])
        done.add(pr)
    return done


def ask(r: Reporter, prs: list[dict[str, Any]], log: Callable[[str], None], skip: set[str] = frozenset()) -> int:
    """File one question per open PR that is not already waiting. `skip` = refs
    just merged/closed this run: GitHub's PR list lags, a merged PR can still
    show as open seconds later (2026-10-21, PR #9 asked twice)."""
    waiting = r.open_refs() | {str(d.get('ref')) for d in r.answers()} | set(skip)
    asked = 0
    for p in prs:
        ref = str(p['number'])
        if ref in waiting:
            continue
        r.ask(f'Scalić PR SEO #{ref}? „{p["title"]}”', options=OPTIONS, ref=ref, slug='gitara-lekcje',
              context_url=p['url'], detail=f'+{p.get("additions", 0)} / −{p.get("deletions", 0)} linii. '
              'Tak = squash-merge i deploy przez Vercel. Nie = zamknięcie PR, hipotezy wracają do „proposed”.',
              expires_hours=EXPIRES_H)
        log(f'asked about PR #{ref}')
        asked += 1
    return asked


def retire_plan(pr_url: str) -> None:
    if not pr_url:
        return
    from seo_db import psql_exec
    psql_exec("UPDATE seo_plan SET status = 'proposed', pr_url = NULL, updated_at = now() "
              "WHERE pr_url = :'u' AND status = 'in_pr';", {'u': pr_url})


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    r = Reporter.from_env(ROUTINE)
    log = lambda m: print(f'seo-decide: {m}', file=sys.stderr)  # noqa: E731
    acted = act(r, gh, retire_plan, log)
    asked = ask(r, open_prs(gh), log, acted)
    log(f'acted on {len(acted)}, asked {asked}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
