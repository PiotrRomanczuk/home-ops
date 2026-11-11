#!/usr/bin/env python3
"""pr_review.py — "second pair of eyes": an independent review of every open PR.

Hourly 07–23 (pr-review.timer). For each open, non-draft PR (pr_decide.candidates)
whose current head commit has no row in pr_reviews (migration 028), at most MAX_PER_RUN
per run, oldest first: check the head out (pr_review_gh), run the two-pass reviewer
(pr_review_llm), post one comment + a review:* label, store the row. pr-decide asks
Piotr about a PR only once its current head has a review.

    pr_review.py                     normal run
    pr_review.py --dry-run           review, but write JSON files only (no comment, no DB row)
    pr_review.py --pr repo#12        just this PR (ignores the limit, re-reviews its head)

Env: INGEST_URL + INGEST_TOKEN (card), PR_OWNER, PR_REVIEW_CACHE, PR_REVIEW_MODEL, PR_REVIEW_RULES.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agents.routine_report import Reporter  # noqa: E402

import pr_decide  # noqa: E402
import pr_gate  # noqa: E402
import pr_review_gh  # noqa: E402
import pr_review_llm  # noqa: E402
import review_db  # noqa: E402

ROUTINE = 'pr-review'
MAX_PER_RUN = 3
VIEW = 'headRefOid,baseRefName,title,body,statusCheckRollup'


def log(msg: str) -> None:
    print(f'pr-review: {msg}', file=sys.stderr)


def view(repo: str, number: int) -> dict[str, Any]:
    return json.loads(pr_decide.gh(['pr', 'view', str(number), '-R', f'{pr_review_gh.OWNER}/{repo}', '--json', VIEW]))


def ci_line(checks: list[dict[str, Any]]) -> str:
    states = [f'{c.get("name") or c.get("context")}={c.get("conclusion") or c.get("state") or c.get("status")}'
              for c in checks]
    return ', '.join(states) or 'brak kontroli'


def previous_text(prev: dict[str, Any] | None) -> str:
    if not prev:
        return ''
    findings = prev['findings'] if isinstance(prev['findings'], list) else json.loads(prev['findings'] or '[]')
    lines = [f'Commit {prev["head_sha"][:7]}: {prev["verdict"]} — {prev["summary"]}']
    lines += [f'- [{f["severity"]}] {f["file"]}:{f["line"]} {f["problem"]}' for f in findings]
    return '\n'.join(lines) + '\nSprawdź, czy te uwagi zostały poprawione.'


def review_one(p: dict[str, Any], v: dict[str, Any], dry: bool) -> dict[str, Any]:
    repo, num, sha = p['repository']['name'], p['number'], v['headRefOid']
    path = pr_review_gh.checkout(repo, num, v['baseRefName'])
    body, skipped = pr_review_gh.diff(path, v['baseRefName'])
    previous = '' if dry else previous_text(review_db.latest(repo, num))
    pr = {'repo': repo, 'number': num, 'title': v['title'], 'body': v.get('body'), 'base': v['baseRefName'],
          'ci': ci_line(v.get('statusCheckRollup') or []), 'previous': previous}
    result = pr_review_llm.review(pr, body, skipped, path)
    row = {**result, 'repo': repo, 'number': num, 'head_sha': sha, 'round': pr_gate.rounds(p.get('labels', []))}
    if dry:
        out = pr_review_gh.CACHE / 'dry' / f'{repo}-{num}-{sha[:7]}.json'
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(row, ensure_ascii=False, indent=1) + '\n' + pr_review_gh.render(row, sha))
        log(f'{repo}#{num} {sha[:7]}: {row["verdict"]} (dry run → {out})')
        return row
    row['comment_url'] = pr_review_gh.publish(pr_decide.gh, repo, num, row, sha)
    review_db.save(row)
    log(f'{repo}#{num} {sha[:7]}: {row["verdict"]}, {len(row["findings"])} uwag, odrzucone {row["dropped"]}')
    return row


def pick(prs: list[dict[str, Any]], only: str | None, limit: int,
         dry: bool = False) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    done = set() if only or dry else review_db.reviewed_shas()  # a dry run never touches the DB
    out = []
    for p in prs:
        repo, num = p['repository']['name'], p['number']
        if only and only != f'{repo}#{num}':
            continue
        v = view(repo, num)
        if (repo, num, v['headRefOid']) not in done:
            out.append((p, v))
        if len(out) >= limit:
            break
    return out


def report(rows: list[dict[str, Any]], errors: list[str]) -> None:
    if not rows and not errors:
        return
    items = [(f'{r["repo"]} #{r["number"]}: {r["verdict"]} — {r["summary"]}'[:160], r.get('comment_url')) for r in rows]
    items += [(e[:160], None) for e in errors][:5 - len(items)]
    Reporter.from_env(ROUTINE).card(f'Przejrzane PR: {len(rows)}, z uwagami: {sum(r["verdict"] != "ok" for r in rows)}',
                                    status='warn' if errors else 'ok', items=items[:5],
                                    metric={'label': 'przejrzane', 'value': len(rows)})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--pr', help='repo#number')
    ap.add_argument('--max', type=int, default=MAX_PER_RUN)
    ns = ap.parse_args(argv)
    rows, errors = [], []
    for p, v in pick(pr_decide.candidates(pr_decide.gh), ns.pr, 1 if ns.pr else ns.max, ns.dry_run):
        key = f'{p["repository"]["name"]}#{p["number"]}'
        try:
            rows.append(review_one(p, v, ns.dry_run))
        except (pr_review_llm.ReviewError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            errors.append(f'{key}: {str(getattr(exc, "stderr", "") or exc)[:200]}')
            log(errors[-1])
    if not ns.dry_run:
        report(rows, errors)
    return 1 if errors and not rows else 0


if __name__ == '__main__':
    raise SystemExit(main())
