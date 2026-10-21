#!/usr/bin/env python3
"""pr_decide.py — every open PR on Piotr's GitHub becomes a Decisions question.

Twice a day (pr-decide.timer). Same contract as seo_decide.py (ADR 2026-10-13):

  1. act on answers: yes → squash-merge, no → close with the reason as a
     comment (branch kept), later → nothing now, not asked again for 7 days
  2. ask about open PRs that have no question waiting, oldest first, at most
     MAX_OPEN waiting at once so "Dziś" does not drown

Skipped: drafts, archived repos, `seo-auto` PRs (seo_decide.py owns those).
A PR with conflicts or red CI gets only Odrzuć / Później — "Scal" would fail.
A failed merge is logged and consumed; the PR, still open, is asked again.

Env: INGEST_URL + INGEST_TOKEN, PR_OWNER (default PiotrRomanczuk).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agents.routine_report import Reporter  # noqa: E402

ROUTINE = 'pr-decide'
OWNER = os.environ.get('PR_OWNER', 'PiotrRomanczuk')
MAX_OPEN = 8
SNOOZE = timedelta(days=7)
SKIP_LABELS = {'seo-auto'}
MERGE = {'key': 'yes', 'label': 'Scal'}
CLOSE = {'key': 'no', 'label': 'Odrzuć'}
LATER = {'key': 'later', 'label': 'Później'}

Gh = Callable[[list[str]], str]
Log = Callable[[str], None]


def gh(args: list[str]) -> str:
    return subprocess.run(['gh', *args], check=True, capture_output=True, text=True).stdout


def ref_of(repo: str, number: int | str) -> str:
    return f'{repo}#{number}'


def split_ref(ref: str) -> tuple[str, str] | None:
    repo, _, num = ref.partition('#')
    return (repo, num) if repo and num.isdigit() else None


def candidates(run: Gh) -> list[dict[str, Any]]:
    """Open, non-draft PRs in live repos, oldest first."""
    archived = {r['name'] for r in json.loads(run(['repo', 'list', OWNER, '--limit', '200', '--archived',
                                                   '--json', 'name']) or '[]')}
    prs = json.loads(run(['search', 'prs', '--owner', OWNER, '--state', 'open', '--limit', '200', '--json',
                          'repository,number,title,url,isDraft,author,createdAt,labels']) or '[]')
    out = [p for p in prs if not p['isDraft'] and p['repository']['name'] not in archived
           and not SKIP_LABELS & {lb['name'] for lb in p.get('labels', [])}]
    return sorted(out, key=lambda p: p['createdAt'])


def health(run: Gh, repo: str, number: int) -> tuple[bool, str]:
    """(mergeable, why-not). UNKNOWN mergeability counts as mergeable — GitHub computes it lazily."""
    v = json.loads(run(['pr', 'view', str(number), '-R', f'{OWNER}/{repo}', '--json',
                        'mergeable,statusCheckRollup,additions,deletions']))
    size = f'+{v.get("additions", 0)} / −{v.get("deletions", 0)} linii'
    if v.get('mergeable') == 'CONFLICTING':
        return False, f'{size} · konflikt z gałęzią bazową, nie da się scalić'
    red = [c.get('name') or c.get('context') for c in v.get('statusCheckRollup') or []
           if (c.get('conclusion') or c.get('state') or '').upper() in ('FAILURE', 'ERROR', 'TIMED_OUT', 'CANCELLED')]
    if red:
        return False, f'{size} · CI czerwone: {", ".join(red[:3])}'
    return True, size


def act(r: Reporter, run: Gh, log: Log) -> set[str]:
    done: set[str] = set()
    for d in r.answers():
        ref = str(d.get('ref') or '')
        parts = split_ref(ref)
        try:
            if parts and d.get('answer') == 'yes':
                run(['pr', 'merge', parts[1], '-R', f'{OWNER}/{parts[0]}', '--squash', '--delete-branch'])
                log(f'{ref} merged')
            elif parts and d.get('answer') == 'no':
                why = d.get('reason') or 'bez powodu'
                run(['pr', 'close', parts[1], '-R', f'{OWNER}/{parts[0]}', '--comment',
                     f'Odrzucone w home-ops Decisions: {why}'])
                log(f'{ref} closed: {why}')
            else:
                log(f'{ref}: {d.get("answer")} — nothing to do now')
        except subprocess.CalledProcessError as e:
            log(f'{ref}: gh failed ({(e.stderr or "").strip()[:200]}) — will be asked again')
        r.consume(d['id'])
        done.add(ref)
    return done


def snoozed(r: Reporter, now: datetime) -> set[str]:
    rows = r._call('GET', f'/api/decisions?state=answered&routine={ROUTINE}&limit=200')['decisions']
    return {d['ref'] for d in rows if d.get('answer') == 'later' and d.get('answered_at')
            and now - datetime.fromisoformat(d['answered_at'].replace('Z', '+00:00')) < SNOOZE}


def ask(r: Reporter, run: Gh, prs: list[dict[str, Any]], log: Log, skip: set[str], now: datetime) -> int:
    waiting = r.open_refs()
    blocked = waiting | {str(d.get('ref')) for d in r.answers()} | skip | snoozed(r, now)
    room = MAX_OPEN - len(waiting)
    asked = 0
    for p in prs:
        if asked >= room:
            break
        repo, num = p['repository']['name'], p['number']
        ref = ref_of(repo, num)
        if ref in blocked:
            continue
        ok, detail = health(run, repo, num)
        author = p.get('author', {}).get('login', '')
        age = (now - datetime.fromisoformat(p['createdAt'].replace('Z', '+00:00'))).days
        r.ask(f'{repo} #{num}: {p["title"][:200]}', options=[MERGE, CLOSE, LATER] if ok else [CLOSE, LATER],
              ref=ref, slug=repo, context_url=p['url'], expires_hours=24 * 7,
              detail=f'{detail} · {age} dni · autor {author}. Scal = squash-merge i usunięcie gałęzi; '
                     'Odrzuć = zamknięcie z powodem (gałąź zostaje); Później = wraca za 7 dni.')
        log(f'asked about {ref}')
        asked += 1
    return asked


def main() -> int:
    r = Reporter.from_env(ROUTINE)
    log: Log = lambda m: print(f'pr-decide: {m}', file=sys.stderr)  # noqa: E731
    now = datetime.now(timezone.utc)
    acted = act(r, gh, log)
    prs = candidates(gh)
    asked = ask(r, gh, prs, log, acted, now)
    log(f'{len(prs)} open PRs · acted on {len(acted)} · asked {asked}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
