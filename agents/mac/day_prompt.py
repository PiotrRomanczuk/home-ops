"""day_prompt.py — turn GET /api/journal/day into an LLM prompt and a Dziś card.

Pure functions (no network) so day-summary's wording is testable:
  facts(journal)          short Polish fact sheet the model reasons from
  build_prompt(j, tasks)  the full prompt (facts + Now tasks of hot/warm projects)
  next_steps(text)        the "Co dalej" bullets out of the model's answer
  card(j, steps, prev)    headline / items / metric for routine_report.card()
  pick_day(now)           which day a run without an argument summarises
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

# A run before this local hour is a catch-up after the Mac slept through 21:30
# (launchd fires the missed slot on wake-up), so it summarises yesterday.
EVENING_HOUR = 21


def pick_day(now: datetime) -> date:
    """Today from 21:00 on, otherwise yesterday (the 21:30 slot that was missed)."""
    return now.date() if now.hour >= EVENING_HOUR else now.date() - timedelta(days=1)

WEEKDAYS = ['pon', 'wt', 'śr', 'czw', 'pt', 'sob', 'nd']


def hm(minutes: float) -> str:
    m = int(round(minutes))
    return f'{m // 60} h {m % 60:02d} min' if m >= 60 else f'{m} min'


def _top(rows: list[dict[str, Any]], key: str, n: int = 3) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: -(r.get(key) or 0))[:n]


def facts(j: dict[str, Any]) -> list[str]:
    c = j.get('claude') or {}
    tot = c.get('totals') or {}
    out = [f'Mac nie spał: {hm(j.get("awake_min") or 0)}.',
           f'Claude: {tot.get("sessions", 0)} sesji, {tot.get("prompts", 0)} promptów, '
           f'aktywność {hm(tot.get("active_min") or 0)}, błędy narzędzi {tot.get("errors", 0)}.']
    for p in _top(c.get('by_project') or [], 'active_min', 6):
        out.append(f'- projekt {p.get("project_slug") or "(bez projektu)"}: {hm(p.get("active_min") or 0)}, '
                   f'{p.get("prompts", 0)} promptów, {p.get("sessions", 0)} sesji')
    for s in _top(c.get('sessions') or [], 'prompts_day', 8):
        out.append(f'- sesja „{s.get("title") or s.get("session_id", "")[:8]}” ({s.get("host")}, '
                   f'{s.get("project_slug") or "-"}): {s.get("prompts_day", 0)} promptów')
    for pr in (c.get('prs') or [])[:6]:
        out.append(f'- PR: {pr}')
    apps = j.get('apps') or {}
    if apps.get('cpu'):
        out.append('Najwięcej CPU: ' + ', '.join(f'{a["name"]} {int(a["cpu_s"] // 60)} min' for a in apps['cpu'][:4]))
    if apps.get('net'):
        out.append('Najwięcej sieci: ' + ', '.join(f'{a["name"]} {a["mb"]:.0f} MB' for a in apps['net'][:4]))
    for p in (j.get('procs') or [])[:8]:
        out.append(f'- w tle: {p.get("name")} ({p.get("reason")}) {str(p.get("cmd") or "")[:80]}')
    return out


def build_prompt(j: dict[str, Any], tasks: list[str]) -> str:
    """tasks: 'slug: task' lines; those of projects worked on today come first."""
    today = {p.get('project_slug') for p in (j.get('claude') or {}).get('by_project') or []}
    ranked = sorted(tasks, key=lambda t: t.split(':', 1)[0] not in today)
    lines = [
        'Jesteś asystentem Piotra (programista, projekty prywatne i JDG). Na podstawie faktów z jego dnia',
        'napisz krótko po polsku. Odpowiedz dokładnie w tym formacie, bez wstępu i zakończenia:',
        '', '## Dzień', '<2–3 zdania: na co poszedł czas, co się udało, co utknęło>', '', '## Co dalej',
        '- <krok 1>', '- <krok 2>', '- <krok 3>', '',
        'Zasady dla „Co dalej”: 3–5 punktów, każdy ≤ 140 znaków, zaczynający się od nazwy projektu.',
        'Najpierw dokończenie tego, co ruszał dziś (projekty z faktów), potem najwyżej jeden punkt z innych zadań Now.',
        'Nie wymyślaj faktów spoza listy.',
        '', f'Fakty z dnia {j.get("day")}:', *facts(j), '',
        'Zadania Now (najpierw projekty ruszane dziś):', *[f'- {t}' for t in ranked[:25]],
    ]
    return '\n'.join(lines)


def next_steps(text: str) -> list[str]:
    steps, inside = [], False
    for line in (text or '').splitlines():
        s = line.strip()
        if s.startswith('#'):
            inside = 'dalej' in s.lower()
        elif inside and s[:2] in ('- ', '* '):
            steps.append(s[2:].strip().replace('**', '')[:160])
    return steps[:5]


def card(j: dict[str, Any], steps: list[str], prev_active_min: float | None) -> dict[str, Any]:
    tot = (j.get('claude') or {}).get('totals') or {}
    active = float(tot.get('active_min') or 0)
    by_project = [p for p in (j.get('claude') or {}).get('by_project') or [] if p.get('project_slug')]
    projects = [p['project_slug'] for p in _top(by_project, 'active_min')]
    day = j.get('day') or ''
    try:
        from datetime import date
        d = date.fromisoformat(day)
        label = f'{WEEKDAYS[d.weekday()]} {d.day:02d}.{d.month:02d}'
    except ValueError:
        label = day
    head = f'{label}: {hm(active)} z Claude · {tot.get("sessions", 0)} sesji · {tot.get("prompts", 0)} promptów'
    if projects:
        head += ' · ' + ', '.join(projects)
    items = steps or [line.lstrip('- ') for line in facts(j)[2:7]]
    metric = {'label': 'aktywny czas z Claude', 'value': round(active / 60, 1), 'unit': 'h'}
    if prev_active_min is not None:
        metric['delta'] = round((active - prev_active_min) / 60, 1)
    return {'headline': head[:200], 'items': [(i, None) for i in items[:5]], 'metric': metric}
