"""mac_ship.py — get mac-watcher's samples to home-ops from wherever the laptop is.

  * every sample is first appended to a local daily archive
    (<state>/metrics-YYYY-MM-DD.jsonl, older days gzipped) — the full record
    stays on the Mac even after host_metrics prunes it at 30 days;
  * the server is reached over the LAN when the Mac is home, else over
    Tailscale (INGEST_FALLBACK_URL);
  * whatever can't be sent waits in the spool and is replayed, in order and
    with its original ts, before anything new;
  * SHIP=0 keeps everything local (archive + spool) — used until the server
    side (migration 032) is deployed.
"""
from __future__ import annotations

import gzip
import json
import shutil
import time
from pathlib import Path
from typing import Any

from _common import IngestClient
from mac_sample import on_home_lan
from spool import Spool


class Shipper:
    def __init__(self, *, host: str, token: str, lan_url: str, fallback_url: str,
                 state_dir: Path, ship: bool) -> None:
        self.host, self.token, self.ship = host, token, ship
        self.lan_url, self.fallback_url = lan_url.rstrip('/'), fallback_url.rstrip('/')
        self.state_dir = state_dir
        self.spool = Spool(state_dir / 'spool.jsonl')
        self.gzipped_day = ''

    def base(self) -> str:
        import psutil
        url = self.lan_url if on_home_lan(psutil.net_if_addrs()) else self.fallback_url
        return url.rsplit('/api/', 1)[0]

    def send(self, path: str, body: dict[str, Any]) -> bool:
        base = self.base()
        ic = IngestClient(host=self.host, source='agent:mac-watcher', events_url=base + '/api/ingest',
                          metrics_url=base + '/api/metrics', token=self.token)
        status, _ = ic.request(base + path, body, timeout=10)
        return 200 <= status < 300

    def deliver(self, metric: dict[str, Any], events: list[dict[str, Any]], snapshot: dict[str, Any]) -> None:
        self.archive(metric, events)
        if not self.ship or not self.token or not self.spool.flush(self.send):
            self.spool.append('/api/metrics', [metric])
            self.spool.append('/api/ingest', events)
            return
        if not self.send('/api/metrics', metric):
            self.spool.append('/api/metrics', [metric])
        if events and not self.send('/api/ingest', {'events': events}):
            self.spool.append('/api/ingest', events)
        self.send('/api/activity/now', {'host': self.host, 'snapshot': snapshot})  # latest only, never spooled

    def archive(self, metric: dict[str, Any], events: list[dict[str, Any]]) -> None:
        day = time.strftime('%Y-%m-%d')
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with (self.state_dir / f'metrics-{day}.jsonl').open('a') as f:
            f.write(json.dumps({'metric': metric, 'events': events}, ensure_ascii=False) + '\n')
        if self.gzipped_day != day:
            self.gzip_old(day)
            self.gzipped_day = day

    def gzip_old(self, today: str) -> None:
        for path in self.state_dir.glob('metrics-*.jsonl'):
            if path.stem.removeprefix('metrics-') >= today:
                continue
            with path.open('rb') as src, gzip.open(str(path) + '.gz', 'ab') as dst:
                shutil.copyfileobj(src, dst)
            path.unlink()
