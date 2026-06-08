"""home-ops agent runtime — shared HTTP, env loading, self-logging.

Every watcher (elitedesk/win10/rpi) and the planner-sync worker imports
from here. Single source of truth for:
  * INGEST_URL / INGEST_TOKEN env loading
  * X-Ingest-Token POST helpers with retry semantics
  * Self-emit (`agent:<name>` source convention)
  * METRIC_URL derivation from base ingest URL

Usage:
    from agents._common import IngestClient
    ic = IngestClient.from_env(host='elitedesk', source='agent:elitedesk-watcher')
    ic.post_events([event_dict])              # batched, 3-retry
    ic.post_metrics(metric_dict)              # single, no retry
    ic.post_log('info', 'starting up')        # self-emit one event
"""
from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Sequence


# ── shutdown coordination ─────────────────────────────────────────────


class Shutdown:
    """Cross-thread shutdown signal. Install once at process start.

    Usage in a loop body:
        while not shutdown.wait(POLL_INTERVAL):
            do_one_tick()

    install() registers SIGTERM and SIGINT handlers that set the event.
    On Windows under WinSW, KeyboardInterrupt from the wrapper still
    reaches Python's signal layer for SIGINT; SIGTERM is unavailable on
    Windows so install() just registers SIGINT there.
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    def install(self, on_signal: Callable[[int], None] | None = None) -> None:
        def handle(signum: int, _frame: Any) -> None:
            self._event.set()
            if on_signal is not None:
                try:
                    on_signal(signum)
                except Exception as e:  # noqa: BLE001  best-effort callback
                    print(f'shutdown callback raised: {e}', file=sys.stderr)

        signal.signal(signal.SIGINT, handle)
        if hasattr(signal, 'SIGTERM'):
            try:
                signal.signal(signal.SIGTERM, handle)
            except (ValueError, OSError):
                pass  # Windows: SIGTERM may be unavailable

    def is_set(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)

    def set(self) -> None:
        self._event.set()


class IngestClient:
    """Single shared HTTP surface for agents. Construct via from_env() in
    almost every case; the explicit constructor is for tests."""

    def __init__(
        self,
        *,
        host: str,
        source: str,
        events_url: str,
        metrics_url: str,
        token: str,
        timeout: float = 5.0,
    ) -> None:
        self.host = host
        self.source = source
        self.events_url = events_url
        self.metrics_url = metrics_url
        self.token = token
        self.timeout = timeout

    @classmethod
    def from_env(
        cls,
        *,
        host: str,
        source: str | None = None,
        timeout: float = 5.0,
    ) -> 'IngestClient':
        """Read INGEST_URL / INGEST_TOKEN / METRIC_URL from os.environ.
        Exits with code 1 if INGEST_URL or INGEST_TOKEN is missing —
        agents have no useful fallback so this is correct startup behavior."""
        ingest_url = (os.environ.get('INGEST_URL') or '').rstrip('/')
        token = os.environ.get('INGEST_TOKEN', '')
        if not ingest_url or not token:
            print('INGEST_URL and INGEST_TOKEN required', file=sys.stderr)
            sys.exit(1)
        metric_url = os.environ.get('METRIC_URL') or ingest_url.replace('/api/ingest', '/api/metrics')
        return cls(
            host=host,
            source=source or f'agent:{host}-watcher',
            events_url=ingest_url,
            metrics_url=metric_url,
            token=token,
            timeout=timeout,
        )

    def _post(self, url: str, body: dict[str, Any]) -> bool:
        status, _ = self.request(url, body)
        return 200 <= status < 300

    def request(
        self,
        url: str,
        body: dict[str, Any],
        timeout: float | None = None,
    ) -> tuple[int, dict[str, Any] | None]:
        """Generic token-authed POST. Returns (status, parsed_body). status=0
        means network error (no response received). For consumers that need
        more than the success/failure bit returned by the higher-level
        helpers — e.g. the planner-sync worker reads the upserted/removed
        counts from the response."""
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            method='POST',
            headers={'Content-Type': 'application/json', 'X-Ingest-Token': self.token},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read())
            except (json.JSONDecodeError, ValueError, OSError):
                return e.code, None
        except (urllib.error.URLError, TimeoutError, OSError):
            return 0, None

    def post_events(self, events: Sequence[dict[str, Any]], retries: int = 3) -> bool:
        """Batched events with exponential-ish backoff. Returns True on success,
        False after dropping. Used by the shipper loop of journald/docker
        watchers."""
        body = {'events': list(events)}
        for attempt in range(retries):
            if self._post(self.events_url, body):
                return True
            time.sleep(1 + attempt)
        print(f'dropped {len(events)} events after {retries} retries', file=sys.stderr)
        return False

    def post_metrics(self, metric: dict[str, Any]) -> bool:
        """Single metric sample. No retry — next tick re-samples; a dropped
        single sample isn't worth blocking the sampler thread."""
        if not self._post(self.metrics_url, metric):
            print('metric POST failed', file=sys.stderr)
            return False
        return True

    def post_log(
        self,
        level: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Self-emit a lifecycle / error event using this agent's source."""
        event: dict[str, Any] = {
            'host': self.host,
            'source': self.source,
            'level': level,
            'message': message[:8000],
        }
        if data:
            event['data'] = data
        if not self._post(self.events_url, {'events': [event]}):
            print(f'self-log failed: {message}', file=sys.stderr)
