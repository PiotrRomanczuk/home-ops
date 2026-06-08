#!/usr/bin/env python3
"""rpi-watcher — host metrics + SoC temp for the Pi monitoring box.

Sibling of elitedesk-watcher and win10-watcher. No GPU (Pi 5 has only a small
VideoCore — no separate sampling). Pi's CPU/SoC temperature lands in
data.cpu_temp_c rather than gpu_temp_c — the schema column is GPU-specific.

Env:
  INGEST_URL       (required) e.g. http://192.168.1.75:64421/api/ingest
  INGEST_TOKEN     (required) shared secret
  HOST_NAME        defaults to 'rpi'
  METRIC_INTERVAL  seconds between samples (default 30)
  METRIC_DISK_PATH default '/'
  METRIC_TOP_N     top-N processes (default 10)
  TEMP_PATH        thermal zone file (default /sys/class/thermal/thermal_zone0/temp)
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

INGEST_URL = os.environ.get('INGEST_URL', '')
INGEST_TOKEN = os.environ.get('INGEST_TOKEN', '')
HOST_NAME = os.environ.get('HOST_NAME', 'rpi')
METRIC_INTERVAL = float(os.environ.get('METRIC_INTERVAL', '30'))
METRIC_URL = os.environ.get('METRIC_URL') or INGEST_URL.replace('/api/ingest', '/api/metrics')
METRIC_DISK_PATH = os.environ.get('METRIC_DISK_PATH', '/')
METRIC_TOP_N = int(os.environ.get('METRIC_TOP_N', '10'))
TEMP_PATH = Path(os.environ.get('TEMP_PATH', '/sys/class/thermal/thermal_zone0/temp'))

SELF_SOURCE = f'agent:{HOST_NAME}-watcher'

if not INGEST_URL or not INGEST_TOKEN:
    print('INGEST_URL and INGEST_TOKEN required', file=sys.stderr)
    sys.exit(1)


def _post(url: str, body: dict[str, Any]) -> bool:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method='POST',
        headers={'Content-Type': 'application/json', 'X-Ingest-Token': INGEST_TOKEN},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return 200 <= r.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def post_log(level: str, message: str, data: dict[str, Any] | None = None) -> None:
    ev: dict[str, Any] = {'host': HOST_NAME, 'source': SELF_SOURCE, 'level': level, 'message': message[:8000]}
    if data:
        ev['data'] = data
    if not _post(INGEST_URL, {'events': [ev]}):
        print(f'self-log failed: {message}', file=sys.stderr)


def send_metric(metric: dict[str, Any]) -> None:
    if not _post(METRIC_URL, metric):
        print('metric POST failed', file=sys.stderr)


def read_soc_temp_c() -> float | None:
    """Return CPU/SoC temperature in °C, or None if unreadable."""
    try:
        return round(int(TEMP_PATH.read_text().strip()) / 1000, 1)
    except (FileNotFoundError, PermissionError, ValueError, OSError):
        return None


def metric_sampler_loop() -> None:
    try:
        import psutil
    except ImportError:
        post_log('error', 'psutil not installed; metric sampling disabled')
        return

    psutil.cpu_percent(interval=None)
    last_net = psutil.net_io_counters()
    last_net_ts = time.monotonic()

    while True:
        time.sleep(METRIC_INTERVAL)
        try:
            now = time.monotonic()
            cpu_pct = psutil.cpu_percent(interval=None)
            try:
                load_1, _, _ = psutil.getloadavg()
            except (AttributeError, OSError):
                load_1 = 0.0
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()
            disk = psutil.disk_usage(METRIC_DISK_PATH)
            net = psutil.net_io_counters()
            elapsed = max(now - last_net_ts, 0.001)
            net_rx = (net.bytes_recv - last_net.bytes_recv) / elapsed / 1024
            net_tx = (net.bytes_sent - last_net.bytes_sent) / elapsed / 1024
            last_net, last_net_ts = net, now

            procs_cpu, procs_mem = [], []
            for p in psutil.process_iter(['name', 'pid', 'cpu_percent', 'memory_info']):
                try:
                    i = p.info
                    if (i.get('cpu_percent') or 0) > 0:
                        procs_cpu.append({'name': i.get('name') or '?', 'pid': i['pid'], 'pct': round(i['cpu_percent'], 1)})
                    rss = i['memory_info'].rss if i.get('memory_info') else 0
                    if rss > 0:
                        procs_mem.append({'name': i.get('name') or '?', 'pid': i['pid'], 'rss_mb': rss // (1024 * 1024)})
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            top_cpu = sorted(procs_cpu, key=lambda x: x['pct'], reverse=True)[:METRIC_TOP_N]
            top_mem = sorted(procs_mem, key=lambda x: x['rss_mb'], reverse=True)[:METRIC_TOP_N]

            data: dict[str, Any] = {'top_cpu': top_cpu, 'top_mem': top_mem}
            temp_c = read_soc_temp_c()
            if temp_c is not None:
                data['cpu_temp_c'] = temp_c

            metric: dict[str, Any] = {
                'host': HOST_NAME,
                'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'cpu_pct': round(cpu_pct, 1),
                'cpu_load_1': round(load_1, 2),
                'mem_pct': round(mem.percent, 1),
                'mem_used_mb': mem.used // (1024 * 1024),
                'mem_total_mb': mem.total // (1024 * 1024),
                'swap_pct': round(swap.percent, 1),
                'disk_pct': round(disk.percent, 1),
                'net_rx_kbps': round(net_rx, 1),
                'net_tx_kbps': round(net_tx, 1),
                'data': data,
            }
            send_metric(metric)
        except (psutil.Error, OSError) as e:
            print(f'metric sample failed: {e}', file=sys.stderr)


def main() -> None:
    post_log('info', f'rpi-watcher up: interval={METRIC_INTERVAL}s temp_path={TEMP_PATH}')
    try:
        metric_sampler_loop()
    except KeyboardInterrupt:
        post_log('info', 'rpi-watcher shutting down (SIGINT)')


if __name__ == '__main__':
    main()
