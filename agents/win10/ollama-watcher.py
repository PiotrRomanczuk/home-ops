#!/usr/bin/env python3
"""ollama-watcher — tails Ollama WinSW log files on Windows and ships
parsed structured events to the home-ops ingest API.

Env:
  INGEST_URL       (required) e.g. http://192.168.1.75:64421/api/ingest
  INGEST_TOKEN     (required) shared secret
  HOST_NAME        defaults to 'win10'
  OLLAMA_LOG       path to Ollama.err.log (default: C:\\ProgramData\\Ollama-Service\\Ollama.err.log)
  BATCH_SECONDS    flush window; default 2
  BATCH_MAX        max events per POST; default 100
"""
from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


INGEST_URL = os.environ.get('INGEST_URL', '')
INGEST_TOKEN = os.environ.get('INGEST_TOKEN', '')
HOST_NAME = os.environ.get('HOST_NAME', 'win10')
LOG_PATH = Path(os.environ.get('OLLAMA_LOG', r'C:\ProgramData\Ollama-Service\Ollama.err.log'))
BATCH_SECONDS = float(os.environ.get('BATCH_SECONDS', '2'))
BATCH_MAX = int(os.environ.get('BATCH_MAX', '100'))


if not INGEST_URL or not INGEST_TOKEN:
    print('INGEST_URL and INGEST_TOKEN required', file=sys.stderr)
    sys.exit(1)


# ── parsing ───────────────────────────────────────────────────────────

GIN_RE = re.compile(
    r'^\[GIN\]\s+(?P<ts>\d{4}/\d{2}/\d{2}\s+-\s+\d{2}:\d{2}:\d{2})\s+\|'
    r'\s+(?P<status>\d+)\s+\|'
    r'\s+(?P<dur>\S+)\s+\|'
    r'\s+(?P<peer>\S+)\s+\|'
    r'\s+(?P<method>\S+)\s+(?P<path>\S+)\s*$'
)

# slog-style: time=… level=… source=… msg="…" key=value key="quoted value"
KV_RE = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S+)')


def parse_status_level(status: int) -> str:
    if status >= 500:
        return 'error'
    if status >= 400:
        return 'warn'
    return 'info'


def parse_slog_level(raw: str) -> str:
    r = raw.upper()
    if r in ('ERROR', 'ERR', 'FATAL'):
        return 'error'
    if r in ('WARN', 'WARNING'):
        return 'warn'
    if r == 'DEBUG':
        return 'debug'
    return 'info'


def parse_line(line: str) -> dict[str, Any] | None:
    s = line.strip()
    if not s:
        return None

    m = GIN_RE.match(s)
    if m:
        try:
            status = int(m.group('status'))
        except ValueError:
            status = 0
        return {
            'source': 'ollama',
            'level': parse_status_level(status),
            'message': f"{m.group('method')} {m.group('path')}",
            'data': {
                'status': status,
                'duration': m.group('dur'),
                'peer': m.group('peer'),
            },
        }

    if s.startswith('time=') and 'level=' in s:
        kv = {k: v[1:-1] if v.startswith('"') and v.endswith('"') else v
              for k, v in KV_RE.findall(s)}
        level = parse_slog_level(kv.pop('level', 'INFO'))
        kv.pop('time', None)
        msg = kv.pop('msg', s[:200])
        return {
            'source': 'ollama',
            'level': level,
            'message': msg,
            'data': kv,
        }

    return {
        'source': 'ollama-raw',
        'level': 'info',
        'message': s[:8000],
    }


# ── tailer (handles WinSW rotation: shrink/replace) ───────────────────

def tail(path: Path, out: queue.Queue[dict[str, Any]]) -> None:
    pos = 0
    last_inode = None
    while True:
        try:
            st = path.stat()
        except FileNotFoundError:
            time.sleep(1)
            continue
        # st.st_ino is 0 on most Windows volumes; fall back to (size, mtime)
        rotation = False
        if st.st_size < pos:
            rotation = True
        elif last_inode is not None and st.st_ino and st.st_ino != last_inode:
            rotation = True
        if rotation:
            pos = 0
        last_inode = st.st_ino

        if st.st_size > pos:
            try:
                with path.open('r', encoding='utf-8', errors='replace') as f:
                    f.seek(pos)
                    for line in f:
                        ev = parse_line(line)
                        if ev:
                            ev['host'] = HOST_NAME
                            out.put(ev)
                    pos = f.tell()
            except OSError as e:
                print(f'read error: {e}', file=sys.stderr)
                time.sleep(1)
        time.sleep(0.5)


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


# ── main ──────────────────────────────────────────────────────────────

def main() -> None:
    print(f'ollama-watcher up: tailing {LOG_PATH} -> {INGEST_URL}', flush=True)
    q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=10_000)
    t = threading.Thread(target=tail, args=(LOG_PATH, q), daemon=True, name='tail')
    t.start()
    shipper(q)


if __name__ == '__main__':
    main()
