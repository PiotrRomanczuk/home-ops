"""activity_journal — `journalctl --user -o json` records in, unit runs out.

Runs are keyed by INVOCATION_ID. Output joins its run by invocation, then by
_STREAM_ID; a line whose process died before journald read its unit goes to
the one oneshot (or <10 s old service) running then, or nowhere if two overlap (no log beats a wrong
log). A unit failing again within LOOP_WINDOW_S folds into its first failed
run's repeat_count, so a crash loop is one row.
"""
from __future__ import annotations

import re
from collections import deque
from datetime import datetime, timezone
from typing import Any

MSG_STARTING = '7d4958e842da4a758f6c1cdc7b36dcc5'
MSG_STARTED = '39f53479d3a045ac8e11786248231fbf'      # "Started" (simple) / "Finished" (oneshot)
MSG_JOB_FAILED = 'be02cf6855d2428ba40df7e9d022f03d'   # "Failed to start"
MSG_EXITED = '98e322203f7a4ed290d09fe03c09fe15'       # "Main process exited" (EXIT_STATUS)
MSG_UNIT_FAILED = 'd9b373ed55a64feb8242e02dbe79a49c'  # "Failed with result" (UNIT_RESULT)
MSG_DEACTIVATED = '7ad2d189f7e94e70a38c781354912448'
MSG_RESOURCES = 'ae8f7b866b0347b9af31fe1c80b127c0'   # "Consumed" (CPU_USAGE_NSEC, MEMORY_PEAK)
LOOP_WINDOW_S, GRACE_S, ORPHAN_SLACK_S, YOUNG_S, STALE_OPEN_S, TAIL = 600, 120, 2, 10, 86400, 30
_ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
PUBLIC = ('kind', 'unit', 'invocation_id', 'project_slug', 'result', 'exit_code', 'cpu_ms', 'mem_peak_mb', 'repeat_count', 'detail')


def rec_time(rec: dict[str, Any]) -> float:
    return int(rec.get('__REALTIME_TIMESTAMP') or 0) / 1e6


def iso(t: float | None) -> str | None:
    return datetime.fromtimestamp(t, timezone.utc).isoformat() if t else None


