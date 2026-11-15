"""redact.py — mask secrets in text before it leaves the host.

Used by claude-collector (prompts, Bash commands) and mac-watcher (process
command lines: MCP servers get API keys and DSNs as arguments). A secret keeps
its first 6 characters plus '...', the convention from the global secrets
rule, so a reader can still tell which key it was.

    from redact import redact
    redact('npx mcp --api-key ctx7sk-abcdef123456')  # → '... --api-key ctx7sk...'
"""
from __future__ import annotations

import re

KEEP = 6

# Tokens recognisable by their prefix, anywhere in the text.
_PREFIXED = re.compile(
    r'\b(?:sk-[A-Za-z0-9_-]{16,}|sk_(?:live|test)_[A-Za-z0-9]{16,}|ctx7sk-[A-Za-z0-9-]{8,}'
    r'|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}'
    r'|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|glpat-[A-Za-z0-9_-]{16,}'
    r'|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})')

# user:password@ inside a URL / DSN.
_URL_CRED = re.compile(r'(?P<pre>[a-z][a-z0-9+.-]*://[^\s:/@]+:)(?P<secret>[^\s@/]+)(?=@)', re.I)

# --api-key X, --token=X, Bearer X, password=X, "secret": "X", FOO_TOKEN=X …
_NAMED = re.compile(
    r'(?P<pre>(?:--?[\w-]*(?:key|token|secret|password|passwd|pwd)[\w-]*[ =]'
    r'|\bBearer\s+'
    r'|\b[\w-]*(?:api[_-]?key|token|secret|password|passwd|pwd)[\w-]*["\']?\s*[:=]\s*["\']?))'
    r'(?P<secret>(?!\$\()[^\s"\'&,;)]{8,})', re.I)  # `"$(secret x)"` is a lookup, not a value

# Polish "hasło: X" / "hasło=X" (any separator-ed value) and "moje hasło to X"
# (only when X looks like a password — has a digit or symbol — so prose survives).
_PL_SEP = re.compile(r'(?P<pre>\bhas(?:ł|l)[oa]\s*[:=]\s*["\']?)(?P<secret>(?!\$\()[^\s"\'&,;)]{8,})', re.I)
_PL_TO = re.compile(r'(?P<pre>\bhas(?:ł|l)[oa]\s+(?:to|is)\s+["\']?)'
                    r'(?P<secret>(?=[^\s"\'&,;)]*[\d!@#$%^*+=?~/])[^\s"\'&,;)]{8,})', re.I)

# sshpass -p X (the pattern from secrets.md) and `Authorization: Basic <base64>`.
_SSHPASS = re.compile(r'(?P<pre>\bsshpass\s+-p\s*["\']?)(?P<secret>(?!\$)[^\s"\']+)')
_BASIC = re.compile(r'(?P<pre>\bBasic\s+)(?P<secret>(?=[A-Za-z0-9+/]*[\d+/=])[A-Za-z0-9+/=]{12,})')


def mask(secret: str) -> str:
    return secret[:KEEP] + '...'


def redact(text: str) -> str:
    """Return text with every recognised secret masked. Idempotent."""
    if not text:
        return text
    out = _URL_CRED.sub(lambda m: m.group('pre') + mask(m.group('secret')), text)
    for rx in (_NAMED, _PL_SEP, _PL_TO, _SSHPASS, _BASIC):
        out = rx.sub(lambda m: m.group('pre') + _keep_masked(m.group('secret')), out)
    return _PREFIXED.sub(lambda m: _keep_masked(m.group(0)), out)


def _keep_masked(secret: str) -> str:
    return secret if secret.endswith('...') and len(secret) <= KEEP + 3 else mask(secret)
