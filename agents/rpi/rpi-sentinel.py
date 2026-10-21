#!/usr/bin/env python3
"""rpi-sentinel — the Pi's independent-observer agent.

Everything else in home-ops observes the world *through* elitedesk (Postgres,
ingest, digest, github-repo-sync all live there), so elitedesk going down is
the one failure the stack cannot report about itself — the dead-agent
sentinel (migration 010) alerts by inserting into host_logs, a table that
dies with the host. This agent runs on the Pi (always-on, separate failure
domain, ~5W) and closes that gap with two loops:

  1. Watchdog: polls GET /api/health every CHECK_INTERVAL. After
     FAILS_TO_ALERT consecutive failures it emails an alert DIRECTLY from
     the Pi (stdlib smtplib, Gmail app password from a 0600 file — the
     send-digest.py pattern), re-alerting every REALERT_HOURS while down.
     On recovery it emails again and posts the full outage record into
     host_logs retroactively (it couldn't log during the outage — ingest
     was the thing that was down).

  2. Second-vantage deploy probes: every PROBE_INTERVAL, discovers deploy
     URLs from GET /api/projects (repo_meta.deploy.url, falling back to
     raw_frontmatter.deployed — no second hand-maintained mapping file) and
     probes each with the same shared check_url() that github-repo-sync
     uses from elitedesk. Transition-only emission: up→down posts an
     error-level host_logs event with source='app:<slug>' (which the
     project drill page already renders — zero UI changes), down→up posts
     an info recovery event. A real outage = both vantage points agree;
     an elitedesk egress problem = only one of them says down.

Env:
  INGEST_URL       (required) e.g. http://192.168.1.75:64421/api/ingest
  INGEST_TOKEN     (required) shared secret
  HOST_NAME        defaults to 'rpi'
  CHECK_INTERVAL   watchdog seconds between health checks (default 60)
  PROBE_INTERVAL   seconds between deploy-probe rounds (default 600)
  FAILS_TO_ALERT   consecutive health failures before alerting (default 3)
  REALERT_HOURS    re-alert cadence while ingest stays down (default 4)
  ALERT_TO         alert recipient (required unless ALERT_DRY_RUN=1)
  ALERT_FROM       alert sender  (required unless ALERT_DRY_RUN=1)
  SMTP_HOST        default smtp.gmail.com
  SMTP_PORT        default 587 (STARTTLS)
  SMTP_USER        default = ALERT_FROM
  SMTP_PASS_FILE   default ~/.config/home-ops/smtp.pass (0600, never env)
  ALERT_DRY_RUN    '1' = print alerts to stdout instead of sending
"""
from __future__ import annotations

import json
import os
import smtplib
import sys
import threading
import time
import urllib.error
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from typing import Any

# _common.py lives next to this script in production (~/bin/_common.py) and
# one level up in the repo (agents/_common.py). Try both so dev + deploy both
# work without any package wiring.
_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))
sys.path.insert(0, str(_here.parent))
from _common import IngestClient, Shutdown, check_url  # noqa: E402

HOST_NAME = os.environ.get('HOST_NAME', 'rpi')
CHECK_INTERVAL = float(os.environ.get('CHECK_INTERVAL', '60'))
PROBE_INTERVAL = float(os.environ.get('PROBE_INTERVAL', '600'))
FAILS_TO_ALERT = int(os.environ.get('FAILS_TO_ALERT', '3'))
REALERT_HOURS = float(os.environ.get('REALERT_HOURS', '4'))
ALERT_TO = os.environ.get('ALERT_TO', '')
ALERT_FROM = os.environ.get('ALERT_FROM', '')
SMTP_HOST = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER = os.environ.get('SMTP_USER', '') or ALERT_FROM
SMTP_PASS_FILE = Path(os.environ.get('SMTP_PASS_FILE', '~/.config/home-ops/smtp.pass')).expanduser()
ALERT_DRY_RUN = os.environ.get('ALERT_DRY_RUN', '') in ('1', 'true')

ic = IngestClient.from_env(host=HOST_NAME, source='agent:rpi-sentinel', timeout=10)
shutdown = Shutdown()

INGEST_BASE = ic.events_url.replace('/api/ingest', '').rstrip('/')
HEALTH_URL = INGEST_BASE + '/api/health'
PROJECTS_URL = INGEST_BASE + '/api/projects'


def post_log(level: str, message: str, data: dict[str, Any] | None = None) -> None:
    ic.post_log(level, message, data)


# ── alert email (send-digest.py pattern: stdlib smtplib, pass from 0600 file) ─

