#!/usr/bin/env python3
"""seo-collect.py — daily search-visibility snapshot for Piotr's public sites.

Runs on elitedesk via seo-collect.timer (06:00). For each site in
seo-collect.sites.json it pulls:
  * Search Console — query × page × day over a rolling GSC_DAYS window
    (GSC lags 2–3 days and revises recent days, so the window is re-sent and
    upserted rather than appended).
  * GA4 — sessions/users and the site's tracked conversion events per day ×
    source/medium for the last GA4_DAYS days.
and for each entry in `places`, the Google rating + review count (own listing
and local competitors), the basis for review-velocity comparisons.

Everything goes to POST /api/seo/ingest (migration 017). A source whose
credentials aren't configured is skipped with a warning, not failed — the
Places key in particular is optional.

Env:
  INGEST_URL, INGEST_TOKEN  (required) same pair every agent on this host uses
  SEO_SA_JSON     path to the Google service-account key (GSC + GA4)
  PLACES_API_KEY  Places API (New) key, restricted to that API
  SEO_CONFIG      defaults to seo-collect.sites.json next to this script
  GSC_DAYS        default 7;  GA4_DAYS default 3
  HOST_NAME       default 'elitedesk'

Exit code: 1 if any configured source failed (so the unit shows failed and the
digest surfaces it), 0 otherwise.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))
sys.path.insert(0, str(_here.parent.parent))
from agents._common import IngestClient  # noqa: E402
from seo_google import access_token  # noqa: E402
from seo_sources import fetch_ga4, fetch_gsc, fetch_place, place_row  # noqa: E402

CONFIG = Path(os.environ.get('SEO_CONFIG') or (_here / 'seo-collect.sites.json'))
SA_JSON = os.environ.get('SEO_SA_JSON', '')
PLACES_KEY = os.environ.get('PLACES_API_KEY', '')
GSC_DAYS = int(os.environ.get('GSC_DAYS', '7'))
GA4_DAYS = int(os.environ.get('GA4_DAYS', '3'))

ic = IngestClient.from_env(host=os.environ.get('HOST_NAME', 'elitedesk'), source='agent:seo-collect', timeout=60)
SEO_URL = ic.events_url.replace('/api/ingest', '').rstrip('/') + '/api/seo/ingest'


def window(days: int, today: date) -> tuple[str, str]:
    """[today-days, today-1] as ISO dates — yesterday is the newest complete day."""
    return (today - timedelta(days=days)).isoformat(), (today - timedelta(days=1)).isoformat()


def send(kind: str, rows: list[dict[str, Any]]) -> int:
    status, body = ic.request(SEO_URL, {'kind': kind, 'rows': rows})
    if status != 200 or not body:
        raise RuntimeError(f'/api/seo/ingest {kind} → {status} {body}')
    if body.get('rejected'):
        ic.post_log('warn', f'seo {kind}: {len(body["rejected"])} rows rejected', {'rejected': body['rejected'][:20]})
    return int(body.get('upserted', 0))


def run_step(name: str, fn: Callable[[], int], failures: list[str], summary: dict[str, int]) -> None:
    try:
        summary[name] = fn()
    except Exception as e:  # noqa: BLE001 — one bad source must not stop the others
        failures.append(name)
        ic.post_log('error', f'seo-collect {name} failed: {e}')
        print(f'{name} failed: {e}', file=sys.stderr)


def google_token(failures: list[str]) -> str:
    """Bearer token for GSC + GA4, or '' when unconfigured (skip) or broken (fail)."""
    if not SA_JSON:
        ic.post_log('warn', 'seo-collect: SEO_SA_JSON not set — skipping Search Console + GA4')
        return ''
    try:
        return access_token(SA_JSON)
    except Exception as e:  # noqa: BLE001
        failures.append('google-auth')
        ic.post_log('error', f'seo-collect google-auth failed: {e}')
        print(f'google-auth failed: {e}', file=sys.stderr)
        return ''


def main() -> int:
    cfg = json.loads(CONFIG.read_text())
    today = date.today()
    failures: list[str] = []
    summary: dict[str, int] = {}

    token = google_token(failures)
    if token:
        for site in cfg.get('sites', []):
            slug = site['slug']
            if site.get('gsc'):
                start, end = window(GSC_DAYS, today)
                run_step(f'gsc:{slug}', lambda s=site, a=start, b=end: send(
                    'gsc', fetch_gsc(token, s['slug'], s['gsc'], a, b)), failures, summary)
            if site.get('ga4'):
                start, end = window(GA4_DAYS, today)
                run_step(f'ga4:{slug}', lambda s=site, a=start, b=end: send('ga4', fetch_ga4(
                    token, s['slug'], s['ga4'], s.get('events', []), a, b)), failures, summary)

    places = [p for p in cfg.get('places', []) if p.get('enabled', True)]
    if places and PLACES_KEY:
        def collect_places() -> int:
            rows = []
            for p in places:
                hit = fetch_place(PLACES_KEY, p)
                if hit is None:
                    ic.post_log('warn', f'seo-collect: no Places match for {p["label"]}', {'query': p.get('query')})
                    continue
                rows.append(place_row(p, hit, today.isoformat()))
            return send('places', rows) if rows else 0
        run_step('places', collect_places, failures, summary)
    elif places:
        ic.post_log('warn', 'seo-collect: PLACES_API_KEY not set — skipping competitor reviews')

    level = 'error' if failures else 'info'
    ic.post_log(level, f'seo-collect done: {summary}' + (f' failed={failures}' if failures else ''), {'summary': summary})
    print(json.dumps({'summary': summary, 'failed': failures}))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
