"""Tests for planner-sync's markdown parsers.

Covers:
  * parse_project_file       — full markdown → record (frontmatter + sections)
  * _flip_task_in_section    — checkbox toggle in a specific section
  * _split_sections          — section-by-canonical-header extraction
  * _parse_frontmatter       — flat YAML key/value

These are the parsers powering the Projects tab. If they break, every
project drill page breaks silently. Cheap unit coverage; runs in <50ms.

Run:
    python3 -m unittest discover -s agents/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_planner_sync():
    """Load planner-sync.py as a module despite its hyphenated filename.
    Sets the env vars that IngestClient.from_env requires so the import
    doesn't sys.exit."""
    os.environ.setdefault('INGEST_URL', 'http://x/api/ingest')
    os.environ.setdefault('INGEST_TOKEN', 'y')
    path = REPO_ROOT / 'agents' / 'elitedesk' / 'planner-sync.py'
    spec = importlib.util.spec_from_file_location('planner_sync', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestFlipTaskInSection(unittest.TestCase):
    """The bit that does the actual checkbox flip when the UI toggles."""

    md = (
        '---\n'
        'status: hot\n'
        '---\n'
        '\n'
        '# Test Project\n'
        '\n'
        '## Now\n'
        '- [x] item zero done\n'
        '- [ ] item one open\n'
        '- [ ] item two open\n'
        '\n'
        '## Next\n'
        '- [ ] item zero of next\n'
        '\n'
        '## Later\n'
        '- [ ] also a task\n'
    )

    def setUp(self):
        self.mod = _load_planner_sync()

    def test_flip_open_to_done(self):
        out = self.mod._flip_task_in_section(self.md, 'now', 1, True)
        self.assertIn('- [x] item one open', out)
        # The other items must be untouched.
        self.assertIn('- [x] item zero done', out)
        self.assertIn('- [ ] item two open', out)

    def test_flip_done_to_open(self):
        out = self.mod._flip_task_in_section(self.md, 'now', 0, False)
        self.assertIn('- [ ] item zero done', out)

    def test_out_of_range_idx_returns_none(self):
        self.assertIsNone(self.mod._flip_task_in_section(self.md, 'now', 5, True))

    def test_section_isolation(self):
        out = self.mod._flip_task_in_section(self.md, 'next', 0, True)
        self.assertIn('- [x] item zero of next', out)
        # The Now items must NOT be touched.
        self.assertIn('- [x] item zero done', out)  # already done, unchanged
        self.assertIn('- [ ] item one open', out)
        self.assertIn('- [ ] item two open', out)

    def test_section_with_subtitle(self):
        """Sections like '## Next — Session 4 (functional hardening)' should
        still match 'next' on the first word — the planner's home-ops file
        does this for session breakdowns."""
        md = (
            '## Next — Session 4 (description)\n'
            '- [ ] subtitle section task\n'
        )
        out = self.mod._flip_task_in_section(md, 'next', 0, True)
        self.assertIn('- [x] subtitle section task', out)


class TestSplitSections(unittest.TestCase):
    """Section extraction must handle the canonical names AND the
    "X — subtitle" pattern that real vault files use."""

    def setUp(self):
        self.mod = _load_planner_sync()

    def test_canonical_names(self):
        body = (
            '## Now\nfoo\n\n'
            '## Next\nbar\n\n'
            '## Later\nbaz\n\n'
            '## Pain points\nthe pain\n'
        )
        sections = self.mod._split_sections(body)
        self.assertEqual(sections['Now'], 'foo')
        self.assertEqual(sections['Next'], 'bar')
        self.assertEqual(sections['Later'], 'baz')
        self.assertEqual(sections['Pain points'], 'the pain')

    def test_first_match_wins_for_multiple_next(self):
        body = (
            '## Next — Session 4\nsession 4 content\n\n'
            '## Next — Session 4b\nsession 4b content\n'
        )
        sections = self.mod._split_sections(body)
        self.assertEqual(sections['Next'], 'session 4 content')


class TestParseFrontmatter(unittest.TestCase):
    def setUp(self):
        self.mod = _load_planner_sync()

    def test_basic_key_values(self):
        fm = self.mod._parse_frontmatter('status: hot\nupdated: 2026-06-08\ncommits_30d: 13')
        self.assertEqual(fm['status'], 'hot')
        self.assertEqual(fm['updated'], '2026-06-08')
        self.assertEqual(fm['commits_30d'], 13)  # casts bare ints

    def test_quoted_strings(self):
        fm = self.mod._parse_frontmatter('title: "Quoted"\nother: \'also quoted\'')
        self.assertEqual(fm['title'], 'Quoted')
        self.assertEqual(fm['other'], 'also quoted')

    def test_skips_comments_and_blanks(self):
        fm = self.mod._parse_frontmatter('# this is a comment\nstatus: warm\n\n')
        self.assertEqual(fm, {'status': 'warm'})


class TestParseProjectFile(unittest.TestCase):
    def setUp(self):
        self.mod = _load_planner_sync()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _write(self, name, content):
        p = Path(self.tmp.name) / name
        p.write_text(content, encoding='utf-8')
        return p

    def test_hot_project_full_shape(self):
        path = self._write('demo.md', (
            '---\n'
            'updated: 2026-06-08\n'
            'status: hot\n'
            'last_commit: 2026-06-08\n'
            'commits_30d: 13\n'
            'path: ~/Desktop/demo\n'
            '---\n'
            '\n'
            '# Demo Project\n'
            '\n'
            'Description.\n'
            '\n'
            '## Now\n'
            '- [x] done thing\n'
            '- [ ] open thing\n'
            '\n'
            '## Next\n'
            '- [ ] later thing\n'
            '\n'
            '## Pain points\n'
            'The pain is real.\n'
        ))
        rec = self.mod.parse_project_file(path)
        self.assertIsNotNone(rec)
        self.assertEqual(rec['slug'], 'demo')
        self.assertEqual(rec['title'], 'Demo Project')
        self.assertEqual(rec['status'], 'hot')
        self.assertEqual(rec['commits_30d'], 13)
        self.assertIn('done thing', rec['now_md'])
        self.assertIn('open thing', rec['now_md'])
        self.assertIn('later thing', rec['next_md'])
        self.assertEqual(rec['pain_md'], 'The pain is real.')

    def test_no_frontmatter_falls_back_to_filename(self):
        path = self._write('orphan.md', '# Just a Title\n\n## Now\n- [ ] foo\n')
        rec = self.mod.parse_project_file(path)
        self.assertIsNotNone(rec)
        self.assertEqual(rec['slug'], 'orphan')
        self.assertEqual(rec['title'], 'Just a Title')
        self.assertEqual(rec['status'], 'dormant')

    def test_invalid_status_defaults_to_dormant(self):
        path = self._write('bogus.md', '---\nstatus: weird-value\n---\n# X\n')
        rec = self.mod.parse_project_file(path)
        self.assertEqual(rec['status'], 'dormant')


if __name__ == '__main__':
    unittest.main()
