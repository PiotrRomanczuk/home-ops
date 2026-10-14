"""seo_metrics.py — pure computations for seo-analyse.py (no DB, no network).

Input rows are plain dicts shaped like seo_gsc_daily / seo_ga4_daily. Every
function here is unit-tested in tests/test_seo_analyse.py; the main script
only glues psql → these → render/LLM.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Iterable

Row = dict[str, Any]


def split_windows(rows: Iterable[Row], end: date, days: int = 7) -> tuple[list[Row], list[Row]]:
    """(current, previous) windows of `days` each, current ending at `end` (inclusive)."""
    cur_start = end - timedelta(days=days - 1)
    prev_start = cur_start - timedelta(days=days)
    cur, prev = [], []
    for r in rows:
        d = r['day'] if isinstance(r['day'], date) else date.fromisoformat(str(r['day']))
        if cur_start <= d <= end:
            cur.append(r)
        elif prev_start <= d < cur_start:
            prev.append(r)
    return cur, prev


def _agg(rows: Iterable[Row], key: str) -> dict[str, dict[str, float]]:
    """Sum clicks/impressions and impression-weight position per `key` value."""
    acc: dict[str, dict[str, float]] = defaultdict(lambda: {'clicks': 0, 'impressions': 0, 'pos_w': 0.0})
    for r in rows:
        a = acc[r[key]]
        imp = int(r['impressions'])
        a['clicks'] += int(r['clicks'])
        a['impressions'] += imp
        a['pos_w'] += float(r['position']) * imp
    out = {}
    for k, a in acc.items():
        pos = round(a['pos_w'] / a['impressions'], 1) if a['impressions'] else None
        out[k] = {'clicks': int(a['clicks']), 'impressions': int(a['impressions']), 'position': pos}
    return out


def totals(rows: Iterable[Row]) -> dict[str, float | None]:
    a = _agg(({**r, '_all': 1} for r in rows), '_all')
    if not a:
        return {'clicks': 0, 'impressions': 0, 'position': None, 'ctr': None}
    t = a[1]
    ctr = round(t['clicks'] / t['impressions'], 4) if t['impressions'] else None
    return {**t, 'ctr': ctr}


def query_deltas(cur: list[Row], prev: list[Row], limit: int = 15) -> dict[str, list[Row]]:
    """Top queries by impressions with deltas vs the previous window, plus new/lost."""
    c, p = _agg(cur, 'query'), _agg(prev, 'query')
    top = sorted(c.items(), key=lambda kv: (-kv[1]['impressions'], -kv[1]['clicks']))[:limit]
    out = []
    for q, m in top:
        pm = p.get(q)
        out.append({
            'query': q, **m,
            'd_impressions': m['impressions'] - (pm['impressions'] if pm else 0),
            'd_position': (round(m['position'] - pm['position'], 1)
                           if pm and m['position'] is not None and pm['position'] is not None else None),
        })
    new = sorted((q for q in c if q not in p), key=lambda q: -c[q]['impressions'])[:limit]
    lost = sorted((q for q in p if q not in c), key=lambda q: -p[q]['impressions'])[:limit]
    return {'top': out, 'new': [{'query': q, **c[q]} for q in new], 'lost': [{'query': q, **p[q]} for q in lost]}


def page_deltas(cur: list[Row], prev: list[Row], limit: int = 10) -> list[Row]:
    c, p = _agg(cur, 'page'), _agg(prev, 'page')
    top = sorted(c.items(), key=lambda kv: -kv[1]['impressions'])[:limit]
    return [{'page': pg, **m, 'd_impressions': m['impressions'] - (p[pg]['impressions'] if pg in p else 0)}
            for pg, m in top]


def compile_areas(cfg: dict[str, Any]) -> list[tuple[str, str, str, re.Pattern[str]]]:
    return [(a['key'], a['label'], a.get('line', ''), re.compile(a['pattern'], re.IGNORECASE)) for a in cfg['areas']]


def classify_area(query: str, areas: list[tuple[str, str, str, re.Pattern[str]]]) -> str | None:
    for key, _label, _line, rx in areas:
        if rx.search(query):
            return key
    return None


def area_breakdown(cur: list[Row], prev: list[Row], cfg: dict[str, Any]) -> list[Row]:
    """Impressions/clicks/position per area (first regex wins), with deltas; the
    answer to 'which districts actually generate searches'. Unmatched → no_area."""
    areas = compile_areas(cfg)
    labels = {k: (lbl, line) for k, lbl, line, _ in areas}
    no_area = cfg.get('no_area_label', 'none')

    def tag(rows: list[Row]) -> list[Row]:
        return [{**r, 'area': classify_area(r['query'], areas) or no_area} for r in rows]

    c, p = _agg(tag(cur), 'area'), _agg(tag(prev), 'area')
    out = []
    for key in sorted(set(c) | set(p), key=lambda k: -(c.get(k, {}).get('impressions', 0))):
        m = c.get(key, {'clicks': 0, 'impressions': 0, 'position': None})
        lbl, line = labels.get(key, (key, ''))
        out.append({'area': key, 'label': lbl, 'line': line, **m,
                    'd_impressions': m['impressions'] - p.get(key, {}).get('impressions', 0),
                    'queries': sorted({r['query'] for r in tag(cur) if r['area'] == key})[:8]})
    return out


def ga4_summary(rows: list[Row]) -> dict[str, Any]:
    """Sessions per source/medium and summed tracked events over the window."""
    by_sm: dict[str, int] = defaultdict(int)
    events: dict[str, int] = defaultdict(int)
    for r in rows:
        by_sm[r['source_medium']] += int(r['sessions'])
        for name, n in (r.get('events') or {}).items():
            events[name] += int(n)
    top = sorted(by_sm.items(), key=lambda kv: -kv[1])[:8]
    return {'sessions': sum(by_sm.values()), 'by_source': [{'source_medium': k, 'sessions': v} for k, v in top],
            'events': dict(sorted(events.items()))}
