"""Tests for budget.py — parsing a real /usage report, the pace line and the start/pause decisions.

Run:
    python3 -m unittest discover -s ops/mac/sprint/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import budget as b  # noqa: E402

# usage_report from `claude -p /usage --output-format stream-json --verbose`, 2026-11-15
REPORT = {'rate_limits': {'limits': [
    {'kind': 'session', 'group': 'session', 'percent': 65, 'resets_at': '2026-11-15T13:50:00.421008+00:00', 'scope': None, 'is_active': True},
    {'kind': 'weekly_all', 'group': 'weekly', 'percent': 35, 'resets_at': '2026-11-16T16:00:00.421026+00:00', 'scope': None, 'is_active': False},
    {'kind': 'weekly_scoped', 'group': 'weekly', 'percent': 31, 'resets_at': '2026-11-16T16:00:00Z',
     'scope': {'model': {'display_name': 'Fable'}, 'surface': None}, 'is_active': False}]}}
CFG = {'weekly_cap': 80, 'pace_head_start': 10, 'session_cap': 90, 'fable_weekly_cap': 80}
RESET = datetime(2026, 11, 23, 16, 0, tzinfo=timezone.utc)  # the week after Monday 16.11 17:00 Warsaw


def limits(week: float, session: float = 10, fable: float = 0) -> b.Limits:
    return {'weekly': {'percent': week, 'resets_at': RESET}, 'session': {'percent': session, 'resets_at': RESET},
            'fable': {'percent': fable, 'resets_at': RESET}}


class ParseTest(unittest.TestCase):
    def test_real_report(self):
        lim = b.parse(REPORT)
        self.assertEqual(sorted(lim), ['fable', 'session', 'weekly'])
        self.assertEqual(lim['weekly']['percent'], 35.0)
        self.assertEqual(lim['session']['resets_at'], datetime(2026, 11, 15, 13, 50, 0, 421008, tzinfo=timezone.utc))
        self.assertEqual(lim['fable']['resets_at'].utcoffset(), timedelta(0))  # 'Z' parsed on Python 3.9

    def test_empty_report(self):
        self.assertEqual(b.parse({}), {})


class PaceTest(unittest.TestCase):
    def test_line_grows_through_the_week_up_to_the_cap(self):
        start = RESET - b.WEEK
        self.assertAlmostEqual(b.pace(80, 10, RESET, start), 10)
        self.assertAlmostEqual(b.pace(80, 10, RESET, start + b.WEEK / 2), 50)
        self.assertAlmostEqual(b.pace(80, 10, RESET, RESET - timedelta(hours=1)), 80)
        self.assertEqual(b.pace(80, 10, None, start), 80)


class VerdictTest(unittest.TestCase):
    mid_week = RESET - b.WEEK / 2  # pace line 50%

    def test_allowed_under_cap_pace_and_session(self):
        self.assertIsNone(b.verdict(limits(40), CFG, 'sonnet', self.mid_week))

    def test_blocked_by_pace_cap_session_and_fable(self):
        self.assertIn('tempo', b.verdict(limits(55), CFG, 'sonnet', self.mid_week))
        self.assertIn('80%', b.verdict(limits(80), CFG, 'sonnet', RESET - timedelta(hours=1)))
        self.assertIn('sesja', b.verdict(limits(40, session=92), CFG, 'sonnet', self.mid_week))
        self.assertIn('fable', b.verdict(limits(40, fable=85), CFG, 'fable', self.mid_week))
        self.assertIsNone(b.verdict(limits(40, fable=85), CFG, 'opus', self.mid_week))
        self.assertEqual(b.verdict({}, CFG, 'sonnet', self.mid_week), 'brak odczytu limitów')

    def test_exhausted_until_only_for_limits_really_used_up(self):
        now = RESET - timedelta(days=2)
        self.assertIsNone(b.exhausted_until(limits(60, session=70), 'sonnet', now))  # "rate limit" was something else
        self.assertEqual(b.exhausted_until(limits(60, session=100), 'sonnet', now), RESET)
        self.assertIsNone(b.exhausted_until(limits(60, fable=100), 'opus', now))  # Fable's week doesn't stop Opus
        self.assertEqual(b.exhausted_until(limits(60, fable=100), 'fable', now), RESET)


if __name__ == '__main__':
    unittest.main()
