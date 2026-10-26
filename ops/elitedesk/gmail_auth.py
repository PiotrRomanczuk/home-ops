"""gmail_auth.py — stdlib-only installed-app OAuth for the personal Gmail mailbox.

One-time `authorize()` opens the browser, catches the redirect on a loopback
port and stores the refresh token (0600) next to the downloaded client JSON.
`access_token()` refreshes it on demand. The OAuth client must be a "Desktop
app" client whose consent screen is *In production* — Testing-mode refresh
tokens die after 7 days, which would break the daily run.
"""
from __future__ import annotations

import json
import os
import secrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from seo_google import http_json

SCOPES = (
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.settings.basic',
    'https://mail.google.com/',  # IMAP (XOAUTH2): bulk header reads without the REST per-minute quota
)
CONFIG_DIR = Path(os.environ.get('GMAIL_CONFIG_DIR', Path.home() / '.config' / 'home-ops'))
CLIENT_PATH = CONFIG_DIR / 'gmail-client.json'
TOKEN_PATH = CONFIG_DIR / 'gmail-token.json'
AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'


def load_client(path: Path = CLIENT_PATH) -> dict[str, str]:
    """The `installed` block of a Google 'Desktop app' client_secret JSON."""
    raw = json.loads(path.read_text())
    client = raw.get('installed') or raw.get('web')
    if not client:
        raise SystemExit(f'{path}: expected an "installed" OAuth client JSON')
    return client


def write_private(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(payload, f)


def _catch_code(port: int, state: str) -> str:
    """Serve exactly one request on 127.0.0.1:port and return the ?code=."""
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — http.server API
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            ok = q.get('state') == state and 'code' in q
            if ok:
                result['code'] = q['code']
            self.send_response(200 if ok else 400)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write('OK — możesz zamknąć kartę.'.encode() if ok else b'OAuth failed')

        def log_message(self, *_args):
            pass

    with HTTPServer(('127.0.0.1', port), Handler) as srv:
        while 'code' not in result:
            srv.handle_request()
    return result['code']


def authorize(port: int = 8765) -> None:
    client = load_client()
    redirect = f'http://127.0.0.1:{port}'
    state = secrets.token_urlsafe(16)
    url = AUTH_URL + '?' + urllib.parse.urlencode({
        'client_id': client['client_id'], 'redirect_uri': redirect, 'response_type': 'code',
        'scope': ' '.join(SCOPES), 'access_type': 'offline', 'prompt': 'consent', 'state': state,
    })
    print(f'Opening browser for consent. If it does not open, visit:\n{url}\n')
    webbrowser.open(url)
    code = _catch_code(port, state)
    tok = http_json(TOKEN_URL, form={
        'code': code, 'client_id': client['client_id'], 'client_secret': client['client_secret'],
        'redirect_uri': redirect, 'grant_type': 'authorization_code',
    })
    if 'refresh_token' not in tok:
        raise SystemExit('No refresh_token returned — revoke the app grant and retry.')
    write_private(TOKEN_PATH, {'refresh_token': tok['refresh_token'],
                               'access_token': tok['access_token'],
                               'expires_at': int(time.time()) + int(tok['expires_in'])})
    print(f'Saved token to {TOKEN_PATH}')


def access_token() -> str:
    """Valid bearer token; refreshes (and persists) when within 60 s of expiry."""
    if not TOKEN_PATH.exists():
        raise SystemExit(f'No {TOKEN_PATH} — run `gmail_cleanup.py auth` first.')
    tok = json.loads(TOKEN_PATH.read_text())
    if tok.get('expires_at', 0) - 60 > time.time():
        return tok['access_token']
    client = load_client()
    fresh = http_json(TOKEN_URL, form={
        'refresh_token': tok['refresh_token'], 'client_id': client['client_id'],
        'client_secret': client['client_secret'], 'grant_type': 'refresh_token',
    })
    tok.update(access_token=fresh['access_token'],
               expires_at=int(time.time()) + int(fresh['expires_in']))
    write_private(TOKEN_PATH, tok)
    return tok['access_token']
