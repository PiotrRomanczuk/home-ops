#!/usr/bin/env python3
"""rpi-watcher — host metrics + SoC temp + log shipping for the Pi monitoring box.

Sibling of elitedesk-watcher and win10-watcher. No GPU (Pi 5 has only a small
VideoCore — no separate sampling). Pi's CPU/SoC temperature lands in
data.cpu_temp_c rather than gpu_temp_c — the schema column is GPU-specific.

Log shipping (same follower/shipper pattern as elitedesk-watcher):
  - docker container stdout/stderr for WATCH_CONTAINERS → source docker:<name>
  - journald at warning-or-worse across all units → source journald:<unit>

Env:
  INGEST_URL        (required) e.g. http://192.168.1.75:64421/api/ingest
  INGEST_TOKEN      (required) shared secret
  HOST_NAME         defaults to 'rpi'
  METRIC_INTERVAL   seconds between samples (default 30)
  METRIC_DISK_PATH  default '/'
  METRIC_TOP_N      top-N processes (default 10)
  TEMP_PATH         thermal zone file (default /sys/class/thermal/thermal_zone0/temp)
  WATCH_CONTAINERS  comma-separated; default uptime-kuma,beszel,homeassistant
  JOURNAL_PRIORITY  journald -p threshold (default 4 = warning)
  BATCH_MAX         shipper batch size (default 100)
  BATCH_SECONDS     shipper flush interval (default 3)
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

# _common.py lives next to this script in production (~/bin/_common.py) and
# one level up in the repo (agents/_common.py). Try both so dev + deploy both
# work without any package wiring.
_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))
sys.path.insert(0, str(_here.parent))
from _common import IngestClient, Shutdown  # noqa: E402

HOST_NAME = os.environ.get('HOST_NAME', 'rpi')
METRIC_INTERVAL = float(os.environ.get('METRIC_INTERVAL', '30'))
METRIC_DISK_PATH = os.environ.get('METRIC_DISK_PATH', '/')
METRIC_TOP_N = int(os.environ.get('METRIC_TOP_N', '10'))
TEMP_PATH = Path(os.environ.get('TEMP_PATH', '/sys/class/thermal/thermal_zone0/temp'))
WATCH_CONTAINERS = [c.strip() for c in os.environ.get(
    'WATCH_CONTAINERS', 'uptime-kuma,beszel,homeassistant').split(',') if c.strip()]
JOURNAL_PRIORITY = os.environ.get('JOURNAL_PRIORITY', '4')
BATCH_MAX = int(os.environ.get('BATCH_MAX', '100'))
BATCH_SECONDS = float(os.environ.get('BATCH_SECONDS', '3'))

ic = IngestClient.from_env(host=HOST_NAME)
shutdown = Shutdown()


def post_log(level: str, message: str, data: dict[str, Any] | None = None) -> None:
    ic.post_log(level, message, data)


def send_metric(metric: dict[str, Any]) -> None:
    ic.post_metrics(metric)


def level_from_priority(prio: str) -> str:
    try:
        p = int(prio)
    except (TypeError, ValueError):
        return 'info'
    if p <= 2:
        return 'fatal'
    if p == 3:
        return 'error'
    if p == 4:
        return 'warn'
    return 'info'


def make_event(source: str, level: str, message: str,
               data: dict[str, Any] | None = None, ts: str | None = None) -> dict[str, Any]:
    e: dict[str, Any] = {'host': HOST_NAME, 'source': source, 'level': level, 'message': message[:8000]}
    if data:
        e['data'] = data
    if ts:
        e['ts'] = ts
    return e


def follow_docker_container(name: str, out: queue.Queue[dict[str, Any]]) -> None:
    """Tail one container's stdout/stderr. Restarts on crash / container churn."""
    while not shutdown.is_set():
        cmd = ['docker', 'logs', '-f', '--since', '1s', '--tail', '0', name]
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        except FileNotFoundError:
            print('docker not found, sleeping then retrying', file=sys.stderr)
            time.sleep(30)
            continue
        assert p.stdout is not None
        for line in p.stdout:
            line = line.rstrip()
            if not line:
                continue
            lower = line.lower()
            if any(k in lower for k in ('error', 'fatal', 'panic')):
                lvl = 'error'
            elif 'warn' in lower:
                lvl = 'warn'
            else:
                lvl = 'info'
            out.put(make_event(f'docker:{name}', lvl, line))
        p.wait()
        time.sleep(3)