class RunTracker:
    def __init__(self, catalog: Any) -> None:
        self.catalog = catalog
        self.runs: dict[str, dict[str, Any]] = {}    # invocation → run (open, or ended < GRACE_S ago)
        self.streams: dict[str, str] = {}            # _STREAM_ID → invocation
        self.loops: dict[str, dict[str, Any]] = {}   # unit → first failed run of its crash loop
        self.dirty: dict[str, dict[str, Any]] = {}
        self.last_t = 0.0

    def feed(self, rec: dict[str, Any]) -> None:
        self.last_t = max(self.last_t, rec_time(rec))
        if rec.get('SYSLOG_IDENTIFIER') == 'systemd' and rec.get('USER_UNIT'):
            self._lifecycle(rec)
        elif isinstance(rec.get('MESSAGE'), str):
            self._output(rec)

    def running(self) -> list[dict[str, Any]]:
        return [self._public(r) for r in self.runs.values() if r['result'] == 'running' and '_into' not in r]

    def _lifecycle(self, rec: dict[str, Any]) -> None:
        unit, inv, mid, t = rec['USER_UNIT'], rec.get('USER_INVOCATION_ID'), rec.get('MESSAGE_ID'), rec_time(rec)
        if not inv or not self.catalog.tracked(unit):
            return
        run = self.runs.get(inv)
        if run is None:
            if mid not in (MSG_STARTING, MSG_STARTED):
                return  # the tail of a run we never saw start
            run = self.runs[inv] = {
                'kind': self.catalog.kind(unit), 'unit': unit, 'invocation_id': inv,
                'project_slug': self.catalog.project(unit), 'result': 'running', 'exit_code': None,
                'cpu_ms': None, 'mem_peak_mb': None, 'repeat_count': 1, 'detail': None,
                '_start': t, '_end': None, '_tail': deque(maxlen=TAIL), '_oneshot': self.catalog.is_oneshot(unit),
            }
        tgt = run.get('_into', run)
        if mid == MSG_STARTED and run['_oneshot'] or mid == MSG_DEACTIVATED:
            self._finish(run, t, failed=rec.get('JOB_RESULT') == 'failed')
        elif mid in (MSG_JOB_FAILED, MSG_UNIT_FAILED):
            run['detail'] = rec.get('UNIT_RESULT') or run['detail'] or 'failed'
            self._finish(run, t, failed=True)
        elif mid == MSG_EXITED and str(rec.get('EXIT_STATUS', '')).isdigit():
            tgt['exit_code'] = int(rec['EXIT_STATUS'])
        elif mid == MSG_RESOURCES:
            cpu = int(rec.get('CPU_USAGE_NSEC') or 0) // 1_000_000
            tgt['cpu_ms'] = (tgt['cpu_ms'] or 0) + cpu if tgt is not run else cpu
            mem = int(rec.get('MEMORY_PEAK') or 0) // (1024 * 1024)
            tgt['mem_peak_mb'] = max(tgt['mem_peak_mb'] or 0, mem) or None
            self._finish(run, t, failed=run['result'] == 'failed')
        self._touch(run.get('_into', run))

    def _finish(self, run: dict[str, Any], t: float, failed: bool) -> None:
        first = run['_end'] is None
        run['_end'] = max(run['_end'] or t, t)
        run['result'] = 'failed' if failed or run['result'] == 'failed' else 'ok'
        if first:
            self._chain(run)

    def _chain(self, run: dict[str, Any]) -> None:
        unit, head = run['unit'], self.loops.get(run['unit'])
        if run['result'] != 'failed':
            self.loops.pop(unit, None)
        elif head is None or run['_start'] - head['_end'] > LOOP_WINDOW_S:
            self.loops[unit] = run
        else:
            head['repeat_count'] += 1
            head['_end'] = run['_end']
            head['exit_code'] = run['exit_code'] if run['exit_code'] is not None else head['exit_code']
            head['_tail'].extend(run['_tail'])
            run['_into'] = head
            self.dirty.pop(run['invocation_id'], None)

    def _touch(self, run: dict[str, Any]) -> None:
        if '_into' not in run:
            self.dirty[run['invocation_id']] = run

    def _output(self, rec: dict[str, Any]) -> None:
        inv, stream, t = rec.get('_SYSTEMD_INVOCATION_ID'), rec.get('_STREAM_ID'), rec_time(rec)
        run = self.runs.get(inv) if inv else None
        if run is None and stream in self.streams:
            run = self.runs.get(self.streams[stream])
        if run is None and rec.get('_TRANSPORT') == 'stdout' and not rec.get('_SYSTEMD_USER_UNIT'):
            near = [r for r in self.runs.values() if (r['_oneshot'] or t - r['_start'] <= YOUNG_S)
                    and r['_start'] <= t and (r['_end'] is None or t <= r['_end'] + ORPHAN_SLACK_S)]
            run = near[0] if len(near) == 1 else None
        if run is None:
            return
        if stream:
            self.streams[stream] = run['invocation_id']
        tgt = run.get('_into', run)
        tgt['_tail'].append(_ANSI.sub('', rec['MESSAGE'])[:500])
        if tgt['_oneshot'] or tgt['_end'] is not None:
            self._touch(tgt)

    def _public(self, run: dict[str, Any]) -> dict[str, Any]:
        out = {k: run[k] for k in PUBLIC}
        out.update(started_at=iso(run['_start']), finished_at=iso(run['_end']), log_tail=list(run['_tail']))
        return out

    def _alive(self, r: dict[str, Any]) -> bool:
        stale = r['_oneshot'] and self.last_t - r['_start'] > STALE_OPEN_S
        return r['_end'] > self.last_t - GRACE_S if r['_end'] is not None else not stale

    def drain(self) -> list[dict[str, Any]]:
        """Changed runs; a restart inside a crash loop is held until it ends."""
        out, keep = [], {}
        for inv, run in self.dirty.items():
            head = self.loops.get(run['unit'])
            if run['result'] == 'running' and head is not None and head is not run:
                keep[inv] = run
            else:
                out.append(self._public(run))
        self.dirty = keep
        self.runs = {k: r for k, r in self.runs.items() if k in keep or self._alive(r)}
        self.streams = {s: k for s, k in self.streams.items() if k in self.runs}
        self.loops = {u: h for u, h in self.loops.items() if self.last_t - h['_end'] <= LOOP_WINDOW_S}
        return out
