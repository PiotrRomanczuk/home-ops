#!/usr/bin/env python3
"""pr_decide.py — every reviewed open PR on Piotr's GitHub becomes a Decisions question.

Twice a day (pr-decide.timer). Same contract as seo_decide.py (ADR 2026-10-13), plus the
"second pair of eyes" rule (2026-11-11, migration 028): a PR is asked about only after
pr-review reviewed its current head commit, and the options follow that review (pr_gate.py).

  1. act on answers: yes / force → squash-merge exactly the reviewed commit
     (`--match-head-commit`), fix → label `fix-requested` for pr-agent, no → close with
     the reason as a comment (branch kept), later → nothing, not asked again for 7 days
  2. ask about reviewed PRs with no question waiting, oldest first, at most MAX_OPEN
     waiting at once; a question about an older commit is superseded by the new one

Skipped: drafts, archived repos, `seo-auto` PRs (seo_decide.py owns those).
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

import pr_gate  # noqa: E402

ROUTINE = 'pr-decide'
OWNER = os.environ.get('PR_OWNER', 'PiotrRomanczuk')
MAX_OPEN = 8
SNOOZE = timedelta(days=7)
SKIP_LABELS = {'seo-auto'}
SUPERSEDED = 'zastąpione nowym commitem'

Gh = Callable[[list[str]], str]
Log = Callable[[str], None]
ReviewFor = Callable[[str, int, str], 'dict[str, Any] | None']


def gh(args: list[str]) -> str:
    return subprocess.run(['gh', *args], check=True, capture_output=True, text=True).stdout


def candidates(run: Gh) -> list[dict[str, Any]]:
    """Open, non-draft PRs in live repos, oldest first."""
    archived = {r['name'] for r in json.loads(run(['repo', 'list', OWNER, '--limit', '200', '--archived',
                                                   '--json', 'name']) or '[]')}
    prs = json.loads(run(['search', 'prs', '--owner', OWNER, '--state', 'open', '--limit', '200', '--json',
                          'repository,number,title,url,isDraft,author,createdAt,labels']) or '[]')
    out = [p for p in prs if not p['isDraft'] and p['repository']['name'] not in archived
           and not SKIP_LABELS & {lb['name'] for lb in p.get('labels', [])}]
    return sorted(out, key=lambda p: p['createdAt'])


def act(r: Reporter, run: Gh, log: Log) -> set[str]:
    done: set[str] = set()
    for d in r.answers():
        ref, answer = str(d.get('ref') or ''), d.get('answer')
        parts = pr_gate.split_ref(ref)
        try:
            if parts and answer in ('yes', 'force'):
                pr_gate.merge_reviewed(run, OWNER, *parts, log)
            elif parts and answer == 'fix':
                run(['label', 'create', 'fix-requested', '-R', f'{OWNER}/{parts[0]}', '--color', '0969da', '--force'])
                run(['pr', 'edit', parts[1], '-R', f'{OWNER}/{parts[0]}', '--add-label', 'fix-requested'])
                log(f'{ref}: fix requested')
            elif parts and answer == 'no':
                why = d.get('reason') or 'bez powodu'
                run(['pr', 'close', parts[1], '-R', f'{OWNER}/{parts[0]}', '--comment',
                     f'Odrzucone w home-ops Decisions: {why}'])
                log(f'{ref} closed: {why}')
            else:
                log(f'{ref}: {answer} — nothing to do now')
        except subprocess.CalledProcessError as e:
            log(f'{ref}: gh failed ({(e.stderr or "").strip()[:200]}) — will be asked again')
        r.consume(d['id'])
        done.add(pr_gate.pr_key(ref))
    return done


def snoozed(r: Reporter, now: datetime) -> set[str]:
    rows = r._call('GET', f'/api/decisions?state=answered&routine={ROUTINE}&limit=200')['decisions']
    return {pr_gate.pr_key(d['ref']) for d in rows if d.get('answer') == 'later' and d.get('answered_at')
            and not str(d.get('reason') or '').startswith(SUPERSEDED)
            and now - datetime.fromisoformat(d['answered_at'].replace('Z', '+00:00')) < SNOOZE}


def waiting(r: Reporter) -> dict[str, dict[str, Any]]:
    """Open questions by PR key (repo#number)."""
    rows = r._call('GET', f'/api/decisions?state=open&routine={ROUTINE}&limit=200')['decisions']
    return {pr_gate.pr_key(d['ref']): d for d in rows if d.get('ref')}


def ask(r: Reporter, run: Gh, prs: list[dict[str, Any]], log: Log, skip: set[str], now: datetime,
        review_for: ReviewFor) -> int:
    open_q = waiting(r)
    blocked = skip | snoozed(r, now)
    room, asked = MAX_OPEN - len(open_q), 0
    for p in prs:
        repo, num = p['repository']['name'], p['number']
        key = f'{repo}#{num}'
        if key in blocked:
            continue
        st = pr_gate.state(run, OWNER, repo, num)
        review = review_for(repo, num, st['sha'])
        old = open_q.get(key)
        if review is None or (old and pr_gate.split_ref(old['ref'])[2] == st['sha']):
            continue  # not reviewed yet, or the question about this commit is already waiting
        if old:  # waiting question is about an older commit: retire it, ask about the reviewed one
            r._call('POST', f'/api/decisions/{old["id"]}/answer', {'option': 'later', 'reason': f'{SUPERSEDED} {st["sha"][:7]}'})
            r.consume(old['id'])
        elif asked >= room:
            break
        n = pr_gate.rounds(p.get('labels', []))
        age = (now - datetime.fromisoformat(p['createdAt'].replace('Z', '+00:00'))).days
        r.ask(f'{repo} #{num}: {p["title"][:200]}', options=pr_gate.options(review, st['ok'], n),
              ref=pr_gate.ref_of(repo, num, st['sha']), slug=repo, context_url=p['url'], expires_hours=24 * 7,
              detail=pr_gate.detail(review, st, age, p.get('author', {}).get('login', ''), n))
        log(f'asked about {key} at {st["sha"][:7]} ({review["verdict"]})')
        asked += 0 if old else 1
    return asked


def main() -> int:
    import review_db
    r = Reporter.from_env(ROUTINE)
    log: Log = lambda m: print(f'pr-decide: {m}', file=sys.stderr)  # noqa: E731
    now = datetime.now(timezone.utc)
    acted = act(r, gh, log)
    prs = candidates(gh)
    asked = ask(r, gh, prs, log, acted, now, review_db.for_sha)
    log(f'{len(prs)} open PRs · acted on {len(acted)} · asked {asked}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
