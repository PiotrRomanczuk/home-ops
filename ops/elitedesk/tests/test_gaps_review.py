"""Review round 1 for PR #75: gaps_parse edge cases and repo_health error handling."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gaps_parse as gp  # noqa: E402
import repo_health as rh  # noqa: E402
from test_repo_health import SOCIAL_HUB, b64, fake  # noqa: E402


class TestReviewFixes(unittest.TestCase):
    NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)

    def test_shipped_paragraph_ends_at_next_definition(self):
        text = '## Gaps\n- **LN-2 Done.**\n_Shipped 2026-10-09: LN-2._\n- **LN-7 Nowa luka.**\n'
        self.assertEqual(gp.parse_gaps({'BLUEPRINT.md': text})['ids'], ['LN-7'])

    def test_shipped_note_ends_at_section_boundary(self):
        text = ('## Gaps\n- **SK-1 Done.**\n_Shipped 2026-10-09: SK-1._\n'
                '## More planned work\nSee SK-2 and SK-3 for context.\n- **SK-2 Open.**\n')
        self.assertEqual(gp.parse_gaps({'BLUEPRINT.md': text})['ids'], ['SK-2'])

    def test_shipped_note_ignores_ids_in_parentheses(self):
        text = '## Gaps\n### SKL-1 · Open\n### PRA-1 · Done\n_Shipped 2026-07-19: PRA-1 (unblocks SKL-1 later)._\n'
        self.assertEqual(gp.parse_gaps({'BLUEPRINT.md': text})['ids'], ['SKL-1'])

    def test_numbered_roadmap_in_single_blueprint(self):
        text = '## 90 · Roadmap\n1. SRC-1 — Źródła\n2. **REC-1** — Receipts\n3) PRD-1 — Produkty\n'
        self.assertEqual(gp.parse_gaps({'BLUEPRINT.md': text})['ids'], ['PRD-1', 'REC-1', 'SRC-1'])

    def test_technical_terms_are_not_gaps(self):
        text = '## Gaps\n- SHA-256 hashes are not verified yet\n- UTF-8 only\n- **LN-1 Real.**\n'
        self.assertEqual(gp.parse_gaps({'BLUEPRINT.md': text})['ids'], ['LN-1'])

    def test_bug_label_matches_whole_word(self):
        gh = fake({'/repos/o/r/issues?state=open&per_page=100': [
            {'created_at': '2026-11-01T10:00:00Z', 'labels': [{'name': 'debug'}]},
            {'created_at': '2026-11-01T10:00:00Z', 'labels': [{'name': 'not-a-bug'}]},
            {'created_at': '2026-11-01T10:00:00Z', 'labels': [{'name': 'type: bug'}]},
            {'created_at': '2026-11-01T10:00:00Z', 'labels': [{'name': 'bug'}]},
        ]})
        self.assertEqual(rh.issues_summary(gh, 'o/r', self.NOW)['bugs'], 2)

    def test_api_error_is_not_a_missing_blueprint(self):
        def gh(path):
            return None
        gh.status = lambda path: 403
        self.assertEqual(rh.blueprint_gaps(gh, 'o/r', 'main'), {'error': 'api'})

    def test_failed_file_fetch_marks_partial(self):
        routes = {
            '/repos/o/r/contents/docs/app-blueprint?ref=main': [
                {'type': 'file', 'name': '00-overview.md', 'path': 'docs/app-blueprint/00-overview.md'},
                {'type': 'file', 'name': '01-a.md', 'path': 'docs/app-blueprint/01-a.md'}],
            '/repos/o/r/contents/docs/app-blueprint/00-overview.md?ref=main': b64(SOCIAL_HUB),
        }

        def gh(path):
            return routes.get(path)
        gh.status = lambda path: 200 if path in routes else 404
        r = rh.blueprint_gaps(gh, 'o/r', 'main')
        self.assertTrue(r['partial'])
        self.assertEqual(r['ids'], ['CORE-1', 'CORE-10'])


if __name__ == '__main__':
    unittest.main()
