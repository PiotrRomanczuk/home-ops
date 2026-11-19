"""Tests for machine.py — parsers fed with recorded macOS outputs, and the start/stop gates.

Run:
    python3 -m unittest discover -s ops/mac/gpu/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import machine as m  # noqa: E402

IOREG = '    | |   "HIDIdleTime" = 734512000000\n    | |   "HIDKeyboardModifierMappingPairs" = ()\n'
BATT_AC = "Now drawing from 'AC Power'\n -InternalBattery-0 (id=5374051)\t74%; charging; 1:33 remaining present: true\n"
BATT_BAT = "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=5374051)\t56%; discharging;\n"
ASSERT = ('Assertion status system-wide:\n   BackgroundTask                 0\n   PreventUserIdleDisplaySleep    {d}\n'
          '   PreventUserIdleSystemSleep     1\nListed by owning process:\n'
          '   pid 82(powerd): [0x0008] 01:10:01 PreventUserIdleSystemSleep named: "Powerd - Prevent sleep while display is on"\n')
SYSSTATE = 'Current System Capabilities are: CPU Graphics Audio Network \nCurrent Power State: 4\n'
DARK = 'Current System Capabilities are: CPU Network \nCurrent Power State: 2\n'
PS = ('  101   101 /opt/homebrew/bin/uv run song2logic study list.jsonl --shard 1/2\n'
      '  102   101 python3 -m song2logic study list.jsonl --shard 1/2\n'
      '  200   200 /Users/p/.local/bin/song2logic scan-ui\n')


def snap(**over):
    base = {'idle_s': 900.0, 'on_ac': True, 'display_held': False, 'graphics': True, 'thermal': 0,
            'pressure': 1, 'logic': False, 'foreign': False}
    return {**base, **over}


class ParseTest(unittest.TestCase):
    def test_idle_seconds(self):
        self.assertAlmostEqual(m.parse_idle(IOREG), 734.512)
        self.assertIsNone(m.parse_idle(''))

    def test_power_source(self):
        self.assertTrue(m.parse_on_ac(BATT_AC))
        self.assertFalse(m.parse_on_ac(BATT_BAT))
        self.assertFalse(m.parse_on_ac(''))

    def test_display_assertion_uses_summary_line(self):
        self.assertTrue(m.parse_display_held(ASSERT.format(d=1)))
        self.assertFalse(m.parse_display_held(ASSERT.format(d=0)))  # powerd's system-sleep line doesn't count

    def test_graphics_capability(self):
        self.assertTrue(m.parse_graphics(SYSSTATE))
        self.assertFalse(m.parse_graphics(DARK))

    def test_int_default_when_unreadable(self):
        self.assertEqual(m.parse_int(' 1\n', 4), 1)
        self.assertEqual(m.parse_int('', 4), 4)

    def test_foreign_song2logic_ignores_own_group_and_scan_ui(self):
        self.assertFalse(m.foreign_song2logic(PS, own_pgids=[101]))
        self.assertTrue(m.foreign_song2logic(PS, own_pgids=[]))
        self.assertFalse(m.foreign_song2logic(PS.splitlines()[2], own_pgids=[]))


class GateTest(unittest.TestCase):
    def test_away_needs_idle_no_display_hold_no_logic(self):
        self.assertTrue(m.away(snap(), idle_min=10))
        self.assertFalse(m.away(snap(idle_s=120.0), idle_min=10))
        self.assertFalse(m.away(snap(display_held=True), idle_min=10))
        self.assertFalse(m.away(snap(logic=True), idle_min=10))
        self.assertFalse(m.away(snap(idle_s=None), idle_min=10))

    def test_can_start_and_must_stop(self):
        self.assertTrue(m.can_start(snap()))
        self.assertFalse(m.can_start(snap(thermal=1)))
        self.assertFalse(m.can_start(snap(graphics=False)))
        self.assertIsNone(m.must_stop(snap(thermal=1)))  # fair: don't start, but don't kill either
        self.assertEqual(m.must_stop(snap(on_ac=False)), 'bateria')
        self.assertIn('temperatura', m.must_stop(snap(thermal=2)))
        self.assertIn('pamięć', m.must_stop(snap(pressure=2)))


if __name__ == '__main__':
    unittest.main()
