"""Tests for activity_journal + activity_units — journald → unit runs.

Records mirror what `journalctl --user -o json` printed on elitedesk on
2026-11-08 (same MESSAGE_IDs and fields), trimmed to what the tracker reads.

Run:
    python3 -m unittest discover -s agents/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from collections import deque
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load(name: str):
    path = REPO_ROOT / 'agents' / 'elitedesk' / f'{name}.py'
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


aj = _load('activity_journal')
au = _load('activity_units')

T0 = 1_794_160_800.0  # 2026-11-08 18:00:00 UTC


def sd(mid: str, unit: str, inv: str, t: float, **extra) -> dict:
    """A systemd user-manager lifecycle record."""
    return {'SYSLOG_IDENTIFIER': 'systemd', 'MESSAGE_ID': mid, 'USER_UNIT': unit,
            'USER_INVOCATION_ID': inv, '__REALTIME_TIMESTAMP': str(int(t * 1e6)), **extra}


def out(msg: str, t: float, **extra) -> dict:
    """A program output line (no unit fields unless given)."""
    return {'MESSAGE': msg, 'SYSLOG_IDENTIFIER': 'sh', '_TRANSPORT': 'stdout',
            '__REALTIME_TIMESTAMP': str(int(t * 1e6)), **extra}


def oneshot_ok(unit: str, inv: str, t: float, lines: list[dict] | None = None) -> list[dict]:
    return [sd(aj.MSG_STARTING, unit, inv, t), *(lines or []),
            sd(aj.MSG_STARTED, unit, inv, t + 0.5, JOB_RESULT='done'),
            sd(aj.MSG_RESOURCES, unit, inv, t + 0.5, CPU_USAGE_NSEC='664364000', MEMORY_PEAK='92602368')]


def crash(unit: str, inv: str, t: float) -> list[dict]:
    """One cycle of stano-backfill: Started → exited 1 → Failed → Consumed."""
    return [sd(aj.MSG_STARTED, unit, inv, t, JOB_RESULT='done'),
            sd(aj.MSG_EXITED, unit, inv, t + 1, EXIT_STATUS='1', EXIT_CODE='exited'),
            sd(aj.MSG_UNIT_FAILED, unit, inv, t + 1, UNIT_RESULT='exit-code'),
            sd(aj.MSG_RESOURCES, unit, inv, t + 1, CPU_USAGE_NSEC='818000000', MEMORY_PEAK='107000000')]


UNIT_FILES = {
    'lesson-notes-social.service': 'Type=oneshot\nWorkingDirectory=%h/code/lesson-notes\n',
    'lesson-notes-social.timer': '[Timer]\nOnCalendar=*:0/15\n',
    'social-hub-cron.service': 'Type=oneshot\n',
    'social-hub-cron.timer': '[Timer]\nUnit=social-hub-cron.service\n',
    'stano-backfill.service': 'Type=simple\nWorkingDirectory=%h/code/marszal/Stano/backend\nRestart=on-failure\n',
    'brief-pull.service': 'Type=oneshot\nWorkingDirectory=-%h/code/logs-stack\n',
    'mystery.service': 'Type=oneshot\nWorkingDirectory=%h/code/logs-stack\n',
    'unit-failure-mail@.service': 'Type=oneshot\n',
}


class TrackerCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        unit_dir = Path(self.tmp.name)
        for name, body in UNIT_FILES.items():
            (unit_dir / name).write_text(body)
        self.catalog = au.UnitCatalog(unit_dir=unit_dir, home='/home/piotr')
        self.catalog.refresh()
        self.tr = aj.RunTracker(self.catalog)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def feed(self, recs: list[dict]) -> list[dict]:
        for r in recs:
            self.tr.feed(r)
        return self.tr.drain()


class CatalogTest(TrackerCase):
    def test_projects_kinds_and_tracking(self) -> None:
        c = self.catalog
        self.assertEqual(c.project('lesson-notes-social.service'), 'lesson-notes')
        self.assertEqual(c.project('mystery.service'), 'home-ops')  # ~/code/logs-stack alias
        self.assertEqual(c.project('stano-backfill.service'), 'stano')
        self.assertEqual(c.kind('social-hub-cron.service'), 'timer')
        self.assertEqual(c.kind('stano-backfill.service'), 'service')
        self.assertTrue(c.tracked('unit-failure-mail@seo-collect.service'))
        self.assertFalse(c.tracked('app-org.chromium.Chromium-3205.scope'))
        self.assertTrue(c.is_oneshot('brief-pull.service'))


class RunTrackerTest(TrackerCase):
    def test_oneshot_success_with_orphan_output(self) -> None:
        line = out('{"message":"No pending posts"}', T0 + 0.6, _STREAM_ID='s1')
        runs = self.feed(oneshot_ok('lesson-notes-social.service', 'inv1', T0) + [line])
        self.assertEqual(len(runs), 1)
        r = runs[0]
        self.assertEqual((r['result'], r['kind'], r['project_slug']), ('ok', 'timer', 'lesson-notes'))
        self.assertEqual((r['cpu_ms'], r['mem_peak_mb']), (664, 88))
        self.assertEqual(r['log_tail'], ['{"message":"No pending posts"}'])
        self.assertTrue(r['started_at'].startswith('2026-11-08T18:00:00'))

    def test_orphan_line_is_dropped_when_two_oneshots_overlap(self) -> None:
        recs = [sd(aj.MSG_STARTING, 'lesson-notes-social.service', 'a', T0),
                sd(aj.MSG_STARTING, 'social-hub-cron.service', 'b', T0),
                out('who wrote me?', T0 + 0.2)]
        runs = self.feed(recs)
        self.assertEqual(sorted(r['result'] for r in runs), ['running', 'running'])
        self.assertTrue(all(r['log_tail'] == [] for r in runs))

    def test_output_joins_by_invocation_then_stream(self) -> None:
        recs = [sd(aj.MSG_STARTING, 'brief-pull.service', 'bp', T0),
                out('pulled 3 briefs', T0 + 1, _SYSTEMD_USER_UNIT='brief-pull.service',
                    _SYSTEMD_INVOCATION_ID='bp', _STREAM_ID='st'),
                sd(aj.MSG_STARTING, 'social-hub-cron.service', 'other', T0 + 2),
                out('late line, unit already gone', T0 + 3, _STREAM_ID='st'),
                sd(aj.MSG_STARTED, 'brief-pull.service', 'bp', T0 + 4, JOB_RESULT='done')]
        runs = {r['invocation_id']: r for r in self.feed(recs)}
        self.assertEqual(runs['bp']['log_tail'], ['pulled 3 briefs', 'late line, unit already gone'])
        self.assertEqual(runs['bp']['project_slug'], 'daily-brief')

    def test_failed_oneshot_keeps_exit_code_and_reason(self) -> None:
        u = 'brief-pull.service'
        recs = [sd(aj.MSG_STARTING, u, 'f', T0),
                sd(aj.MSG_EXITED, u, 'f', T0 + 1, EXIT_STATUS='2'),
                sd(aj.MSG_UNIT_FAILED, u, 'f', T0 + 1, UNIT_RESULT='exit-code'),
                sd(aj.MSG_JOB_FAILED, u, 'f', T0 + 1, JOB_RESULT='failed')]
        (r,) = self.feed(recs)
        self.assertEqual((r['result'], r['exit_code'], r['detail']), ('failed', 2, 'exit-code'))

    def test_restart_loop_folds_into_one_row(self) -> None:
        u = 'stano-backfill.service'
        first = self.feed(crash(u, 'c0', T0))
        self.assertEqual([(r['invocation_id'], r['repeat_count']) for r in first], [('c0', 1)])
        recs = [rec for i in range(1, 6) for rec in crash(u, f'c{i}', T0 + 23 * i)]
        runs = self.feed(recs)
        self.assertEqual(len(runs), 1)
        self.assertEqual((runs[0]['invocation_id'], runs[0]['repeat_count']), ('c0', 6))
        self.assertEqual(runs[0]['cpu_ms'], 818 * 6)
        self.assertTrue(runs[0]['finished_at'].startswith('2026-11-08T18:01:5'))

    def test_loop_restart_still_running_is_held_back(self) -> None:
        u = 'stano-backfill.service'
        self.feed(crash(u, 'c0', T0))
        held = self.feed([sd(aj.MSG_STARTED, u, 'c1', T0 + 23, JOB_RESULT='done')])
        self.assertEqual(held, [])
        runs = self.feed(crash(u, 'c1', T0 + 23)[1:])
        self.assertEqual([(r['invocation_id'], r['repeat_count']) for r in runs], [('c0', 2)])

    def test_crash_loop_keeps_the_crash_message(self) -> None:
        u = 'stano-backfill.service'
        cycle = crash(u, 'c0', T0)
        cycle.insert(1, out('Error: OPENAI_API_KEY missing', T0 + 0.8, _STREAM_ID='x'))
        (r,) = self.feed(cycle)
        self.assertEqual(r['log_tail'], ['Error: OPENAI_API_KEY missing'])

    def test_syslog_lines_from_other_daemons_are_not_orphans(self) -> None:
        recs = [sd(aj.MSG_STARTING, 'brief-pull.service', 'bp', T0),
                out('Disconnected from user piotr', T0 + 0.1, SYSLOG_IDENTIFIER='sshd-session', _TRANSPORT='syslog')]
        (r,) = self.feed(recs)
        self.assertEqual(r['log_tail'], [])

    def test_long_running_service_does_not_soak_up_orphans(self) -> None:
        self.feed([sd(aj.MSG_STARTED, 'stano-backfill.service', 'svc', T0, JOB_RESULT='done')])
        self.feed([sd(aj.MSG_STARTING, 'brief-pull.service', 'bp', T0 + 600),
                   out('from brief-pull', T0 + 600.2)])
        self.assertEqual(self.tr.runs['bp']['_tail'], deque(['from brief-pull']))
        self.assertEqual(list(self.tr.runs['svc']['_tail']), [])

    def test_failure_after_a_quiet_gap_starts_a_new_row(self) -> None:
        u = 'stano-backfill.service'
        self.feed(crash(u, 'c0', T0))
        runs = self.feed(crash(u, 'c1', T0 + aj.LOOP_WINDOW_S + 60))
        self.assertEqual([(r['invocation_id'], r['repeat_count']) for r in runs], [('c1', 1)])

    def test_untracked_units_and_unseen_starts_are_ignored(self) -> None:
        recs = [sd(aj.MSG_STARTED, 'app-org.chromium.Chromium-1.scope', 'x', T0, JOB_RESULT='done'),
                sd(aj.MSG_RESOURCES, 'brief-pull.service', 'never-started', T0)]
        self.assertEqual(self.feed(recs), [])

    def test_running_lists_open_runs(self) -> None:
        self.feed([sd(aj.MSG_STARTING, 'brief-pull.service', 'r', T0)])
        self.assertEqual([r['unit'] for r in self.tr.running()], ['brief-pull.service'])


if __name__ == '__main__':
    unittest.main()
