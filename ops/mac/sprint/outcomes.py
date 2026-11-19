"""outcomes.py — what one headless run means for its task (runner.worker → classify → sprint_tasks.finish).

- limit: the subscription said no — `res.api_error_status == 429` / `api_error: usage_limit_reached`, or the
  limit wording together with a reset hour or a /usage reading that confirms it. Back to queue/ on the same
  model and attempts, `not_before` = the reset from the message ("resets 4:50am (Europe/Warsaw)"), else from
  /usage, else now + 15 min, and `resume: <session_id>` so the next run continues that session. Only a session
  or weekly limit pauses every Claude worker; a per-model week (Fable) holds just this task.
- interrupted: the job's stop (SIGTERM/SIGKILL: rc 143/137, -15/-9) or a Claude model's timeout (rc 124) —
  back to queue/ in 10 min on the same model; the third one fails the task. A local model's timeout is that
  model being too slow, so it stays a retry (→ sonnet). A resumed run whose session is gone ("No conversation
  found") is interrupted too, with `resume` dropped: the next run starts afresh.
- done: rc 0, no error and results/<id>.md written during this run.
- retry: anything else. It escalates the model, except `pr-fix` / `ci` / `code` on a Claude model: those fail
  on CI, lint or hooks rather than on the model, so the second try stays on it with the first try's ending.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import budget as b

LIMIT_RE = re.compile(r'usage.?limit|session.?limit|weekly.?limit|limit.?reached|rate.?limit|hit your .{0,20}limit|out of .*usage', re.I)
# "resets 4:50am (Europe/Warsaw)"; a weekly one may carry a date: "resets Nov 23, 5pm (Europe/Warsaw)"
RESET_RE = re.compile(r'resets\s+(?:on\s+)?(?:([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(?:at\s+)?)?'
                      r'(\d{1,2})(?::(\d{2}))?\s*([ap]m)\s*\(([^)]+)\)', re.I)
MONTHS = ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec')
SIGNALS = {143, 137, -15, -9}
TIMEOUT = 124
NO_SESSION = 'No conversation found'  # `--resume <id>` of a session that no longer exists
NO_ESCALATION = {'pr-fix', 'ci', 'code'}
BACKOFF, REQUEUE_IN, GRACE = timedelta(minutes=15), timedelta(minutes=10), timedelta(minutes=30)
GLOBAL = ('session', 'weekly')


def text_of(run: dict[str, Any]) -> str:
    res = run['res'] if isinstance(run['res'], dict) else {}
    return f'{res.get("result") or ""}\n{res.get("api_error") or ""}\n{run.get("stderr") or ""}'


def is_sure(res: dict[str, Any]) -> bool:
    return res.get('api_error_status') == 429 or res.get('api_error') == 'usage_limit_reached'


def reset_at(text: str, now: datetime) -> datetime | None:
    """The reset named in a limit message, as an aware datetime after `now`; None when there is none."""
    m = RESET_RE.search(text)
    if not m:
        return None
    month, day, hour, minute, ampm, zone = m.groups()
    try:
        local = now.astimezone(ZoneInfo(zone.strip()))
        t = local.replace(hour=int(hour) % 12 + (12 if ampm.lower() == 'pm' else 0), minute=int(minute or 0),
                          second=0, microsecond=0)
        if month:
            t = t.replace(month=MONTHS.index(month[:3].lower()) + 1, day=int(day))
    except (KeyError, ValueError):  # unknown zone (ZoneInfoNotFoundError is a KeyError), month or hour
        return None
    if t > now:
        return t
    if now - t < GRACE:  # the message rounds the reset down to the minute: it is (nearly) here
        return now + timedelta(minutes=5)
    return t.replace(year=t.year + 1) if month else t + timedelta(days=1)


def scope_of(text: str, model: str, limits: b.Limits, now: datetime) -> str:
    """Which limit ran out: session | weekly | <model> | unknown."""
    low = text.lower()
    if 'session limit' in low:
        return 'session'
    if model not in GLOBAL and model in low:
        return model
    if 'weekly limit' in low:
        return 'weekly'
    for key in (*GLOBAL, model):
        if b.exhausted_until(limits, now, (key,)):
            return key
    return 'unknown'


def wants_usage(run: dict[str, Any]) -> bool:
    """A limit signal without a reset hour: worth a fresh /usage reading before classify()."""
    res, text = run['res'] if isinstance(run['res'], dict) else {}, text_of(run)
    return (not run['model'].startswith('local:') and (is_sure(res) or bool(LIMIT_RE.search(text)))
            and reset_at(text, datetime.now().astimezone()) is None)


def limit_until(run: dict[str, Any], now: datetime, limits: b.Limits) -> tuple[datetime, str] | None:
    """(not before, scope) when the run hit a subscription limit; None otherwise. Needs no /usage reading."""
    res, model, text = run['res'] if isinstance(run['res'], dict) else {}, run['model'], text_of(run)
    sure = is_sure(res)
    if model.startswith('local:') or not (sure or LIMIT_RE.search(text)):
        return None
    scope = scope_of(text, model, limits, now)
    keys = (scope,) if scope != 'unknown' else (*GLOBAL, model)
    until = reset_at(text, now) or b.exhausted_until(limits, now, keys)
    if until is None and not sure:  # "rate limit" was only a word in an ordinary failure
        return None
    return until or now + BACKOFF, scope


def classify(run: dict[str, Any], now: datetime, *, kind: str | None = None, result_mtime: float | None = None,
             limits: b.Limits | None = None) -> tuple[str, dict[str, Any]]:
    """→ (outcome, meta). meta['set']: task fields to write (None drops one); meta['pause_until']: when every
    Claude worker may start again (session/weekly limits only); meta['escalate'] / meta['note'] for a retry."""
    res = run['res'] if isinstance(run['res'], dict) else {}
    rc, local = run['rc'], run['model'].startswith('local:')
    session = res.get('session_id') or None
    hit = limit_until(run, now, limits or {})
    if hit:
        until, scope = hit
        return 'limit', {'set': {'not_before': until.isoformat(timespec='seconds'), 'resume': session}, 'scope': scope,
                         'pause_until': until if scope in GLOBAL else None}
    if run.get('resumed') and NO_SESSION in text_of(run):  # the session to continue is gone: start afresh, same model
        return 'interrupted', {'set': {'not_before': None, 'resume': None}}
    if rc in SIGNALS or (rc == TIMEOUT and not local):
        return 'interrupted', {'set': {'not_before': (now + REQUEUE_IN).isoformat(timespec='seconds'), 'resume': session}}
    cleared = {'not_before': None, 'resume': None}
    if rc == 0 and not res.get('is_error') and result_mtime is not None and result_mtime >= run['started']:
        return 'done', {'set': cleared}
    escalate = local or kind not in NO_ESCALATION
    note = '' if escalate else str(res.get('result') or run.get('stderr') or f'rc {rc}, bez pliku wyniku')[-500:]
    return 'retry', {'set': cleared, 'escalate': escalate, 'note': note}


def mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return None
