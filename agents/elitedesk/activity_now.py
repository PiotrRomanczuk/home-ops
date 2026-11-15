"""activity_now — the "right now" snapshot: who is using the CPU, which units
are running, what fires next, and whether a runner is busy.

CPU is grouped by owner from /proc/<pid>/cgroup, so a Playwright run shows up
as the runner unit that spawned it instead of forty chrome-headless-shells.
"""
from __future__ import annotations

import json
import subprocess
from typing import Any

SAMPLE_TOP = 6


def owner_from_cgroup(text: str, containers: dict[str, str]) -> str:
    """'0::/user.slice/…/app.slice/gha-runner-light.service' → 'gha-runner-light'."""
    path = text.strip().splitlines()[-1].split('::', 1)[-1] if text.strip() else ''
    leaf = path.rstrip('/').rsplit('/', 1)[-1]
    if leaf.startswith('docker-') and leaf.endswith('.scope'):
        cid = leaf[len('docker-'):-len('.scope')]
        return containers.get(cid, 'docker:' + cid[:12])
    if leaf.endswith('.service'):
        return leaf[:-len('.service')]
    if leaf.startswith('session-') or leaf.startswith('app-'):
        return 'sesja'
    return leaf or 'kernel'


def group_cpu(samples: list[tuple[str, float]], ncpu: int, top: int = SAMPLE_TOP) -> list[dict[str, Any]]:
    """[(owner, process cpu%)] → top owners as % of the whole machine."""
    totals: dict[str, float] = {}
    for owner, pct in samples:
        totals[owner] = totals.get(owner, 0.0) + pct
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return [{'owner': o, 'pct': round(p / max(ncpu, 1), 1)} for o, p in ranked[:top] if p / max(ncpu, 1) >= 0.5]


def docker_names() -> dict[str, str]:
    try:
        p = subprocess.run(['docker', 'ps', '--no-trunc', '--format', '{{.ID}} {{.Names}}'],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    return dict(line.split(' ', 1) for line in p.stdout.splitlines() if ' ' in line)


def next_timers(limit: int = 5) -> list[dict[str, Any]]:
    try:
        p = subprocess.run(['systemctl', '--user', 'list-timers', '-o', 'json', '--no-pager'],
                           capture_output=True, text=True, timeout=10)
        rows = json.loads(p.stdout or '[]')
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []
    rows = [r for r in rows if r.get('next')]
    rows.sort(key=lambda r: r['next'])
    return [{'unit': r.get('activates') or r.get('unit'), 'next_at': r['next'] / 1e6} for r in rows[:limit]]


class CpuSampler:
    """psutil keeps per-process CPU baselines between calls, so the first
    sample after start is empty and every later one covers the gap since."""

    def __init__(self, psutil: Any) -> None:
        self.ps = psutil
        self.names: dict[str, str] = {}
        self.ps.cpu_percent(interval=None)

    def sample(self, runner_dirs: list[str]) -> dict[str, Any]:
        self.names = docker_names() or self.names
        samples: list[tuple[str, float]] = []
        busy: set[str] = set()
        for p in self.ps.process_iter(['pid', 'cpu_percent', 'cmdline']):
            try:
                cmd = ' '.join(p.info.get('cmdline') or [])
                busy.update(d for d in runner_dirs if f'{d}/bin/Runner.Worker' in cmd)
                pct = p.info.get('cpu_percent') or 0.0
                if pct > 0:
                    with open(f"/proc/{p.info['pid']}/cgroup") as f:
                        samples.append((owner_from_cgroup(f.read(), self.names), pct))
            except (self.ps.Error, OSError):
                continue
        try:
            load_1 = round(self.ps.getloadavg()[0], 2)
        except (AttributeError, OSError):
            load_1 = None
        return {
            'cpu_pct': round(self.ps.cpu_percent(interval=None), 1),
            'load_1': load_1,
            'ncpu': self.ps.cpu_count() or 1,
            'owners': group_cpu(samples, self.ps.cpu_count() or 1),
            'busy_runner_dirs': sorted(busy),
        }
