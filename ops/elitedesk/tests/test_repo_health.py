"""Tests for gaps_parse (open blueprint gap IDs, four repo formats) and
repo_health (issues + gaps from the GitHub API through a fake getter).

Run:
    python3 -m unittest discover -s ops/elitedesk/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import base64
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gaps_parse as gp  # noqa: E402
import repo_health as rh  # noqa: E402

STRUMMY_DOMAIN = """# Skills
## Purpose
Mentions SKL-9 in prose, which is not a definition.
## Gaps & planned work

### SKL-1 · Student can reach their own skill checklist
**Missing** …
### ~~SKL-7~~ · Done already
_Shipped 2026-07-19: PRA-1 (aggregate
triggers fixed), NOT-1, ASG-3._

## Test plan
### SKL-8 · not a gap section
"""

STRUMMY_ROADMAP = """# Implementation Roadmap
| ID    | Gap |
| ----- | --- |
| ADM-5 | `/api/stats/weekly` has no role check |
| **PRA-1** | shipped above |
"""

LESSON_NOTES = """# Lesson Notes — blueprint
## Gaps & planned work

- **LN-5 Raport tygodniowy do rodzica mailem.** Missing: …
- **LN-6 Materiały przy lekcji.** Missing: …

_Shipped 2026-10-09: LN-2 — „Powtórka dnia”._
## Open questions
- LN-5: czy trzymać adres e-mail rodzica?
"""

D4 = """## Gaps & planned work
| ID | Gap | Brief |
| --- | --- | --- |
| BLD-1 | Import builds | Missing: … |
| CHR-3 | Temper/masterwork targets | … |
"""

SOCIAL_HUB = """## 8. Luki (kolejność proponowana)
| ID | Luka | Dlaczego |
|----|------|----------|
| CORE-1 | Jeden przepływ | … |
| CORE-10 | Coś | … |
"""


class TestParseGaps(unittest.TestCase):
    def test_strummy_headings_roadmap_and_wrapped_shipped_note(self):
        r = gp.parse_gaps({'11-skills.md': STRUMMY_DOMAIN, '90-roadmap.md': STRUMMY_ROADMAP})
        self.assertEqual(r['ids'], ['ADM-5', 'SKL-1'])  # PRA-1 shipped, SKL-7 struck, SKL-8/9 outside gaps

    def test_bold_bullets_and_open_questions_ignored(self):
        self.assertEqual(gp.parse_gaps({'BLUEPRINT.md': LESSON_NOTES})['ids'], ['LN-5', 'LN-6'])

    def test_tables_and_natural_sort(self):
        r = gp.parse_gaps({'BLUEPRINT.md': D4, '00-overview.md': SOCIAL_HUB})
        self.assertEqual(r['ids'], ['BLD-1', 'CHR-3', 'CORE-1', 'CORE-10'])
        self.assertEqual(r['by_prefix'], {'BLD': 1, 'CHR': 1, 'CORE': 2})
        self.assertEqual(r['count'], 4)

    def test_testing_strategy_and_audits_are_skipped(self):
        self.assertEqual(gp.parse_gaps({'91-testing-strategy.md': D4, '94-audit.md': D4, 'README.md': D4})['count'], 0)
        self.assertTrue(gp.counts_as_blueprint('12-billing-payments.md'))
        self.assertFalse(gp.counts_as_blueprint('92-launch-runbook.md'))


def b64(text: str) -> dict[str, str]:
    return {'encoding': 'base64', 'content': base64.b64encode(text.encode()).decode()}


def fake(routes: dict[str, object]):
    return lambda path: routes.get(path)


class TestRepoHealth(unittest.TestCase):
    NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)

    def test_issues_exclude_prs_and_count_bug_labels(self):
        gh = fake({'/repos/o/r/issues?state=open&per_page=100': [
            {'created_at': '2026-11-01T10:00:00Z', 'labels': [{'name': 'Bug'}]},
            {'created_at': '2026-10-01T10:00:00Z', 'labels': [{'name': 'enhancement'}]},
            {'created_at': '2026-09-01T10:00:00Z', 'pull_request': {}, 'labels': [{'name': 'bug'}]},
        ]})
        self.assertEqual(rh.issues_summary(gh, 'o/r', self.NOW),
                         {'open': 2, 'bugs': 1, 'oldest_days': 40, 'capped': False})

    def test_issues_api_failure_is_no_data(self):
        self.assertIsNone(rh.issues_summary(fake({}), 'o/r', self.NOW))

    def test_gaps_from_single_file_and_folder(self):
        gh = fake({
            '/repos/o/r/contents/docs/BLUEPRINT.md?ref=main': b64(LESSON_NOTES),
            '/repos/o/r/contents/docs/app-blueprint?ref=main': [
                {'type': 'file', 'name': '00-overview.md', 'path': 'docs/app-blueprint/00-overview.md'},
                {'type': 'file', 'name': '91-testing.md', 'path': 'docs/app-blueprint/91-testing.md'},
                {'type': 'dir', 'name': 'adr', 'path': 'docs/app-blueprint/adr'},
            ],
            '/repos/o/r/contents/docs/app-blueprint/00-overview.md?ref=main': b64(SOCIAL_HUB),
        })
        r = rh.blueprint_gaps(gh, 'o/r', 'main')
        self.assertEqual(r['ids'], ['CORE-1', 'CORE-10', 'LN-5', 'LN-6'])
        self.assertEqual(r['files'], 2)

    def test_no_blueprint_is_none(self):
        self.assertIsNone(rh.blueprint_gaps(fake({}), 'o/r', 'main'))


if __name__ == '__main__':
    unittest.main()
