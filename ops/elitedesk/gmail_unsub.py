"""gmail_unsub.py — find every mailing list the mailbox receives and unsubscribe on request.

Discovery is read-only (IMAP header fetch of messages carrying List-Unsubscribe).
Unsubscribing only uses RFC 8058 one-click (HTTPS POST `List-Unsubscribe=One-Click`):
no page is opened, nothing is sent from the mailbox. mailto:/plain-link lists are
reported for manual handling.
"""
from __future__ import annotations

import imaplib
import json
import re
import time
import urllib.error
import urllib.request
from email.utils import parseaddr

from gmail_imap import all_mail_box, decode, epoch_ms

FETCH = ('(INTERNALDATE BODY.PEEK[HEADER.FIELDS (FROM SUBJECT LIST-ID LIST-UNSUBSCRIBE '
         'LIST-UNSUBSCRIBE-POST)])')
_URI = re.compile(r'<([^>]+)>')
_DATE = re.compile(rb'INTERNALDATE "([^"]+)"')


def parse_unsub(value: str, post: str) -> dict:
    uris = _URI.findall(value or '')
    https = next((u for u in uris if u.lower().startswith('https://')), None)
    mailto = next((u for u in uris if u.lower().startswith('mailto:')), None)
    one_click = bool(https and 'one-click' in (post or '').lower())
    method = 'one-click' if one_click else 'link' if https else 'mailto' if mailto else 'none'
    return {'method': method, 'https': https, 'mailto': mailto}


def headers_of(raw: bytes) -> dict[str, str]:
    """Unfold and decode a small header block into {lower-name: value}."""
    out: dict[str, str] = {}
    for line in re.sub(rb'\r?\n[ \t]+', b' ', raw).decode('utf-8', 'replace').splitlines():
        name, sep, value = line.partition(':')
        if sep:
            out.setdefault(name.strip().lower(), decode(value.strip()))
    return out


def discover(imap: imaplib.IMAP4_SSL, since: str = '01-Jan-2010', chunk: int = 2000,
             log=print) -> list[dict]:
    """One entry per sender address: latest unsubscribe data + volume + last seen."""
    imap.select(all_mail_box(imap.list()[1]), readonly=True)
    uids = imap.uid('SEARCH', None, f'SINCE {since} HEADER List-Unsubscribe ""')[1][0].split()
    log(f'{len(uids)} messages carry List-Unsubscribe')
    lists: dict[str, dict] = {}
    for i in range(0, len(uids), chunk):
        data = imap.uid('FETCH', b','.join(uids[i:i + chunk]).decode(), FETCH)[1]
        for item in data:
            if not isinstance(item, tuple):
                continue
            h = headers_of(item[1])
            addr = parseaddr(h.get('from', ''))[1].lower()
            m = _DATE.search(item[0])
            ms = epoch_ms(m.group(1).decode()) if m else 0
            entry = lists.setdefault(addr, {'from': addr, 'count': 0, 'last_ms': 0})
            entry['count'] += 1
            if ms >= entry['last_ms']:
                entry.update(last_ms=ms, name=parseaddr(h.get('from', ''))[0], subject=h.get('subject', ''),
                             list_id=h.get('list-id', ''),
                             **parse_unsub(h.get('list-unsubscribe', ''), h.get('list-unsubscribe-post', '')))
    return sorted(lists.values(), key=lambda e: -e['last_ms'])


def one_click(url: str, opener=urllib.request.urlopen) -> tuple[bool, str]:
    """RFC 8058 POST. Returns (ok, short status)."""
    req = urllib.request.Request(url, data=b'List-Unsubscribe=One-Click', method='POST', headers={
        'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': 'home-ops-gmail-unsub/1.0'})
    try:
        with opener(req, timeout=20) as r:
            return 200 <= r.status < 300, str(r.status)
    except urllib.error.HTTPError as e:
        return False, str(e.code)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        return False, type(e).__name__


def unsubscribe(entries: list[dict], log_path, opener=urllib.request.urlopen, log=print) -> int:
    """POST one-click for each entry; append outcome to a JSONL log. Returns successes."""
    ok_count = 0
    with open(log_path, 'a') as f:
        for e in entries:
            if e.get('method') != 'one-click':
                continue
            ok, status = one_click(e['https'], opener)
            ok_count += ok
            f.write(json.dumps({'ts': int(time.time()), 'from': e['from'], 'ok': ok, 'status': status}) + '\n')
            log(f"  {'OK ' if ok else 'ERR'} {status:>4} {e['from']}")
    return ok_count
