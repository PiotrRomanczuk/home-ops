"""activity_units — which systemd --user units activity-watcher tracks and
which project each one works for.

Tracked = a unit file Piotr installed under ~/.config/systemd/user (desktop
session units from /usr/lib are noise). Project = first PROJECT_PATTERNS match,
else WorkingDirectory=~/code/<dir>. Slugs are the vault/projects-table slugs.
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

# First match wins. Keep in sync with the vault project slugs (PROJECTS.md).
PROJECT_PATTERNS: list[tuple[str, str]] = [
    ('seo-*', 'gitara-lekcje'),
    ('brief-pull*', 'daily-brief'),
    ('lesson-*', 'lesson-notes'),
    ('natalia-*', 'natalia-cv'),
    ('social-hub*', 'social-hub'),
    ('szczerze-mowiac*', 'szczerze-mowiac'),
    ('strummy-*', 'strummy'),
    ('student*', 'strummy'),
    ('github-runner-strummy*', 'strummy'),
    ('gha-runner-*', 'strummy'),
    ('cloudflared-strummy*', 'strummy'),
    ('job-radar*', 'job-radar'),
    ('server-refresh*', 'job-radar'),
    ('olx-scraper*', 'olx-scraper'),
    ('d4-*', 'd4-build-agent'),
    ('stano-*', 'stano'),
    ('tiktok-worker*', 'instagram-stories-webhook'),
    ('gdrive-offsite*', 'infrastructure'),
    ('*-mdns.service', 'infrastructure'),
    ('daily-digest*', 'home-ops'),
    ('pr-decide*', 'home-ops'),
    ('pg-backup*', 'home-ops'),
    ('planner-sync*', 'home-ops'),
    ('*-watcher.service', 'home-ops'),
    ('unit-failure-mail@*', 'home-ops'),
    ('llm-eval*', 'home-ops'),
]
WORKDIR_ALIASES = {'logs-stack': 'home-ops'}


def template_of(unit: str) -> str:
    """'unit-failure-mail@seo.service' → 'unit-failure-mail@.service'."""
    if '@' not in unit:
        return unit
    name, _, rest = unit.partition('@')
    return f'{name}@.{rest.rsplit(".", 1)[-1]}'


def parse_unit_file(text: str, home: str) -> dict[str, str]:
    """The two [Service]/[Timer] keys we care about. Last assignment wins,
    as in systemd; a leading '-' on WorkingDirectory means 'optional'."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        for key in ('Type', 'WorkingDirectory', 'Unit'):
            if line.startswith(key + '='):
                out[key] = line.split('=', 1)[1].strip().lstrip('-').replace('%h', home)
    return out


class UnitCatalog:
    def __init__(self, unit_dir: Path | None = None, home: str | None = None) -> None:
        self.home = home or os.path.expanduser('~')
        self.unit_dir = unit_dir or Path(self.home) / '.config' / 'systemd' / 'user'
        self.services: dict[str, dict[str, str]] = {}
        self.timer_targets: set[str] = set()

    def refresh(self) -> None:
        services: dict[str, dict[str, str]] = {}
        targets: set[str] = set()
        for path in sorted(self.unit_dir.glob('*.service')) + sorted(self.unit_dir.glob('*.timer')):
            try:
                keys = parse_unit_file(path.read_text(errors='replace'), self.home)
            except OSError:
                continue
            if path.suffix == '.timer':
                targets.add(keys.get('Unit') or path.stem + '.service')
            else:
                services[path.name] = keys
        self.services, self.timer_targets = services, targets

    def _keys(self, unit: str) -> dict[str, str] | None:
        return self.services.get(unit) or self.services.get(template_of(unit))

    def tracked(self, unit: str) -> bool:
        return self._keys(unit) is not None

    def is_oneshot(self, unit: str) -> bool:
        keys = self._keys(unit) or {}
        return keys.get('Type') == 'oneshot'

    def kind(self, unit: str) -> str:
        return 'timer' if unit in self.timer_targets else 'service'

    def project(self, unit: str) -> str | None:
        for pattern, slug in PROJECT_PATTERNS:
            if fnmatch.fnmatch(unit, pattern):
                return slug
        workdir = (self._keys(unit) or {}).get('WorkingDirectory', '')
        code = os.path.join(self.home, 'code') + os.sep
        if workdir.startswith(code):
            top = workdir[len(code):].split(os.sep, 1)[0]
            return WORKDIR_ALIASES.get(top, top) or None
        return None
