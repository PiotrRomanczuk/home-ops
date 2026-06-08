#!/usr/bin/env python3
"""win10-watcher — host metrics + GPU + Ollama state for the Windows GPU box.

Sibling of elitedesk-watcher (no journald / docker tailing on Windows). The
ollama log tail is a separate process (ollama-watcher.py). This one is
the win10 equivalent of elitedesk-watcher's metric_sampler_loop.

Env:
  INGEST_URL       (required) e.g. http://192.168.1.75:64421/api/ingest
  INGEST_TOKEN     (required) shared secret
  HOST_NAME        defaults to 'win10'
  METRIC_INTERVAL  seconds between samples (default 30)
  METRIC_DISK_PATH default 'C:\\'
  METRIC_TOP_N     top-N processes (default 10)
  GPU_PS1_PATH     path to sample-gpu.ps1 (default: same dir as this script)
  OLLAMA_URL       default http://localhost:11434
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

INGEST_URL = os.environ.get('INGEST_URL', '')
INGEST_TOKEN = os.environ.get('INGEST_TOKEN', '')
HOST_NAME = os.environ.get('HOST_NAME', 'win10')
METRIC_INTERVAL = float(os.environ.get('METRIC_INTERVAL', '30'))
METRIC_URL = os.environ.get('METRIC_URL') or INGEST_URL.replace('/api/ingest', '/api/metrics')
METRIC_DISK_PATH = os.environ.get('METRIC_DISK_PATH', 'C:\\')
METRIC_TOP_N = int(os.environ.get('METRIC_TOP_N', '10'))
GPU_PS1_PATH = Path(os.environ.get('GPU_PS1_PATH') or Path(__file__).resolve().parent / 'sample-gpu.ps1')
OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434').rstrip('/')

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
    """Self-emit a lifecycle / error event. Best-effort; failures only to stderr."""
    ev: dict[str, Any] = {'host': HOST_NAME, 'source': SELF_SOURCE, 'level': level, 'message': message[:8000]}
    if data:
        ev['data'] = data
    if not _post(INGEST_URL, {'events': [ev]}):
        print(f'self-log failed: {message}', file=sys.stderr)


def send_metric(metric: dict[str, Any]) -> None:
    if not _post(METRIC_URL, metric):
        print('metric POST failed', file=sys.stderr)


def sample_gpu() -> dict[str, Any]:
    """Shell out to sample-gpu.ps1 once. Returns parsed JSON or {} on error."""
    try:
        r = subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(GPU_PS1_PATH)],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if r.returncode != 0:
            post_log('warn', 'sample-gpu.ps1 non-zero exit', {'rc': r.returncode, 'stderr': r.stderr[:500]})
            return {}
        return json.loads(r.stdout.strip())
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        post_log('warn', f'sample_gpu failed: {type(e).__name__}', {'err': str(e)[:500]})
        return {}


def sample_ollama() -> dict[str, Any]:
    """GET /api/ps — currently loaded models. {} on failure."""
    try:
        with urllib.request.urlopen(f'{OLLAMA_URL}/api/ps', timeout=3) as r:
            payload = json.loads(r.read())
        loaded = [
            {'name': m.get('name'), 'size_vram_mb': (m.get('size_vram') or 0) // (1024 * 1024)}
            for m in payload.get('models', [])
        ]
        return {'loaded': loaded, 'count': len(loaded)}
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return {}


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

            gpu = sample_gpu()
            ollama = sample_ollama()

            metric: dict[str, Any] = {
                'host': HOST_NAME,
                'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'cpu_pct': round(psutil.cpu_percent(interval=None), 1),
                'mem_pct': round(mem.percent, 1),
                'mem_used_mb': mem.used // (1024 * 1024),
                'mem_total_mb': mem.total // (1024 * 1024),
                'swap_pct': round(swap.percent, 1),
                'disk_pct': round(disk.percent, 1),
                'net_rx_kbps': round(net_rx, 1),
                'net_tx_kbps': round(net_tx, 1),
                'data': {'top_cpu': top_cpu, 'top_mem': top_mem, 'gpu_top_mem': gpu.get('top_gpu_mem', []), 'ollama': ollama},
            }
            if gpu:
                metric['gpu_pct'] = gpu.get('gpu_pct')
                metric['gpu_mem_pct'] = gpu.get('vram_pct')
            send_metric(metric)
        except (psutil.Error, OSError) as e:
            print(f'metric sample failed: {e}', file=sys.stderr)


def main() -> None:
    post_log('info', f'win10-watcher up: interval={METRIC_INTERVAL}s gpu_ps1={GPU_PS1_PATH.name} ollama={OLLAMA_URL}')
    try:
        metric_sampler_loop()
    except KeyboardInterrupt:
        post_log('info', 'win10-watcher shutting down (SIGINT)')


if __name__ == '__main__':
    main()
