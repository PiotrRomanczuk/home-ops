#!/usr/bin/env python3
"""activity-watcher — what elitedesk is doing: systemd --user unit runs (with
their log lines), GitHub Actions jobs on the self-hosted runners, and a
"right now" snapshot. Posts to /api/activity/{runs,now} (migration 026); the
console's Serwer tab and the Dziś card read them.

Runs as a systemd --user service. Env (shares ~/.config/elitedesk-watcher.env):
  INGEST_URL / INGEST_TOKEN  required; the API base is derived from INGEST_URL
  HOST_NAME          default elitedesk
  ACTIVITY_INTERVAL  seconds between journal reads + snapshots; default 30
  GHA_INTERVAL       seconds between GitHub polls; default 120
  RUNNER_ROOT        default ~/actions-runner
  STATE_DIR          journal cursor lives here; default ~/.local/state/home-ops
  BACKFILL           journalctl --since for the very first start; default -7d
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))
sys.path.insert(0, str(_here.parent))
from _common import IngestClient, Shutdown  # noqa: E402
from activity_gha import GhaPoller, discover_runners  # noqa: E402
from activity_journal import RunTracker  # noqa: E402
from activity_now import CpuSampler, next_timers  # noqa: E402
from activity_units import UnitCatalog  # noqa: E402

HOST_NAME = os.environ.get('HOST_NAME', 'elitedesk')
ACTIVITY_INTERVAL = float(os.environ.get('ACTIVITY_INTERVAL', '30'))
GHA_INTERVAL = float(os.environ.get('GHA_INTERVAL', '120'))
RUNNER_ROOT = Path(os.environ.get('RUNNER_ROOT', os.path.expanduser('~/actions-runner')))
STATE_DIR = Path(os.environ.get('STATE_DIR', os.path.expanduser('~/.local/state/home-ops')))
BACKFILL = os.environ.get('BACKFILL', '-7d')
CURSOR_FILE = STATE_DIR / 'activity.cursor'
CHUNK = 500

ic = IngestClient.from_env(host=HOST_NAME, source='agent:activity-watcher')
API = ic.events_url.rsplit('/api/', 1)[0] + '/api/activity'
shutdown = Shutdown()


def flush(pending: dict[str, dict[str, Any]]) -> bool:
    """POST pending runs; what fails stays pending for the next tick."""
    items = list(pending.values())
    for i in range(0, len(items), CHUNK):
        status, _ = ic.request(f'{API}/runs', {'host': HOST_NAME, 'runs': items[i:i + CHUNK]}, timeout=30)
        if not 200 <= status < 300:
            print(f'runs POST failed: HTTP {status}', file=sys.stderr)
            return False
        for r in items[i:i + CHUNK]:
            pending.pop(r['invocation_id'], None)
    return True


def pump_journal(tracker: RunTracker, cursor: str | None, pending: dict[str, dict[str, Any]]) -> str | None:
    """Feed every journal record since `cursor` to the tracker. Big reads (the
    first-start backfill) drain and flush as they go to bound memory."""
    since = [f'--after-cursor={cursor}'] if cursor else [f'--since={BACKFILL}']
    proc = subprocess.Popen(['journalctl', '--user', '-o', 'json', '--no-pager', *since],
                            stdout=subprocess.PIPE, text=True, errors='replace')
    assert proc.stdout is not None
    for n, line in enumerate(proc.stdout, 1):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        tracker.feed(rec)
        cursor = rec.get('__CURSOR') or cursor
        if n % 5000 == 0:
            pending.update((r['invocation_id'], r) for r in tracker.drain())
            flush(pending)
    proc.wait()
    pending.update((r['invocation_id'], r) for r in tracker.drain())
    return cursor


def snapshot(tracker: RunTracker, gha: GhaPoller, sampler: CpuSampler, catalog: UnitCatalog) -> dict[str, Any]:
    runners = discover_runners(RUNNER_ROOT)
    snap = sampler.sample([r['dir'] for r in runners])
    busy = set(snap.pop('busy_runner_dirs'))
    for o in snap['owners']:
        o['project'] = catalog.project(o['owner'] + '.service')
    snap['running'] = [r for r in tracker.running() if catalog.is_oneshot(r['unit'])]
    snap['gha_running'] = gha.active
    snap['runners'] = [{'name': r['name'], 'repo': r['repo'], 'busy': r['dir'] in busy} for r in runners]
    snap['next_timers'] = [{**t, 'project': catalog.project(t['unit'] or '')} for t in next_timers()]
    snap['taken_at'] = time.time()
    return snap


def main() -> None:
    import psutil  # type: ignore  # python3-psutil, already used by elitedesk-watcher

    shutdown.install()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    catalog = UnitCatalog()
    catalog.refresh()
    tracker, gha, sampler = RunTracker(catalog), GhaPoller(RUNNER_ROOT), CpuSampler(psutil)
    cursor = CURSOR_FILE.read_text().strip() if CURSOR_FILE.exists() else None
    pending: dict[str, dict[str, Any]] = {}
    last_gha = last_catalog = 0.0
    ic.post_log('info', f'activity-watcher up: {len(catalog.services)} units, cursor={"yes" if cursor else "backfill " + BACKFILL}')
    while True:
        now = time.monotonic()
        if now - last_catalog > 600:
            catalog.refresh()
            last_catalog = now
        cursor = pump_journal(tracker, cursor, pending)
        if now - last_gha >= GHA_INTERVAL:
            pending.update((r['invocation_id'], r) for r in gha.poll())
            last_gha = now
        if flush(pending) and cursor:
            CURSOR_FILE.write_text(cursor)
        status, _ = ic.request(f'{API}/now', {'host': HOST_NAME, 'snapshot': snapshot(tracker, gha, sampler, catalog)})
        if not 200 <= status < 300:
            print(f'snapshot POST failed: HTTP {status}', file=sys.stderr)
        if shutdown.wait(ACTIVITY_INTERVAL):
            break
    ic.post_log('info', 'activity-watcher down')


if __name__ == '__main__':
    main()
