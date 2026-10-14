"""seo_google.py — stdlib-only Google API plumbing for seo-collect.py.

Service-account OAuth without google-auth: the JWT is assembled here and
RS256-signed by the system `openssl` binary (present on elitedesk), so the
collector keeps the repo's no-pip-install rule. The private key only ever
touches a 0600 temp file that is deleted right after signing.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

SCOPES = (
    'https://www.googleapis.com/auth/webmasters.readonly',
    'https://www.googleapis.com/auth/analytics.readonly',
)


class GoogleApiError(RuntimeError):
    """Non-2xx from a Google endpoint. Message carries status + a body excerpt."""


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def jwt_signing_input(sa: dict[str, Any], now: int, scopes: tuple[str, ...] = SCOPES) -> str:
    """`header.claims` (unsigned) for the OAuth jwt-bearer grant, valid 1h."""
    header = {'alg': 'RS256', 'typ': 'JWT'}
    claims = {
        'iss': sa['client_email'],
        'scope': ' '.join(scopes),
        'aud': sa.get('token_uri', 'https://oauth2.googleapis.com/token'),
        'iat': now,
        'exp': now + 3600,
    }
    enc = lambda d: b64url(json.dumps(d, separators=(',', ':')).encode())  # noqa: E731
    return f'{enc(header)}.{enc(claims)}'


def rs256_sign(signing_input: str, private_key_pem: str) -> str:
    fd, key_path = tempfile.mkstemp(prefix='seo-sa-', suffix='.pem')
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(private_key_pem)
        sig = subprocess.run(
            ['openssl', 'dgst', '-sha256', '-sign', key_path],
            input=signing_input.encode(), capture_output=True, check=True,
        ).stdout
    finally:
        os.unlink(key_path)
    return b64url(sig)


def http_json(url: str, *, body: Any = None, headers: dict[str, str] | None = None,
              form: dict[str, str] | None = None, timeout: float = 30.0) -> Any:
    """POST (body/form) or GET (neither) returning parsed JSON; raises GoogleApiError."""
    hdrs = dict(headers or {})
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        hdrs['Content-Type'] = 'application/x-www-form-urlencoded'
    elif body is not None:
        data = json.dumps(body).encode()
        hdrs['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=hdrs, method='POST' if data else 'GET')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        excerpt = e.read()[:400].decode(errors='replace')
        raise GoogleApiError(f'{e.code} from {url.split("?")[0]}: {excerpt}') from None


def access_token(sa_path: str) -> str:
    """Exchange the service-account key at sa_path for a 1h bearer token."""
    with open(sa_path) as f:
        sa = json.load(f)
    unsigned = jwt_signing_input(sa, int(time.time()))
    assertion = f'{unsigned}.{rs256_sign(unsigned, sa["private_key"])}'
    resp = http_json(
        sa.get('token_uri', 'https://oauth2.googleapis.com/token'),
        form={'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer', 'assertion': assertion},
    )
    return resp['access_token']