def send_alert(subject: str, body: str) -> bool:
    """Best-effort alert email. Never raises — the sentinel must keep
    running even when the alert channel itself is broken (it logs the
    failure to stderr, which journald keeps locally on the Pi)."""
    if ALERT_DRY_RUN:
        print(f'[dry-run alert] {subject}\n{body}')
        return True
    try:
        password = SMTP_PASS_FILE.read_text(encoding='utf-8').strip()
        if not password:
            print(f'alert failed: empty password file {SMTP_PASS_FILE}', file=sys.stderr)
            return False
    except OSError as e:
        print(f'alert failed: cannot read {SMTP_PASS_FILE}: {e}', file=sys.stderr)
        return False

    msg = EmailMessage()
    msg['From'] = ALERT_FROM
    msg['To'] = ALERT_TO
    msg['Subject'] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USER, password)
            smtp.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as e:
        # Never echo the password; the exception text for auth errors doesn't
        # contain it.
        print(f'alert send failed: {e}', file=sys.stderr)
        return False


# ── watchdog state machine (pure logic — unit-tested) ────────────────────

class WatchdogState:
    """Tracks consecutive health-check failures and decides when to signal.

    record(ok, now) returns one of:
      'down'      — just crossed FAILS_TO_ALERT consecutive failures
      'realert'   — still down and the re-alert window elapsed
      'recovered' — first success after a signaled outage
      None        — nothing to do
    down_since is the timestamp of the first failure in the losing streak.
    """

    def __init__(self, fails_to_alert: int = 3, realert_seconds: float = 4 * 3600) -> None:
        self.fails_to_alert = fails_to_alert
        self.realert_seconds = realert_seconds
        self.fails = 0
        self.down = False
        self.down_since: float | None = None
        self.last_alert: float | None = None

    def record(self, ok: bool, now: float) -> str | None:
        if ok:
            was_down = self.down
            self.fails = 0
            self.down = False
            self.last_alert = None
            if not was_down:
                # Sub-threshold blip — drop its timestamp so it can't pollute
                # the next real streak's start time. After a signaled outage,
                # down_since is kept until the caller reads it for the
                # recovery message and resets via clear_outage().
                self.down_since = None
            return 'recovered' if was_down else None
        self.fails += 1
        if self.down_since is None:
            self.down_since = now
        if not self.down and self.fails >= self.fails_to_alert:
            self.down = True
            self.last_alert = now
            return 'down'
        if self.down and self.last_alert is not None and now - self.last_alert >= self.realert_seconds:
            self.last_alert = now
            return 'realert'
        return None

    def clear_outage(self) -> None:
        self.down_since = None


# ── deploy-probe state (per-URL, transition-only — unit-tested) ──────────

class ProbeState:
    """Per-key up/down tracker that only signals on transitions, so a site
    that stays down doesn't spam an event every probe round.

    record(key, ok, now) returns 'down' (crossed fails_to_emit consecutive
    failures), 'recovered' (first success after a signaled down), or None.
    """

    def __init__(self, fails_to_emit: int = 2) -> None:
        self.fails_to_emit = fails_to_emit
        self._fails: dict[str, int] = {}
        self._down: dict[str, bool] = {}
        self.down_since: dict[str, float] = {}

    def record(self, key: str, ok: bool, now: float) -> str | None:
        if ok:
            was_down = self._down.get(key, False)
            self._fails[key] = 0
            self._down[key] = False
            if not was_down:
                # Same blip rule as WatchdogState — see comment there.
                self.down_since.pop(key, None)
            return 'recovered' if was_down else None
        self._fails[key] = self._fails.get(key, 0) + 1
        if self._fails[key] == 1:
            self.down_since.setdefault(key, now)
        if not self._down.get(key, False) and self._fails[key] >= self.fails_to_emit:
            self._down[key] = True
            return 'down'
        return None

    def clear(self, key: str) -> None:
        self.down_since.pop(key, None)


# ── HTTP helpers ──────────────────────────────────────────────────────────

