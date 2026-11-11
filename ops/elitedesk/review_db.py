"""review_db.py — the pr_reviews table (migration 028), shared by pr_review.py
(writes one row per reviewed head commit) and pr_decide.py (reads the row for
a PR's current head before offering "Scal"). SQL goes through seo_db's
`docker exec psql` helpers with -v variables, never string interpolation."""
from __future__ import annotations

import json
from typing import Any, Callable

from seo_db import psql_exec, psql_json

COLS = 'repo, number, head_sha, verdict, summary, findings, dropped, round, model, cost_usd, comment_url, created_at'

Query = Callable[[str, dict[str, str]], list[dict[str, Any]]]
Exec = Callable[[str, dict[str, str]], None]


def for_sha(repo: str, number: int, sha: str, query: Query = psql_json) -> dict[str, Any] | None:
    """The review of exactly this head commit, or None (not reviewed yet)."""
    rows = query(f"SELECT {COLS} FROM public.pr_reviews WHERE repo = :'repo' AND number = :'num'::int "
                 f"AND head_sha = :'sha'", {'repo': repo, 'num': str(number), 'sha': sha})
    return rows[0] if rows else None


def latest(repo: str, number: int, query: Query = psql_json) -> dict[str, Any] | None:
    """The most recent review of this PR (any commit) — tells the reviewer what was asked before."""
    rows = query(f"SELECT {COLS} FROM public.pr_reviews WHERE repo = :'repo' AND number = :'num'::int "
                 f"ORDER BY created_at DESC LIMIT 1", {'repo': repo, 'num': str(number)})
    return rows[0] if rows else None


def reviewed_shas(query: Query = psql_json) -> set[tuple[str, int, str]]:
    """Every (repo, number, head_sha) already reviewed — one query per run, not one per PR."""
    rows = query('SELECT repo, number, head_sha FROM public.pr_reviews', {})
    return {(r['repo'], int(r['number']), r['head_sha']) for r in rows}


def save(review: dict[str, Any], execute: Exec = psql_exec) -> None:
    """Upsert on (repo, number, head_sha): a re-run of the same commit replaces the old row."""
    params = {k: str(review.get(k) if review.get(k) is not None else '') for k in
              ('repo', 'number', 'head_sha', 'verdict', 'summary', 'dropped', 'round', 'model', 'cost_usd', 'comment_url')}
    params['findings'] = json.dumps(review.get('findings') or [], ensure_ascii=False)
    execute("""
INSERT INTO public.pr_reviews (repo, number, head_sha, verdict, summary, findings, dropped, round, model, cost_usd, comment_url)
VALUES (:'repo', :'number'::int, :'head_sha', :'verdict', :'summary', :'findings'::jsonb, :'dropped'::int, :'round'::int,
        NULLIF(:'model', ''), NULLIF(:'cost_usd', '')::numeric, NULLIF(:'comment_url', ''))
ON CONFLICT (repo, number, head_sha) DO UPDATE SET
  verdict = EXCLUDED.verdict, summary = EXCLUDED.summary, findings = EXCLUDED.findings, dropped = EXCLUDED.dropped,
  round = EXCLUDED.round, model = EXCLUDED.model, cost_usd = EXCLUDED.cost_usd,
  comment_url = COALESCE(EXCLUDED.comment_url, public.pr_reviews.comment_url), created_at = now();
""", params)
