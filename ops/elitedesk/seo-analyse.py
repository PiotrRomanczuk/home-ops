#!/usr/bin/env python3
"""seo-analyse.py — morning SEO analysis for one site (gitarawarszawa.pl).

06:30 via seo-analyse.timer, after seo-collect. Steps, each best-effort:
  1. GSC/GA4 rows (migration 017) → 7d-vs-7d metrics, district breakdown,
     adaptive opportunities (seo_metrics / seo_opps).
  2. Own-site crawl → seo_page_snapshot + rule findings with open/resolve
     lifecycle (seo_drift, migration 019).
  3. Plan: in_pr → shipped when the PR merged; shipped hypotheses get 14/28-day
     verdicts vs baseline and control pages (seo_plan).
  4. Card (always) → digest.d/ for the 07:00 e-mail; headless Claude narrative
     with 3 recommendations + a ```plan-updates``` JSON block that is validated
     and applied to seo_plan (propose / reprioritize / ready / retire).
  5. Everything persisted to seo_analysis_daily (migration 018).

Exit 1 only when psql itself fails. Env: SEO_SITE, SEO_SITE_URL, SEO_DISTRICTS,
CLAUDE_MODEL / CLAUDE_TIMEOUT / CLAUDE_BIN, CONTAINER / DB / DB_USER.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))
import seo_plan_db as pdb  # noqa: E402
from seo_db import psql_exec, psql_json  # noqa: E402
from seo_drift import rules, snapshot_site  # noqa: E402
from seo_llm import build_prompt, extract_plan_updates, narrate  # noqa: E402
from seo_metrics import area_breakdown, ga4_summary, page_deltas, query_deltas, split_windows, totals  # noqa: E402
from seo_opps import low_ctr, striking_distance  # noqa: E402
from seo_plan import evaluate, final_status  # noqa: E402
from seo_render import render_card, render_findings, render_opps, render_plan  # noqa: E402

SITE = os.environ.get('SEO_SITE', 'gitarawarszawa.pl')
SITE_URL = os.environ.get('SEO_SITE_URL', f'https://{SITE}/')
DISTRICTS = Path(os.environ.get('SEO_DISTRICTS') or (_here / 'seo-districts.json'))
PROMPT = _here / 'seo-analyse.prompt.md'
CARD_PATH = _here / 'digest.d' / f"seo-{SITE.replace('.', '-')}.txt"
WINDOW_DAYS, GSC_LAG = 7, 2


def load_rows(end: date, days: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    start = end - timedelta(days=days - 1)
    gsc = psql_json(f"SELECT day::text, query, page, clicks, impressions, position FROM seo_gsc_daily "
                    f"WHERE site = '{SITE}' AND day BETWEEN '{start}' AND '{end}'")
    ga4 = psql_json(f"SELECT day::text, source_medium, sessions, users, events FROM seo_ga4_daily "
                    f"WHERE site = '{SITE}' AND day BETWEEN '{end - timedelta(days=WINDOW_DAYS - 1)}' AND '{end}'")
    return gsc, ga4


def build_metrics(gsc: list[dict[str, Any]], ga4: list[dict[str, Any]], end: date) -> dict[str, Any]:
    cur, prev = split_windows(gsc, end, WINDOW_DAYS)
    cfg = json.loads(DISTRICTS.read_text())
    return {'site': SITE, 'window_end': end.isoformat(), 'window_days': WINDOW_DAYS,
            'totals': totals(cur), 'totals_prev': totals(prev), 'queries': query_deltas(cur, prev),
            'pages': page_deltas(cur, prev), 'areas': area_breakdown(cur, prev, cfg),
            'opportunities': {'striking_distance': striking_distance(cur), 'low_ctr': low_ctr(cur)},
            'ga4': ga4_summary(ga4) if ga4 else None}


def crawl_step(today: date) -> list[dict[str, Any]]:
    try:
        snaps = snapshot_site(SITE_URL)
        prev = pdb.previous_snapshots(SITE, today)
        pdb.save_snapshots(SITE, today, snaps)
        found = [{'path': s['path'], **f} for s in snaps for f in rules(s, prev.get(s['path']), SITE_URL)]
        pdb.sync_findings(SITE, today, found)
    except Exception as e:  # noqa: BLE001 — crawl must never block the card
        print(f'warning: crawl step failed: {e}', file=sys.stderr)
    return pdb.open_findings(SITE)


def plan_step(gsc_long: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    plan = pdb.load_plan(SITE)
    for h in plan:
        if pdb.mark_shipped_if_merged(h):
            h['status'] = 'shipped'
    shipped = [h for h in plan if h.get('shipped_at')]
    for h in shipped:
        if h['status'] in ('shipped', 'helped', 'hurt', 'neutral'):
            v = evaluate(h, gsc_long, shipped, today, lag_days=GSC_LAG + 1)
            h['verdict'] = v
            pdb.save_verdict(h['id'], v, final_status(v))
    return pdb.load_plan(SITE)


def save(day: date, metrics: dict[str, Any], card: str, narrative: str | None, model: str) -> None:
    psql_exec("INSERT INTO seo_analysis_daily (site, day, kind, metrics, card, narrative, model) "
              "VALUES (:'site', :'day', 'daily', :'metrics'::jsonb, :'card', NULLIF(:'narrative', ''), :'model') "
              "ON CONFLICT (site, day, kind) DO UPDATE SET metrics = EXCLUDED.metrics, card = EXCLUDED.card, "
              "narrative = EXCLUDED.narrative, model = EXCLUDED.model, created_at = now();",
              {'site': SITE, 'day': day.isoformat(), 'metrics': json.dumps(metrics, ensure_ascii=False),
               'card': card, 'narrative': narrative or '', 'model': model})


def main() -> int:
    today = date.today()
    end = today - timedelta(days=GSC_LAG + 1)
    try:
        gsc_long, ga4 = load_rows(end, 70)          # 70 d: enough for 28 d baseline + 28 d after + lag
        history = psql_json(f"SELECT day::text, narrative FROM seo_analysis_daily WHERE site = '{SITE}' AND kind = 'daily' "
                            f"AND narrative IS NOT NULL ORDER BY day DESC LIMIT 3")
    except subprocess.CalledProcessError as e:
        print(f'psql failed: {e.stderr}', file=sys.stderr)
        return 1
    gsc = [r for r in gsc_long if date.fromisoformat(r['day']) > end - timedelta(days=2 * WINDOW_DAYS)]
    metrics = build_metrics(gsc, ga4, end)
    findings = crawl_step(today)
    plan = plan_step(gsc_long, today)
    metrics['plan'] = plan
    metrics['findings'] = findings
    card = '\n\n'.join(p for p in (render_card(metrics), render_opps(metrics['opportunities']),
                                   render_plan(plan), render_findings(findings)) if p)
    narrative, model, applied = None, '', {}
    if gsc or plan or findings:
        raw, model = narrate(build_prompt(PROMPT, metrics, history))
        if raw:
            narrative, updates = extract_plan_updates(raw)
            applied = pdb.apply_updates(SITE, updates, plan)
        else:
            print('warning: claude narrative unavailable (CLI logged out / timeout) — card only', file=sys.stderr)
    CARD_PATH.parent.mkdir(exist_ok=True)
    CARD_PATH.write_text(card + ('\n\n' + narrative if narrative else '') + '\n')
    try:
        save(today, metrics, card, narrative, model)
    except subprocess.CalledProcessError as e:
        print(f'save failed (migrations 018/019 applied?): {e.stderr}', file=sys.stderr)
        return 1
    print(json.dumps({'site': SITE, 'window_end': end.isoformat(), 'gsc_rows': len(gsc), 'findings_open': len(findings),
                      'plan_rows': len(plan), 'narrative': bool(narrative), 'plan_updates': applied, 'card': str(CARD_PATH)}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
