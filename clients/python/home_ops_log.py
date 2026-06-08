"""home_ops_log — drop-in client for emitting app:<slug> events.

Single-file, stdlib-only. Drop into any project that wants to surface its
lifecycle and errors in the home-ops console.

Usage:
    import home_ops_log as hops
    hops.init('guitar-crm')           # reads INGEST_URL/INGEST_TOKEN from env

    hops.event('stripe webhook received', data={'event_id': evt.id})
    hops.event('twilio 429', level='error', data={'pid': os.getpid()})

    with hops.lifecycle('send_reminders') as life:
        life.set_data({'count': len(batch)})
        # …work…
        # on success: emits send_reminders_succeeded with the data
        # on exception: emits send_reminders_failed with the data + error

Env:
    INGEST_URL    e.g. http://elitedesk.tail266853.ts.net:64421/api/ingest
                  or http://192.168.1.75:64421/api/ingest on LAN
    INGEST_TOKEN  shared secret (same one the watchers use)
    HOME_OPS_HOST optional override for the `host` field; defaults to socket.gethostname()

Failure mode: emit is best-effort. A failed POST prints to stderr and
returns; the calling code never sees the error. The whole point is to be
invisible in the happy path and recoverable in the bad path.
"""
from __future__ import annotations

import contextlib
import json
import os
import socket
import sys
import time
import traceback
import urllib.error
import urllib.request
from typing import Any

_SLUG: str | None = None
_URL: str = ''
_TOKEN: str = ''
_HOST: str = ''


def init(
    slug: str,
    *,
    ingest_url: str | None = None,
    ingest_token: str | None = None,
    host: str | None = None,
) -> None:
    """Configure the module. Call once at process start."""
    global _SLUG, _URL, _TOKEN, _HOST
    _SLUG = slug
    _URL = (ingest_url or os.environ.get('INGEST_URL') or '').rstrip('/')
    _TOKEN = ingest_token or os.environ.get('INGEST_TOKEN') or ''
    _HOST = host or os.environ.get('HOME_OPS_HOST') or socket.gethostname()


def event(
    message: str,
    *,
    level: str = 'info',
    data: dict[str, Any] | None = None,
) -> None:
    """Emit one app:<slug> event. Best-effort; failures print to stderr."""
    if not _SLUG or not _URL or not _TOKEN:
        return  # init() never called — fail silent
    body = {
        'host': _HOST,
        'source': f'app:{_SLUG}',
        'level': level,
        'message': message[:8000],
    }
    if data:
        body['data'] = data
    req = urllib.request.Request(
        _URL,
        data=json.dumps({'events': [body]}).encode(),
        method='POST',
        headers={'Content-Type': 'application/json', 'X-Ingest-Token': _TOKEN},
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            if not 200 <= r.status < 300:
                print(f'home_ops_log: non-2xx {r.status}', file=sys.stderr)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f'home_ops_log: emit failed ({type(e).__name__}): {message[:80]}', file=sys.stderr)


class _Lifecycle:
    """Returned by the `lifecycle` context manager. Lets the caller attach
    structured data before the closing event fires."""

    def __init__(self, stage: str, start_data: dict[str, Any] | None) -> None:
        self.stage = stage
        self.data: dict[str, Any] = dict(start_data or {})
        self.started_at = time.monotonic()

    def set_data(self, more: dict[str, Any]) -> None:
        self.data.update(more)

    def duration_ms(self) -> int:
        return int((time.monotonic() - self.started_at) * 1000)


@contextlib.contextmanager
def lifecycle(stage: str, data: dict[str, Any] | None = None):
    """Emit `<stage>_started` on entry, `<stage>_succeeded` on clean exit,
    `<stage>_failed` on exception (re-raised after emit)."""
    life = _Lifecycle(stage, data)
    event(f'{stage}_started', data=dict(life.data) or None)
    try:
        yield life
    except Exception as exc:
        end = {**life.data, 'duration_ms': life.duration_ms(), 'error': repr(exc)[:500]}
        event(f'{stage}_failed', level='error', data=end)
        # Optional: print the traceback in case the calling code does its own
        # error handling but loses the trace.
        if os.environ.get('HOME_OPS_LOG_TB') == '1':
            traceback.print_exc()
        raise
    else:
        end = {**life.data, 'duration_ms': life.duration_ms()}
        event(f'{stage}_succeeded', data=end)
