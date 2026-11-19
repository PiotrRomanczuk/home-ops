"""status_panels.py — the budget tiles and the GPU section of the status page (status.py).

Reads what the services already write: STATE/usage.json (runner.py, budget.py) and
STATE/gpu/status.json (the GPU supervisor). Never calls /usage itself.
"""
from __future__ import annotations

import html
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import budget as b
import config

e = html.escape


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def limits(state: Path) -> tuple[b.Limits, float]:
    data = _read(state / 'usage.json')
    parsed = {k: {'percent': v['percent'], 'resets_at': b.when(v.get('resets_at'))} for k, v in (data.get('limits') or {}).items()}
    return parsed, float(data.get('read_at') or 0)


def budget_tiles(state: Path) -> tuple[list[tuple[str, str]], str]:
    """Tiles (week %, pace line, session %) and why Claude agents may or may not start now."""
    cfg = config.load(state)['claude']
    lim, read_at = limits(state)
    week, session = lim.get('weekly') or {}, lim.get('session') or {}
    line = b.pace(cfg['weekly_cap'], cfg['pace_head_start'], week.get('resets_at'), datetime.now(timezone.utc))
    tiles = [(f'{week.get("percent", 0):.0f}%', f'tydzień (limit {cfg["weekly_cap"]}%)'),
             (f'{line:.0f}%', 'linia tempa'), (f'{session.get("percent", 0):.0f}%', 'sesja 5 h')]
    if not config.window_end(cfg['windows'], datetime.now()):
        why = 'poza oknem (' + ', '.join(cfg['windows']) + ')'
    elif time.time() - read_at > b.STALE_S:
        why = 'odczyt limitów nieaktualny'
    else:
        why = b.verdict(lim, cfg, 'sonnet', datetime.now(timezone.utc)) or 'mogą startować'
    return tiles, why


def gpu_html(state: Path) -> str:
    s = _read(state / 'gpu' / 'status.json')
    if not s:
        return '<p class="dim">nadzorca GPU nie działa</p>'
    shards = ', '.join(f'{n}: {v}' for n, v in sorted((s.get('shards') or {}).items())) or 'brak'
    rows = [('zadanie', s.get('job') or '—'), ('zrobione zadania', f'{s.get("jobs_done")}/{s.get("jobs_total")}'),
            ('shardy', shards), ('powód pauzy', s.get('reason') or 'brak — pracuje'),
            ('thermalState / pamięć', f'{s.get("thermal")} / {s.get("pressure")}'),
            ('bez ruchu myszy', f'{s.get("idle_min")} min'), ('odczyt', str(s.get('ts', ''))[11:16])]
    return '<table>' + ''.join(f'<tr><th>{e(k)}</th><td>{e(str(v))}</td></tr>' for k, v in rows) + '</table>'
