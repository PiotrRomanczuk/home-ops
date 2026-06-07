#!/usr/bin/env python3
"""uwh-watcher — tails journald units + named Docker container logs and
posts structured events to the home-ops ingest API.

Runs as a systemd --user service. Configurable via env:
  INGEST_URL       (required) e.g. http://192.168.1.75:64421/api/ingest
  INGEST_TOKEN     (required) shared secret
  HOST_NAME        defaults to 'uwh'
  WATCH_UNITS      comma-separated systemd units; default cloudflared,docker,ssh
  WATCH_CONTAINERS comma-separated docker container names; default supabase_db_stano,supabase_kong_stano,supabase_db_StudentManager
  BATCH_SECONDS    flush window; default 2
  BATCH_MAX        max events per POST; default 100
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from typing import Any

import urllib.request
import urllib.error


INGEST_URL = os.environ.get('INGEST_URL', '')
INGEST_TOKEN = os.environ.get('INGEST_TOKEN', '')
HOST_NAME = os.environ.get('HOST_NAME', 'uwh')
WATCH_UNITS = [u.strip() for u in os.environ.get('WATCH_UNITS', 'cloudflared,docker,ssh').split(',') if u.strip()]
WATCH_CONTAINERS = [c.strip() for c in os.environ.get(
    'WATCH_CONTAINERS',
    'supabase_db_stano,supabase_kong_stano,supabase_db_StudentManager',
).split(',') if c.strip()]
BATCH_SECONDS = float(os.environ.get('BATCH_SECONDS', '2'))
BATCH_MAX = int(os.environ.get('BATCH_MAX', '100'))


if not INGEST_URL or not INGEST_TOKEN:
    print('INGEST_URL and INGEST_TOKEN required', file=sys.stderr)
    sys.exit(1)


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
    while True:
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


def send(events: list[dict[str, Any]]) -> None:
    body = json.dumps({'events': events}).encode()
    req = urllib.request.Request(
        INGEST_URL,
        data=body,
        method='POST',
        headers={'Content-Type': 'application/json', 'X-Ingest-Token': INGEST_TOKEN},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                if 200 <= r.status < 300:
                    return
                print(f'ingest non-2xx: {r.status}', file=sys.stderr)
        except urllib.error.URLError as e:
            print(f'ingest attempt {attempt + 1} failed: {e}', file=sys.stderr)
        time.sleep(1 + attempt)
    print(f'dropped {len(events)} events after 3 retries', file=sys.stderr)


def main() -> None:
    q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=10_000)
    threads: list[threading.Thread] = []
    for unit in WATCH_UNITS:
        t = threading.Thread(target=follow_journald, args=(unit, q), daemon=True, name=f'journald:{unit}')
        t.start(); threads.append(t)
    for name in WATCH_CONTAINERS:
        t = threading.Thread(target=follow_docker_container, args=(name, q), daemon=True, name=f'docker:{name}')
        t.start(); threads.append(t)
    print(f'uwh-watcher up: {len(WATCH_UNITS)} units, {len(WATCH_CONTAINERS)} containers', flush=True)
    shipper(q)


if __name__ == '__main__':
    main()
