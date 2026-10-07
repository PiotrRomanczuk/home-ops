"""seo_sources.py — fetch + shape for the three seo-collect.py sources.

Each source is a fetch_* (network) and a pure *_rows/_row shaper, so the
shaping — the part that has to match POST /api/seo/ingest — is unit-tested
without network (ops/elitedesk/tests/test_seo_collect.py).
"""
from __future__ import annotations

import urllib.parse
from typing import Any

from seo_google import http_json

GSC_PAGE = 25000
GA4_API = 'https://analyticsdata.googleapis.com/v1beta/properties/{}:runReport'
PLACES_API = 'https://places.googleapis.com/v1'
PLACES_FIELDS = 'id,displayName,rating,userRatingCount'


# ── Search Console ───────────────────────────────────────────────────────

def gsc_rows(site: str, api_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """searchAnalytics rows (dimensions date, query, page) → seo_gsc_daily rows."""
    out = []
    for r in api_rows:
        day, query, page = r['keys']
        out.append({
            'site': site, 'day': day, 'query': query, 'page': page,
            'clicks': int(r.get('clicks', 0)), 'impressions': int(r.get('impressions', 0)),
            'ctr': float(r.get('ctr', 0)), 'position': float(r.get('position', 0)),
        })
    return out


def fetch_gsc(token: str, site: str, prop: str, start: str, end: str) -> list[dict[str, Any]]:
    """site = config slug stored in the rows; prop = GSC property (sc-domain:… or URL prefix)."""
    url = ('https://www.googleapis.com/webmasters/v3/sites/'
           f'{urllib.parse.quote(prop, safe="")}/searchAnalytics/query')
    rows: list[dict[str, Any]] = []
    while True:
        resp = http_json(url, headers={'Authorization': f'Bearer {token}'}, body={
            'startDate': start, 'endDate': end, 'dimensions': ['date', 'query', 'page'],
            'rowLimit': GSC_PAGE, 'startRow': len(rows), 'dataState': 'all',
        })
        page = resp.get('rows', [])
        rows.extend(page)
        if len(page) < GSC_PAGE:
            return gsc_rows(site, rows)


# ── GA4 ──────────────────────────────────────────────────────────────────

def _ga4_day(v: str) -> str:
    return f'{v[:4]}-{v[4:6]}-{v[6:]}'


def ga4_rows(site: str, traffic: dict[str, Any], events: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge the sessions/users report with the event-count report on (day, source/medium)."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}

    def slot(day: str, sm: str) -> dict[str, Any]:
        return merged.setdefault((day, sm), {
            'site': site, 'day': day, 'source_medium': sm, 'sessions': 0, 'users': 0, 'events': {},
        })

    for r in traffic.get('rows', []):
        d, sm = (x['value'] for x in r['dimensionValues'])
        s = slot(_ga4_day(d), sm)
        s['sessions'], s['users'] = (int(x['value']) for x in r['metricValues'])
    for r in events.get('rows', []):
        d, sm, name = (x['value'] for x in r['dimensionValues'])
        slot(_ga4_day(d), sm)['events'][name] = int(r['metricValues'][0]['value'])
    return list(merged.values())


def fetch_ga4(token: str, site: str, property_id: str, tracked: list[str], start: str, end: str) -> list[dict[str, Any]]:
    url = GA4_API.format(property_id)
    hdr = {'Authorization': f'Bearer {token}'}
    dates = [{'startDate': start, 'endDate': end}]
    dims = [{'name': 'date'}, {'name': 'sessionSourceMedium'}]
    traffic = http_json(url, headers=hdr, body={
        'dateRanges': dates, 'dimensions': dims,
        'metrics': [{'name': 'sessions'}, {'name': 'totalUsers'}], 'limit': 10000,
    })
    events = http_json(url, headers=hdr, body={
        'dateRanges': dates, 'dimensions': dims + [{'name': 'eventName'}],
        'metrics': [{'name': 'eventCount'}], 'limit': 10000,
        'dimensionFilter': {'filter': {'fieldName': 'eventName', 'inListFilter': {'values': tracked}}},
    }) if tracked else {}
    return ga4_rows(site, traffic, events)


# ── Places ───────────────────────────────────────────────────────────────

def place_row(entry: dict[str, Any], place: dict[str, Any], day: str) -> dict[str, Any]:
    return {
        'place_id': place['id'], 'day': day, 'label': entry['label'],
        'name': (place.get('displayName') or {}).get('text') or entry['label'],
        'is_self': bool(entry.get('is_self')),
        'rating': place.get('rating'), 'review_count': place.get('userRatingCount'),
    }


def fetch_place(api_key: str, entry: dict[str, Any]) -> dict[str, Any] | None:
    """Pinned place_id → Place Details; otherwise first Text Search hit (None if no hit)."""
    if entry.get('place_id'):
        return http_json(f'{PLACES_API}/places/{entry["place_id"]}',
                         headers={'X-Goog-Api-Key': api_key, 'X-Goog-FieldMask': PLACES_FIELDS})
    resp = http_json(f'{PLACES_API}/places:searchText', body={
        'textQuery': entry['query'], 'languageCode': 'pl', 'regionCode': 'PL', 'pageSize': 1,
    }, headers={'X-Goog-Api-Key': api_key,
                'X-Goog-FieldMask': ','.join(f'places.{f}' for f in PLACES_FIELDS.split(','))})
    places = resp.get('places') or []
    return places[0] if places else None
