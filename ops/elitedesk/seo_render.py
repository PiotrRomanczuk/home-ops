"""seo_render.py — plain-text digest card for seo-analyse.py.

Deterministic, no LLM: this is what lands in the 07:00 e-mail even when the
Claude CLI is logged out. Width ≤ 78 so the digest's <pre> doesn't wrap.
"""
from __future__ import annotations

from typing import Any


def _pos(p: float | None) -> str:
    return f'{p:.1f}' if p is not None else '—'


def _delta(n: int) -> str:
    return f'{n:+d}' if n else '±0'


def _line(text: str, width: int = 78) -> str:
    return text if len(text) <= width else text[:width - 1] + '…'


def render_card(m: dict[str, Any]) -> str:
    """m = metrics dict built by seo-analyse.py (see build_metrics)."""
    t, p = m['totals'], m['totals_prev']
    lines = [
        f"{m['site']} · GSC 7 dni do {m['window_end']} vs poprzednie 7",
        '(GSC spóźnia się 2–3 dni; przy kilku wyświetleniach liczby są szumem)',
        f"wyświetlenia {t['impressions']} ({_delta(t['impressions'] - p['impressions'])}) · "
        f"kliknięcia {t['clicks']} ({_delta(t['clicks'] - p['clicks'])}) · "
        f"poz. {_pos(t['position'])} (było {_pos(p['position'])})",
    ]
    if m.get('ga4'):
        g = m['ga4']
        ev = ', '.join(f'{k}={v}' for k, v in g['events'].items()) or 'brak zdarzeń'
        lines.append(f"GA4: sesje {g['sessions']} · {ev}")
    lines.append('')
    lines.append('DZIELNICE (frazy z lokalizacją, wyśw. / klik / poz.)')
    for a in m['areas'][:10]:
        lines.append(_line(f"  {a['label']:<28} {a['impressions']:>4} ({_delta(a['d_impressions'])}) "
                           f"/ {a['clicks']:>2} / {_pos(a['position'])}   {a['line']}"))
    lines.append('')
    lines.append('TOP FRAZY (wyśw. Δ · poz. Δ)')
    for q in m['queries']['top'][:10]:
        dp = f"{q['d_position']:+.1f}" if q['d_position'] is not None else 'nowa'
        lines.append(_line(f"  {q['impressions']:>4} {_delta(q['d_impressions']):>4} · {_pos(q['position']):>5} {dp:>5}  {q['query']}"))
    if m['queries']['new']:
        lines.append(_line('NOWE: ' + '; '.join(q['query'] for q in m['queries']['new'][:6])))
    if m['queries']['lost']:
        lines.append(_line('ZNIKNĘŁY: ' + '; '.join(q['query'] for q in m['queries']['lost'][:6])))
    if not m['queries']['top']:
        lines.append('  (brak danych w tym oknie — kolektor jeszcze nie zebrał GSC albo strona nie ma wyświetleń)')
    return '\n'.join(lines)
