#!/usr/bin/env python3
"""elitedesk-watcher — tails journald units + named Docker container logs and
posts structured events to the home-ops ingest API.

Runs as a systemd --user service. Configurable via env:
  INGEST_URL       (required) e.g. http://192.168.1.75:64421/api/ingest
  INGEST_TOKEN     (required) shared secret
  HOST_NAME        defaults to 'elitedesk'
  WATCH_UNITS      comma-separated systemd units; default cloudflared,docker,ssh
  WATCH_CONTAINERS comma-separated docker container names; default supabase_db_stano,supabase_kong_stano,supabase_db_StudentManager
  BATCH_SECONDS    flush window; default 2
  BATCH_MAX        max events per POST; default 100
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))
sys.path.insert(0, str(_here.parent))
from _common import IngestClient, Shutdown  # noqa: E402

HOST_NAME = os.environ.get('HOST_NAME', 'elitedesk')
WATCH_UNITS = [u.strip() for u in os.environ.get('WATCH_UNITS', 'cloudflared,docker,ssh').split(',') if u.strip()]
WATCH_CONTAINERS = [c.strip() for c in os.environ.get(
    'WATCH_CONTAINERS',
    'supabase_db_stano,supabase_kong_stano,supabase_db_StudentManager',
).split(',') if c.strip()]
BATCH_SECONDS = float(os.environ.get('BATCH_SECONDS', '2'))
BATCH_MAX = int(os.environ.get('BATCH_MAX', '100'))

# Metric sampling (host_metrics — third pillar; see docs/CONTEXT.md).
# Disabled at the source if psutil isn't installed; falling back to log-only is fine.
METRICS_ENABLED = os.environ.get('METRICS_ENABLED', '1') not in ('0', 'false', 'no', '')
METRIC_INTERVAL = float(os.environ.get('METRIC_INTERVAL', '30'))
METRIC_DISK_PATH = os.environ.get('METRIC_DISK_PATH', '/')
METRIC_TOP_N = int(os.environ.get('METRIC_TOP_N', '10'))

ic = IngestClient.from_env(host=HOST_NAME)
shutdown = Shutdown()


def level_from_priority(prio: str) -> str:
    try:
        p = int(prio)
    except (TypeError, ValueError):
        return 'info'
    if p <= 2:
        return 'fatal' if p <= 1 else 'error'
    if p == 3:
        return 'error'
    if p == 4:
        return 'warn'
    return 'info'


def make_event(host: str, source: str, level: str, message: str, data: dict[str, Any] | None = None, ts: str | None = None) -> dict[str, Any]:
    e: dict[str, Any] = {'host': host, 'source': source, 'level': level, 'message': message[:8000]}
    if data: e['data'] = data
    if ts: e['ts'] = ts
    return e


# ── journald follower ─────────────────────────────────────────────────

def follow_journald(unit: str, out: queue.Queue[dict[str, Any]]) -> None:
    """Tail a single systemd unit as JSON. Restarts on crash."""
    while True:
        cmd = ['journalctl', '-f', '-o', 'json', '-n', '0', '--unit', unit]
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        except FileNotFoundError:
            print(f'journalctl not found, sleeping then retrying', file=sys.stderr)
            time.sleep(30); continue
        assert p.stdout is not None
        for line in p.stdout:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get('MESSAGE') or ''
            if isinstance(msg, list):
                msg = ' '.join(str(x) for x in msg)
            ts_micro = rec.get('__REALTIME_TIMESTAMP')
            ts_iso = None
            if ts_micro:
                try:
                    ts_iso = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(int(ts_micro) / 1_000_000)) + 'Z'
                except ValueError:
                    pass
            data = {k.lower(): v for k, v in rec.items() if k in {
                'PRIORITY','SYSLOG_IDENTIFIER','SYSLOG_FACILITY','_PID','_COMM','_EXE','_CMDLINE','_HOSTNAME','UNIT','_SYSTEMD_UNIT'
            }}
            out.put(make_event(
                HOST_NAME,
                f'journald:{unit}',
                level_from_priority(rec.get('PRIORITY', '6')),
                str(msg),
                data,
                ts_iso,
            ))
        p.wait()
        time.sleep(3)


# ── docker container follower ─────────────────────────────────────────

def follow_docker_container(name: str, out: queue.Queue[dict[str, Any]]) -> None:
    while True:
        cmd = ['docker', 'logs', '-f', '--since', '1s', '--tail', '0', name]
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        except FileNotFoundError:
            print('docker not found, sleeping then retrying', file=sys.stderr)
            time.sleep(30); continue
        assert p.stdout is not None
        for line in p.stdout:
            line = line.rstrip()
            if not line: continue
            lower = line.lower()
            if any(k in lower for k in ('error', 'fatal', 'panic')):
                lvl = 'error'
            elif 'warn' in lower:
                lvl = 'warn'
            else:
                lvl = 'info'
            out.put(make_event(HOST_NAME, f'docker:{name}', lvl, line))
        p.wait()
        time.sleep(3)


# ── shipper ───────────────────────────────────────────────────────────

def shipper(q: queue.Queue[dict[str, Any]]) -> None:
    buf: list[dict[str, Any]] = []
    last_flush = time.monotonic()
    while not shutdown.is_set():
        timeout = max(0.05, BATCH_SECONDS - (time.monotonic() - last_flush))
        try:
            ev = q.get(timeout=timeout)
            buf.append(ev)
        except queue.Empty:
            pass
        if buf and (len(buf) >= BATCH_MAX or time.monotonic() - last_flush >= BATCH_SECONDS):
            send(buf)
            buf = []
            last_flush = time.monotonic()
    # Soft-drain on shutdown: pull whatever's left in the queue (with a cap)
    # and ship as one final batch. 5s budget so a flood doesn't block exit.
    drain_deadline = time.monotonic() + 5.0
    while time.monotonic() < drain_deadline and len(buf) < BATCH_MAX:
        try:
            buf.append(q.get_nowait())
        except queue.Empty:
            break
    if buf:
        send(buf)
    print(f'elitedesk-watcher: drained {len(buf)} events, exiting', file=sys.stderr)


def send(events: list[dict[str, Any]]) -> None:
    ic.post_events(events)


# ── metric sampler ────────────────────────────────────────────────────
#
# Periodically samples host CPU/mem/disk/net + per-process attribution via
# psutil, POSTs to /api/metrics. See docs/adr/2026-06-07-no-grafana.md
# for the design rationale.
#
# Requires `psutil` on the host. Install via `apt install python3-psutil`
# (Ubuntu / Debian) or `pip install psutil`. If unavailable, this loop
# logs an error once and exits — log shipping continues unaffected.

def send_metric(metric: dict[str, Any]) -> None:
    ic.post_metrics(metric)


def metric_sampler_loop() -> None:
    try:
        import psutil  # type: ignore
    except ImportError:
        print('psutil not installed; metric sampling disabled. apt install python3-psutil', file=sys.stderr)
        return

    # Prime cpu_percent so the first non-blocking call has a baseline.
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
            net_rx_kbps = (net.bytes_recv - last_net.bytes_recv) / elapsed / 1024
            net_tx_kbps = (net.bytes_sent - last_net.bytes_sent) / elapsed / 1024
            last_net, last_net_ts = net, now

            # Per-process attribution. Top N by CPU% and top N by RSS.
            procs_cpu: list[dict[str, Any]] = []
            procs_mem: list[dict[str, Any]] = []
            for p in psutil.process_iter(['name', 'pid', 'cpu_percent', 'memory_info']):
                try:
                    info = p.info
                    name = info.get('name') or '?'
                    pid = info.get('pid')
                    cpu = info.get('cpu_percent') or 0.0
                    rss = info.get('memory_info').rss if info.get('memory_info') else 0
                    if cpu > 0:
                        procs_cpu.append({'name': name, 'pid': pid, 'pct': round(cpu, 1)})
                    if rss > 0:
                        procs_mem.append({'name': name, 'pid': pid, 'rss_mb': rss // (1024 * 1024)})
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            top_cpu = sorted(procs_cpu, key=lambda x: x['pct'], reverse=True)[:METRIC_TOP_N]
            top_mem = sorted(procs_mem, key=lambda x: x['rss_mb'], reverse=True)[:METRIC_TOP_N]

            metric = {
                'host': HOST_NAME,
                'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'cpu_pct': round(cpu_pct, 1),
                'cpu_load_1': round(load_1, 2),
                'mem_pct': round(mem.percent, 1),
                'mem_used_mb': mem.used // (1024 * 1024),
                'mem_total_mb': mem.total // (1024 * 1024),
                'swap_pct': round(swap.percent, 1),
                'disk_pct': round(disk.percent, 1),
                'net_rx_kbps': round(net_rx_kbps, 1),
                'net_tx_kbps': round(net_tx_kbps, 1),
                'data': {
                    'top_cpu': top_cpu,
                    'top_mem': top_mem,
                },
            }
            send_metric(metric)
        except (psutil.Error, OSError, AttributeError, KeyError, ValueError) as e:
            # Narrowed from `except Exception` — these are the realistic
            # failure modes of a psutil sample tick. AttributeError/KeyError
            # cover defensive paths when process_iter returns unexpected
            # shapes (procs racing exit during enumeration).
            print(f'metric sample failed ({type(e).__name__}): {e}', file=sys.stderr)


def main() -> None:
    shutdown.install()
    q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=10_000)
    threads: list[threading.Thread] = []
    for unit in WATCH_UNITS:
        t = threading.Thread(target=follow_journald, args=(unit, q), daemon=True, name=f'journald:{unit}')
        t.start(); threads.append(t)
    for name in WATCH_CONTAINERS:
        t = threading.Thread(target=follow_docker_container, args=(name, q), daemon=True, name=f'docker:{name}')
        t.start(); threads.append(t)
    if METRICS_ENABLED:
        t = threading.Thread(target=metric_sampler_loop, daemon=True, name='metrics')
        t.start(); threads.append(t)
    ic.post_log('info', f'elitedesk-watcher up: {len(WATCH_UNITS)} units, {len(WATCH_CONTAINERS)} containers, metrics={METRICS_ENABLED}')
    shipper(q)
    ic.post_log('info', 'elitedesk-watcher down')


if __name__ == '__main__':
    main()
