"""seo_opps.py — opportunity detection with thresholds that scale to the site.

Classic bands (striking distance 11–30, "CTR below 2%") assume thousands of
impressions. For a site with dozens, the bands are derived from the data: any
query with at least `min_imp` impressions in positions 4–30 is striking
distance, and low CTR means below the site's own median at that position band.
"""
from __future__ import annotations

from statistics import median
from typing import Any, Iterable

Row = dict[str, Any]


def thresholds(total_impressions: int) -> dict[str, int]:
    """min impressions per query to count — 3 for tiny sites, 10 % of 1k+ sites."""
    if total_impressions < 200:
        return {'min_imp': 3, 'max_pos': 30}
    if total_impressions < 2000:
        return {'min_imp': 10, 'max_pos': 25}
    return {'min_imp': 30, 'max_pos': 20}


def _by_query(rows: Iterable[Row]) -> dict[str, dict[str, float]]:
    acc: dict[str, dict[str, float]] = {}
    for r in rows:
        a = acc.setdefault(r['query'], {'clicks': 0, 'impressions': 0, 'pos_w': 0.0, 'page': r['page']})
        a['clicks'] += int(r['clicks']); a['impressions'] += int(r['impressions'])
        a['pos_w'] += float(r['position']) * int(r['impressions'])
    for a in acc.values():
        a['position'] = round(a['pos_w'] / a['impressions'], 1) if a['impressions'] else None
        a['ctr'] = round(a['clicks'] / a['impressions'], 4) if a['impressions'] else 0.0
    return acc


def striking_distance(rows: Iterable[Row], limit: int = 10) -> list[Row]:
    q = _by_query(rows)
    th = thresholds(int(sum(a['impressions'] for a in q.values())))
    hits = [{'query': k, 'impressions': int(a['impressions']), 'position': a['position'], 'page': a['page']}
            for k, a in q.items()
            if a['impressions'] >= th['min_imp'] and a['position'] is not None and 4 <= a['position'] <= th['max_pos']]
    return sorted(hits, key=lambda h: (-h['impressions'], h['position']))[:limit]


def low_ctr(rows: Iterable[Row], limit: int = 10) -> list[Row]:
    """Queries in the top 10 whose CTR is under the site's own median top-10 CTR."""
    q = _by_query(rows)
    th = thresholds(int(sum(a['impressions'] for a in q.values())))
    top = {k: a for k, a in q.items() if a['position'] is not None and a['position'] <= 10 and a['impressions'] >= th['min_imp']}
    if not top:
        return []
    med = median(a['ctr'] for a in top.values())
    hits = [{'query': k, 'impressions': int(a['impressions']), 'ctr': a['ctr'], 'position': a['position'], 'median_ctr': med}
            for k, a in top.items() if a['ctr'] < med]
    return sorted(hits, key=lambda h: -h['impressions'])[:limit]