def follow_journald_errors(out: queue.Queue[dict[str, Any]]) -> None:
    """Tail journald across ALL units at warning-or-worse ("syslog errors")."""
    while not shutdown.is_set():
        cmd = ['journalctl', '-f', '-o', 'json', '-n', '0', '-p', JOURNAL_PRIORITY]
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        except FileNotFoundError:
            print('journalctl not found, sleeping then retrying', file=sys.stderr)
            time.sleep(30)
            continue
        assert p.stdout is not None
        for line in p.stdout:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get('MESSAGE') or ''
            if isinstance(msg, list):
                msg = ' '.join(str(x) for x in msg)
            unit = rec.get('_SYSTEMD_UNIT') or rec.get('SYSLOG_IDENTIFIER') or 'syslog'
            ts_micro = rec.get('__REALTIME_TIMESTAMP')
            ts_iso = None
            if ts_micro:
                try:
                    ts_iso = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(int(ts_micro) / 1_000_000)) + 'Z'
                except ValueError:
                    pass
            data = {k.lstrip('_').lower(): v for k, v in rec.items() if k in {
                'PRIORITY', 'SYSLOG_IDENTIFIER', '_PID', '_COMM', '_SYSTEMD_UNIT',
            }}
            out.put(make_event(
                f'journald:{unit}',
                level_from_priority(rec.get('PRIORITY', '6')),
                str(msg), data, ts_iso,
            ))
        p.wait()
        time.sleep(3)


def shipper(q: queue.Queue[dict[str, Any]]) -> None:
    """Batch events off the queue and POST. Soft-drains (5s cap) on shutdown."""
    buf: list[dict[str, Any]] = []
    last_flush = time.monotonic()
    while not shutdown.is_set():
        timeout = max(0.05, BATCH_SECONDS - (time.monotonic() - last_flush))
        try:
            buf.append(q.get(timeout=timeout))
        except queue.Empty:
            pass
        if buf and (len(buf) >= BATCH_MAX or time.monotonic() - last_flush >= BATCH_SECONDS):
            ic.post_events(buf)
            buf = []
            last_flush = time.monotonic()
    drain_deadline = time.monotonic() + 5.0
    while time.monotonic() < drain_deadline and len(buf) < BATCH_MAX:
        try:
            buf.append(q.get_nowait())
        except queue.Empty:
            break
    if buf:
        ic.post_events(buf)
    print(f'rpi-watcher: drained {len(buf)} events, exiting', file=sys.stderr)


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

    while not shutdown.wait(METRIC_INTERVAL):
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
    shutdown.install()
    q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=10_000)
    for name in WATCH_CONTAINERS:
        threading.Thread(target=follow_docker_container, args=(name, q), daemon=True).start()
    threading.Thread(target=follow_journald_errors, args=(q,), daemon=True).start()
    ship = threading.Thread(target=shipper, args=(q,))
    ship.start()
    post_log('info', (
        f'rpi-watcher up: interval={METRIC_INTERVAL}s temp_path={TEMP_PATH} '
        f'containers={",".join(WATCH_CONTAINERS)} journal_p={JOURNAL_PRIORITY}'
    ))
    metric_sampler_loop()
    ship.join(timeout=8)
    post_log('info', 'rpi-watcher down (signal)')


if __name__ == '__main__':
    main()
