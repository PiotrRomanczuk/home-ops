"""status_auth.py — the token behind POST /stop on the status page.

STATE/status.token (mode 600, made on first use). The page is plain HTTP without a login, so any other web page
could POST a form to 127.0.0.1:8787/stop (CSRF). The form therefore carries the token, which a foreign page
cannot read; /stop without it is refused. On a loopback host the token is a hidden field of the form; on any
other host (SPRINT_STATUS_HOST=0.0.0.0) everyone on the LAN can read the page, so the form asks for the token
(`cat STATE/status.token`) instead of printing it.
"""
from __future__ import annotations

import hmac
import html
import os
import secrets
from pathlib import Path

LOOPBACK = ('127.0.0.1', 'localhost', '::1')


def token(state: Path) -> str:
    path = state / 'status.token'
    if not path.exists():
        state.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(secrets.token_urlsafe(24))
    return path.read_text().strip()


def valid(state: Path, given: str) -> bool:
    return bool(given) and hmac.compare_digest(given.encode(), token(state).encode())


def stop_form(state: Path, host: str) -> str:
    secret = token(state)  # also makes the file, so `cat status.token` works before the first stop
    field = (f'<input type="hidden" name="token" value="{html.escape(secret)}">' if host in LOOPBACK else
             '<input type="password" name="token" placeholder="token z status.token" required> ')
    return ('<form method="post" action="/stop" onsubmit="return confirm(\'Zatrzymać agentów?\')">'
            f'{field}<button>Zatrzymaj agentów Claude</button></form>')
