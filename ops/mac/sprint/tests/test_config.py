"""Tests for config.py — defaults under STATE/config.json, and the time windows.

Run:
    python3 -m unittest discover -s ops/mac/sprint/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

WINDOWS = ['mon-fri 08:30-16:00', 'daily 00:00-07:00']
MON, SAT = datetime(2026, 11, 16), datetime(2026, 11, 21)  # 16.11.2026 is a Monday


def at(day: datetime, hhmm: str) -> datetime:
    hours, minutes = map(int, hhmm.split(':'))
    return day.replace(hour=hours, minute=minutes)


class WindowTest(unittest.TestCase):
    def test_days(self):
        self.assertEqual(config.days('mon-fri'), {0, 1, 2, 3, 4})
        self.assertEqual(config.days('sat-sun'), {5, 6})
        self.assertEqual(config.days('mon,wed,fri'), {0, 2, 4})
        self.assertEqual(config.days('daily'), set(range(7)))

    def test_office_hours_and_nights(self):
        self.assertEqual(config.window_end(WINDOWS, at(MON, '09:00')), at(MON, '16:00'))
        self.assertEqual(config.window_end(WINDOWS, at(MON, '03:00')), at(MON, '07:00'))
        self.assertIsNone(config.window_end(WINDOWS, at(MON, '18:00')))
        self.assertIsNone(config.window_end(WINDOWS, at(SAT, '10:00')))  # weekend days are Piotr's
        self.assertEqual(config.window_end(WINDOWS, at(SAT, '01:00')), at(SAT, '07:00'))

    def test_window_past_midnight(self):
        late = ['fri 22:00-02:00']
        friday = datetime(2026, 11, 20)
        self.assertEqual(config.window_end(late, at(friday, '23:00')), at(SAT, '02:00'))
        self.assertEqual(config.window_end(late, at(SAT, '01:30')), at(SAT, '02:00'))
        self.assertIsNone(config.window_end(late, at(SAT, '23:00')))

    def test_task_must_fit_before_the_window_ends(self):
        self.assertTrue(config.fits(WINDOWS, at(MON, '15:00'), 60))
        self.assertFalse(config.fits(WINDOWS, at(MON, '15:00'), 61))
        self.assertFalse(config.fits(WINDOWS, at(MON, '17:00'), 10))


class LoadTest(unittest.TestCase):
    def test_user_values_override_defaults_per_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            self.assertEqual(config.load(state)['claude']['weekly_cap'], 80)
            (state / 'config.json').write_text(json.dumps({'claude': {'weekly_cap': 70}, 'local': {'idle_min': 5}}))
            cfg = config.load(state)
            self.assertEqual((cfg['claude']['weekly_cap'], cfg['claude']['session_cap']), (70, 90))
            self.assertEqual((cfg['local']['idle_min'], cfg['local']['max_tasks_per_day']), (5, 8))


if __name__ == '__main__':
    unittest.main()
