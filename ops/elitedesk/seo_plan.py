"""seo_plan.py — evaluate SEO hypotheses against GSC rows (pure, tested).

A hypothesis targets queries (regex) and/or pages (paths). Its metric is
summed over matching GSC rows in a window. Verdicts compare the post-ship
window with the pre-ship baseline AND with the control pages' trend (pages no
shipped hypothesis targets), so a site-wide lift doesn't get credited to one
change. Small-site honesty: below MIN_IMPRESSIONS the verdict is
'insufficient', never helped/hurt.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Iterable
from urllib.parse import urlparse

Row = dict[str, Any]
MIN_IMPRESSIONS = 10          # per window, summed over the hypothesis' rows
HELPED_RATIO, HURT_RATIO = 1.25, 0.8   # vs control-adjusted expectation
CHECKPOINTS = (14, 28)


def _path(page: str) -> str:
    return urlparse(page).path or '/'


def matches(h: dict[str, Any], r: Row) -> bool:
    rx = h.get('target_queries') or ''
    pages = h.get('target_pages') or []
    by_q = bool(rx) and re.search(rx, r['query'], re.IGNORECASE) is not None
    by_p = bool(pages) and _path(r['page']) in pages
    return by_q or by_p


def metric_value(rows: Iterable[Row], metric: str) -> float | None:
    rows = list(rows)
    imp = sum(int(r['impressions']) for r in rows)
    clk = sum(int(r['clicks']) for r in rows)
    if metric == 'impressions':
        return float(imp)
    if metric == 'clicks':
        return float(clk)
    if imp == 0:
        return None
    if metric == 'ctr':
        return round(clk / imp, 4)
    return round(sum(float(r['position']) * int(r['impressions']) for r in rows) / imp, 2)


def window_rows(rows: Iterable[Row], start: date, end: date) -> list[Row]:
    out = []
    for r in rows:
        d = r['day'] if isinstance(r['day'], date) else date.fromisoformat(str(r['day']))
        if start <= d <= end:
            out.append(r)
    return out


def control_rows(rows: Iterable[Row], shipped: list[dict[str, Any]]) -> list[Row]:
    """Rows no shipped hypothesis targets — the site-wide trend reference."""
    return [r for r in rows if not any(matches(h, r) for h in shipped)]


def _ratio(after: float | None, before: float | None, metric: str) -> float | None:
    if after is None or before is None or before == 0:
        return None
    r = after / before
    return 1 / r if metric == 'position' and r else r   # lower position = better


def evaluate(h: dict[str, Any], rows: list[Row], shipped: list[dict[str, Any]], today: date,
             lag_days: int = 3) -> dict[str, Any]:
    """Verdict for one shipped hypothesis at every checkpoint already reached."""
    ship = h['shipped_at'] if isinstance(h['shipped_at'], date) else date.fromisoformat(str(h['shipped_at']))
    usable_end = today - timedelta(days=lag_days)
    metric = h.get('metric', 'impressions')
    base_start = ship - timedelta(days=max(CHECKPOINTS))
    base_rows = window_rows(rows, base_start, ship - timedelta(days=1))
    base_mine = [r for r in base_rows if matches(h, r)]
    ctrl = control_rows(rows, shipped)
    out: dict[str, Any] = {'baseline': {'start': base_start.isoformat(), 'end': (ship - timedelta(days=1)).isoformat(),
                                        'value': metric_value(base_mine, metric),
                                        'impressions': sum(int(r['impressions']) for r in base_mine)}}
    for days in CHECKPOINTS:
        end = ship + timedelta(days=days)
        if end > usable_end:
            out[f'day{days}'] = {'status': 'pending', 'due': (end + timedelta(days=lag_days)).isoformat()}
            continue
        mine = [r for r in window_rows(rows, ship, end) if matches(h, r)]
        # compare equal-length windows: last `days` of baseline vs `days` after ship
        base_eq = [r for r in window_rows(rows, ship - timedelta(days=days), ship - timedelta(days=1)) if matches(h, r)]
        ctrl_after = window_rows(ctrl, ship, end)
        ctrl_before = window_rows(ctrl, ship - timedelta(days=days), ship - timedelta(days=1))
        imp = sum(int(r['impressions']) for r in mine)
        mine_ratio = _ratio(metric_value(mine, metric), metric_value(base_eq, metric), metric)
        ctrl_ratio = _ratio(metric_value(ctrl_after, 'impressions'), metric_value(ctrl_before, 'impressions'), 'impressions')
        adj = (mine_ratio / ctrl_ratio) if (mine_ratio and ctrl_ratio) else mine_ratio
        if imp < MIN_IMPRESSIONS or adj is None:
            status = 'insufficient'
        elif adj >= HELPED_RATIO:
            status = 'helped'
        elif adj <= HURT_RATIO:
            status = 'hurt'
        else:
            status = 'neutral'
        out[f'day{days}'] = {'status': status, 'value': metric_value(mine, metric), 'before': metric_value(base_eq, metric),
                             'impressions': imp, 'ratio': round(mine_ratio, 2) if mine_ratio else None,
                             'control_ratio': round(ctrl_ratio, 2) if ctrl_ratio else None,
                             'adjusted': round(adj, 2) if adj else None}
    return out


def final_status(verdict: dict[str, Any]) -> str | None:
    """Terminal plan status once the last checkpoint is in; None while pending."""
    last = verdict.get(f'day{max(CHECKPOINTS)}', {})
    if last.get('status') in ('helped', 'hurt', 'neutral'):
        return last['status']
    if last.get('status') == 'insufficient':
        return 'neutral'
    return None
