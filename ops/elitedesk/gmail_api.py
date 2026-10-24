"""gmail_api.py — thin stdlib client for the Gmail REST API (users/me).

Only what the cleanup + daily analysis need: list message ids by query,
batch label changes, trash, labels and filters CRUD, header metadata.
Never calls batchDelete — permanent deletion is out of scope by design.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

BASE = 'https://gmail.googleapis.com/gmail/v1/users/me'
BATCH_LIMIT = 1000  # messages.batchModify hard cap
RETRY_STATUSES = {429, 500, 502, 503, 504}


class GmailError(RuntimeError):
    """Non-retryable (or retries exhausted) Gmail API failure."""


class RateLimiter:
    """Thread-safe, self-tuning pacing under the per-minute Gmail quota.

    The real per-project limit can sit below the documented 15 000 units/min,
    so this is AIMD: a quota error halves the rate and pauses everyone for a
    few seconds; every success nudges the rate back up towards the ceiling.
    """

    def __init__(self, units_per_sec: float, sleep: Callable[[float], None] = time.sleep,
                 floor: float = 10.0, pause: float = 5.0):
        self.rate, self._max, self._floor, self._pause = units_per_sec, units_per_sec, floor, pause
        self._sleep, self._next, self._last_cut = sleep, 0.0, -1e9
        self._lock = threading.Lock()

    def take(self, units: int) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + units / self.rate
        if start > now:
            self._sleep(start - now)

    def penalize(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now - self._last_cut > self._pause:  # one cut per burst of parallel errors
                self.rate = max(self._floor, self.rate / 2)
                self._last_cut = now
                self._next = max(self._next, now + self._pause)

    def reward(self) -> None:
        with self._lock:
            self.rate = min(self._max, self.rate + 0.05)


def _is_quota(code: int, body: bytes) -> bool:
    return code in RETRY_STATUSES or (code == 403 and (b'ate limit' in body or b'Quota exceeded' in body))


class Gmail:
    def __init__(self, token: Callable[[], str], *, sleep: Callable[[float], None] = time.sleep,
                 opener: Callable[..., Any] = urllib.request.urlopen, units_per_sec: float = 200):
        self._token, self._sleep, self._open = token, sleep, opener
        self._limit = RateLimiter(units_per_sec, sleep)

    def call(self, method: str, path: str, *, params: dict | None = None,
             body: Any = None, retries: int = 12, units: int = 5) -> Any:
        url = BASE + path + ('?' + urllib.parse.urlencode(params, doseq=True) if params else '')
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(retries + 1):
            self._limit.take(units)
            req = urllib.request.Request(url, data=data, method=method, headers={
                'Authorization': f'Bearer {self._token()}', 'Content-Type': 'application/json'})
            try:
                with self._open(req, timeout=60) as r:
                    raw = r.read()
                self._limit.reward()
                return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                err = e.read()
                e.close()
                if _is_quota(e.code, err) and attempt < retries:
                    self._limit.penalize()
                    continue
                raise GmailError(f'{e.code} {method} {path}: {err[:400].decode(errors="replace")}') from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt < retries:
                    self._sleep(min(2 ** attempt, 30))
                    continue
                raise GmailError(f'network {method} {path}: {e}') from None
        raise GmailError(f'retries exhausted: {method} {path}')  # pragma: no cover

    @property
    def rate(self) -> float:
        return self._limit.rate

    # --- messages -------------------------------------------------------
    def iter_ids(self, query: str, *, limit: int | None = None) -> Iterator[str]:
        """Message ids matching a Gmail search query (all pages, newest first)."""
        params: dict[str, Any] = {'q': query, 'maxResults': 500}
        seen = 0
        while True:
            page = self.call('GET', '/messages', params=params)
            for m in page.get('messages', []):
                yield m['id']
                seen += 1
                if limit and seen >= limit:
                    return
            if not page.get('nextPageToken'):
                return
            params['pageToken'] = page['nextPageToken']

    def batch_modify(self, ids: list[str], add: list[str] = (), remove: list[str] = ()) -> None:
        for i in range(0, len(ids), BATCH_LIMIT):
            self.call('POST', '/messages/batchModify', units=50, body={
                'ids': ids[i:i + BATCH_LIMIT], 'addLabelIds': list(add),
                'removeLabelIds': list(remove)})

    def trash(self, ids: list[str], workers: int = 8) -> None:
        """Per-message trash (fallback when batchModify refuses TRASH)."""
        with ThreadPoolExecutor(workers) as pool:
            list(pool.map(lambda i: self.call('POST', f'/messages/{i}/trash'), ids))

    def metadata(self, msg_id: str, names: tuple[str, ...] = ('From', 'Subject', 'Date')) -> dict:
        """Raw message resource with only the requested headers (5 quota units)."""
        return self.call('GET', f'/messages/{msg_id}', params={
            'format': 'metadata', 'metadataHeaders': list(names)})

    def headers(self, msg_id: str) -> dict[str, str]:
        msg = self.metadata(msg_id)
        hdrs = {h['name']: h['value'] for h in msg.get('payload', {}).get('headers', [])}
        return {'from': hdrs.get('From', ''), 'subject': hdrs.get('Subject', ''),
                'date': hdrs.get('Date', ''), 'labels': ','.join(msg.get('labelIds', []))}

    # --- labels ---------------------------------------------------------
    def labels(self) -> list[dict]:
        return self.call('GET', '/labels').get('labels', [])

    def create_label(self, name: str) -> dict:
        return self.call('POST', '/labels', body={
            'name': name, 'labelListVisibility': 'labelShow', 'messageListVisibility': 'show'})

    def patch_label(self, label_id: str, **fields: Any) -> dict:
        return self.call('PATCH', f'/labels/{label_id}', body=fields)

    def delete_label(self, label_id: str) -> None:
        self.call('DELETE', f'/labels/{label_id}')

    # --- filters --------------------------------------------------------
    def filters(self) -> list[dict]:
        return self.call('GET', '/settings/filters').get('filter', [])

    def create_filter(self, criteria: dict, action: dict) -> dict:
        return self.call('POST', '/settings/filters', body={'criteria': criteria, 'action': action})