def check_health(timeout: float = 5.0) -> bool:
    """True iff ingest answers 200 with {"ok": true} — one call covers both
    the ingest process and Postgres (the handler runs SELECT 1)."""
    req = urllib.request.Request(HEALTH_URL, headers={'X-Ingest-Token': ic.token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                return False
            body = json.loads(r.read() or b'{}')
            return body.get('ok') is True
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return False


def fetch_deploy_urls() -> dict[str, str]:
    """slug -> deploy URL, discovered from the projects API so elitedesk's
    github-repo-sync.projects.json stays the single source of URL truth."""
    req = urllib.request.Request(PROJECTS_URL, headers={'X-Ingest-Token': ic.token})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            payload = json.loads(r.read())
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return {}
    return extract_deploy_urls(payload)


def extract_deploy_urls(payload: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    projects = payload.get('projects', []) if isinstance(payload, dict) else []
    for p in projects:
        if not isinstance(p, dict) or not p.get('slug'):
            continue
        rm = p.get('repo_meta') or {}
        deploy = rm.get('deploy') or {}
        url = deploy.get('url') or (p.get('raw_frontmatter') or {}).get('deployed')
        if isinstance(url, str) and url.strip():
            out[str(p['slug'])] = url.strip()
    return out


# ── loops ─────────────────────────────────────────────────────────────────

def _fmt_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f'{h}h{m:02d}m' if h else f'{m}m{s:02d}s'


def watchdog_loop() -> None:
    state = WatchdogState(FAILS_TO_ALERT, REALERT_HOURS * 3600)
    while not shutdown.wait(CHECK_INTERVAL):
        now = time.time()
        action = state.record(check_health(), now)
        if action in ('down', 'realert'):
            since = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(state.down_since or now))
            dur = _fmt_duration(now - (state.down_since or now))
            prefix = 'still DOWN' if action == 'realert' else 'DOWN'
            send_alert(
                f'[home-ops] ingest {prefix} (from rpi)',
                f'home-ops ingest ({HEALTH_URL}) unreachable from the Pi.\n'
                f'Down since: {since} ({dur} ago, {state.fails} consecutive failed checks).\n\n'
                f'Postgres, viewer, digest and all agents depend on it — check elitedesk.\n'
                f'This alert was sent directly from the Pi; it does not depend on elitedesk.',
            )
        elif action == 'recovered':
            down_since = state.down_since or now
            dur = _fmt_duration(now - down_since)
            since = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(down_since))
            send_alert(
                '[home-ops] ingest RECOVERED (from rpi)',
                f'home-ops ingest is answering again (down since {since}, ~{dur}).',
            )
            # Retroactive outage record — we couldn't log while it was down,
            # because the thing that was down is where logs go.
            post_log('error', f'ingest outage over: down ~{dur} (watched from rpi)', {
                'down_since': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(down_since)),
                'recovered_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now)),
                'duration_s': int(now - down_since),
            })
            state.clear_outage()


def probe_loop() -> None:
    state = ProbeState(fails_to_emit=2)
    while not shutdown.wait(PROBE_INTERVAL):
        urls = fetch_deploy_urls()
        for slug, url in urls.items():
            reachable, status_code = check_url(url, timeout=10)
            if not reachable and not shutdown.wait(5):
                # Quick same-tick retry so one dropped packet can't start a
                # losing streak.
                reachable, status_code = check_url(url, timeout=10)
            now = time.time()
            action = state.record(url, reachable, now)
            if action == 'down':
                dur = _fmt_duration(now - state.down_since.get(url, now))
                ic.post_events([{
                    'host': HOST_NAME,
                    'source': f'app:{slug}',
                    'level': 'error',
                    'message': f'deploy unreachable from rpi: {url} '
                               f'({status_code if status_code is not None else "no response"})',
                    'data': {'url': url, 'status_code': status_code, 'failing_for': dur, 'vantage': 'rpi'},
                }])
            elif action == 'recovered':
                dur = _fmt_duration(now - state.down_since.get(url, now))
                ic.post_events([{
                    'host': HOST_NAME,
                    'source': f'app:{slug}',
                    'level': 'info',
                    'message': f'deploy reachable again from rpi: {url} (was down ~{dur})',
                    'data': {'url': url, 'status_code': status_code, 'vantage': 'rpi'},
                }])
                state.clear(url)
            if shutdown.is_set():
                break


def main() -> None:
    if not ALERT_DRY_RUN and (not ALERT_TO or not ALERT_FROM):
        print('ALERT_TO and ALERT_FROM required (or set ALERT_DRY_RUN=1)', file=sys.stderr)
        sys.exit(1)
    shutdown.install()
    prober = threading.Thread(target=probe_loop, daemon=True)
    prober.start()
    post_log('info', (
        f'rpi-sentinel up: health every {CHECK_INTERVAL:g}s (alert after {FAILS_TO_ALERT} fails, '
        f'realert {REALERT_HOURS:g}h), deploy probes every {PROBE_INTERVAL:g}s'
        + (' [ALERT_DRY_RUN]' if ALERT_DRY_RUN else '')
    ))
    watchdog_loop()
    post_log('info', 'rpi-sentinel down (signal)')


if __name__ == '__main__':
    main()
