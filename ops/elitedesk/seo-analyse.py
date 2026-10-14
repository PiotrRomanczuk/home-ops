#!/usr/bin/env python3
"""seo-analyse.py — morning SEO analysis for one site (gitarawarszawa.pl).

Runs on elitedesk via seo-analyse.timer (06:30, after seo-collect). Reads
seo_gsc_daily / seo_ga4_daily through `docker exec psql` (same path the daily
digest uses — no driver to install), computes 7d-vs-7d metrics + the district
breakdown (seo_metrics.py), renders a plain-text card (seo_render.py) and asks
headless Claude for a short narrative with 3 recommendations (seo_llm.py).

Outputs:
  * digest.d/seo-gitarawarszawa.txt — picked up by the 07:00 daily-digest
  * seo_analysis_daily (migration 018) — card + narrative + metrics JSON

The card is always written; the narrative is best-effort (logged-out CLI →
skipped with a warning, exit 0). Exit 1 only when psql itself fails.

Env (seo-collect.env): SEO_SITE (default gitarawarszawa.pl), SEO_DISTRICTS,
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
from seo_llm import build_prompt, narrate  # noqa: E402
from seo_metrics import area_breakdown, ga4_summary, page_deltas, query_deltas, split_windows, totals  # noqa: E402
from seo_render import render_card  # noqa: E402

SITE = os.environ.get('SEO_SITE', 'gitarawarszawa.pl')
DISTRICTS = Path(os.environ.get('SEO_DISTRICTS') or (_here / 'seo-districts.json'))
PROMPT = _here / 'seo-analyse.prompt.md'
CARD_PATH = _here / 'digest.d' / f"seo-{SITE.replace('.', '-')}.txt"
CONTAINER = os.environ.get('CONTAINER', 'home-ops-postgres-1')
DB, DB_USER = os.environ.get('DB', 'home_ops'), os.environ.get('DB_USER', 'postgres')
WINDOW_DAYS, GSC_LAG = 7, 2


def psql_json(sql: str) -> list[dict[str, Any]]:
    """Run SQL wrapped in json_agg through the compose container; [] when empty."""
    wrapped = f"SELECT COALESCE(json_agg(t), '[]'::json) FROM ({sql}) t"
    r = subprocess.run(['docker', 'exec', '-i', CONTAINER, 'psql', '-U', DB_USER, '-d', DB, '-X', '-q', '-t', '-A'],
                       input=wrapped, capture_output=True, text=True, check=True)
    return json.loads(r.stdout.strip() or '[]')


def psql_exec(sql: str, params: dict[str, str]) -> None:
    """Parameterised write via psql -v (values are passed as literal variables, not interpolated)."""
    cmd = ['docker', 'exec', '-i', CONTAINER, 'psql', '-U', DB_USER, '-d', DB, '-X', '-q', '-v', 'ON_ERROR_STOP=1']
    for k, v in params.items():
        cmd += ['-v', f'{k}={v}']
    subprocess.run(cmd, input=sql, capture_output=True, text=True, check=True)


def load_rows(end: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    start = end - timedelta(days=2 * WINDOW_DAYS - 1)
    gsc = psql_json(f"SELECT day::text, query, page, clicks, impressions, position FROM seo_gsc_daily "
                    f"WHERE site = '{SITE}' AND day BETWEEN '{start}' AND '{end}'")
    ga4 = psql_json(f"SELECT day::text, source_medium, sessions, users, events FROM seo_ga4_daily "
                    f"WHERE site = '{SITE}' AND day BETWEEN '{end - timedelta(days=WINDOW_DAYS - 1)}' AND '{end}'")
    return gsc, ga4


def load_history(days: int = 3) -> list[dict[str, Any]]:
    return psql_json(f"SELECT day::text, narrative FROM seo_analysis_daily WHERE site = '{SITE}' AND kind = 'daily' "
                     f"AND narrative IS NOT NULL ORDER BY day DESC LIMIT {days}")


def build_metrics(gsc: list[dict[str, Any]], ga4: list[dict[str, Any]], end: date) -> dict[str, Any]:
    cur, prev = split_windows(gsc, end, WINDOW_DAYS)
    cfg = json.loads(DISTRICTS.read_text())
    return {
        'site': SITE, 'window_end': end.isoformat(), 'window_days': WINDOW_DAYS,
        'totals': totals(cur), 'totals_prev': totals(prev),
        'queries': query_deltas(cur, prev), 'pages': page_deltas(cur, prev),
        'areas': area_breakdown(cur, prev, cfg), 'ga4': ga4_summary(ga4) if ga4 else None,
    }


def save(day: date, metrics: dict[str, Any], card: str, narrative: str | None, model: str) -> None:
    psql_exec(
        "INSERT INTO seo_analysis_daily (site, day, kind, metrics, card, narrative, model) "
        "VALUES (:'site', :'day', 'daily', :'metrics'::jsonb, :'card', NULLIF(:'narrative', ''), :'model') "
        "ON CONFLICT (site, day, kind) DO UPDATE SET metrics = EXCLUDED.metrics, card = EXCLUDED.card, "
        "narrative = EXCLUDED.narrative, model = EXCLUDED.model, created_at = now();",
        {'site': SITE, 'day': day.isoformat(), 'metrics': json.dumps(metrics, ensure_ascii=False),
         'card': card, 'narrative': narrative or '', 'model': model})


def main() -> int:
    today = date.today()
    end = today - timedelta(days=GSC_LAG + 1)  # newest day GSC has usually finalised
    try:
        gsc, ga4 = load_rows(end)
        history = load_history()
    except subprocess.CalledProcessError as e:
        print(f'psql failed: {e.stderr}', file=sys.stderr)
        return 1
    metrics = build_metrics(gsc, ga4, end)
    card = render_card(metrics)
    narrative, model = (None, '') if not gsc else narrate(build_prompt(PROMPT, metrics, history))
    if gsc and narrative is None:
        print('warning: claude narrative unavailable (CLI logged out / timeout) — card only', file=sys.stderr)
    CARD_PATH.parent.mkdir(exist_ok=True)
    CARD_PATH.write_text(card + ('\n\n' + narrative if narrative else '') + '\n')
    try:
        save(today, metrics, card, narrative, model)
    except subprocess.CalledProcessError as e:
        print(f'save failed (migration 018 applied?): {e.stderr}', file=sys.stderr)
        return 1
    print(json.dumps({'site': SITE, 'window_end': end.isoformat(), 'gsc_rows': len(gsc),
                      'narrative': bool(narrative), 'card': str(CARD_PATH)}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
