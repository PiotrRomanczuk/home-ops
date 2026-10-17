"""Unit tests for brief_parse — the daily-brief file → POST /api/briefs body.
Contract: docs/adr/2026-10-17-daily-briefs.md. No network, no git."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from brief_parse import BriefError, brief_payload, split_file  # noqa: E402

GOOD = """---
date: 2026-10-17
slot: morning
generated_at: 2026-10-17T06:03:12+02:00
title: "Sobota: spokojny dzień"
sources: [calendar, planner]
---

## Kalendarz
- 10:00 lekcja
"""


class BriefPayloadTest(unittest.TestCase):
    def test_good_file_maps_to_api_body(self):
        b = brief_payload('briefs/2026-10-17-morning.md', GOOD)
        self.assertEqual(b['date'], '2026-10-17')
        self.assertEqual(b['slot'], 'morning')
        self.assertEqual(b['title'], 'Sobota: spokojny dzień')
        self.assertEqual(b['sources'], ['calendar', 'planner'])
        self.assertEqual(b['generated_at'], '2026-10-17T06:03:12+02:00')
        self.assertTrue(b['body_md'].startswith('## Kalendarz'))

    def test_block_list_sources_and_missing_optional_fields(self):
        text = '---\ndate: 2026-10-17\nslot: evening\nsources:\n  - calendar\n  - "git log"\n---\nbody\n'
        b = brief_payload('briefs/2026-10-17-evening.md', text)
        self.assertEqual(b['sources'], ['calendar', 'git log'])
        self.assertIsNone(b['title'])
        self.assertIsNone(b['generated_at'])

    def test_frontmatter_must_match_filename(self):
        with self.assertRaises(BriefError):
            brief_payload('briefs/2026-10-18-morning.md', GOOD)
        with self.assertRaises(BriefError):
            brief_payload('briefs/2026-10-17-evening.md', GOOD)

    def test_bad_names_and_shapes_are_rejected(self):
        for name in ('briefs/2026-10-17-noon.md', 'notes/2026-10-17-morning.md', 'briefs/x.md'):
            with self.assertRaises(BriefError):
                brief_payload(name, GOOD)
        with self.assertRaises(BriefError):
            split_file('## no frontmatter')
        with self.assertRaises(BriefError):
            split_file('---\ndate: 2026-10-17\nbody without closing fence')
        with self.assertRaises(BriefError):
            brief_payload('briefs/2026-10-17-morning.md', '---\ndate: 2026-10-17\n---\n   \n')

    def test_oversized_body_is_rejected(self):
        text = '---\ndate: 2026-10-17\nslot: morning\n---\n' + 'x' * 20_001
        with self.assertRaises(BriefError):
            brief_payload('briefs/2026-10-17-morning.md', text)


if __name__ == '__main__':
    unittest.main()
