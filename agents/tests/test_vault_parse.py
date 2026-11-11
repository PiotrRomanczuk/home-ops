"""Tests for vault_parse — frontmatter subset incl. lists (project map relations).

Run:
    python3 -m unittest discover -s agents/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'elitedesk'))
import vault_parse as vp  # noqa: E402


class TestScalarsUnchanged(unittest.TestCase):
    """Existing readers (repo, deployed, health, stack) must see the same values."""

    def test_flat_values_and_ints(self):
        fm = vp.parse_frontmatter('status: hot\ncommits_30d: 13\nupdated: 2026-06-08')
        self.assertEqual(fm, {'status': 'hot', 'commits_30d': 13, 'updated': '2026-06-08'})

    def test_quoted_scalars_stay_strings(self):
        fm = vp.parse_frontmatter('repo: "strummy"\nlink: "[[home-ops]]"\nodd: "[a, b]"')
        self.assertEqual(fm['repo'], 'strummy')
        self.assertEqual(fm['link'], '[[home-ops]]')
        self.assertEqual(fm['odd'], '[a, b]')

    def test_comma_scalar_is_not_a_list(self):
        fm = vp.parse_frontmatter('stack: Python 3.13 (uv), selectolax, psycopg 3')
        self.assertEqual(fm['stack'], 'Python 3.13 (uv), selectolax, psycopg 3')

    def test_bare_wikilink_scalar_is_not_a_list(self):
        self.assertEqual(vp.parse_frontmatter('source: [[note]]')['source'], '[[note]]')

    def test_empty_value_without_items_stays_empty_string(self):
        self.assertEqual(vp.parse_frontmatter('summary:\nstatus: warm'), {'summary': '', 'status': 'warm'})


class TestLists(unittest.TestCase):
    def test_flow_list(self):
        self.assertEqual(vp.parse_frontmatter('hosts: [mac, uwh, github]')['hosts'], ['mac', 'uwh', 'github'])

    def test_empty_flow_list(self):
        self.assertEqual(vp.parse_frontmatter('feeds: []')['feeds'], [])

    def test_flow_list_of_quoted_wikilinks(self):
        fm = vp.parse_frontmatter('depends_on: ["[[supabase-studentproduction]]", "[[ollama]]"]')
        self.assertEqual(fm['depends_on'], ['supabase-studentproduction', 'ollama'])

    def test_wikilink_with_path_alias_heading(self):
        fm = vp.parse_frontmatter('feeds: ["[[1-Projekty/job-radar|JR]]", "[[Strummy#Now]]", "[[x.md]]"]')
        self.assertEqual(fm['feeds'], ['job-radar', 'Strummy', 'x'])

    def test_quoted_item_with_comma(self):
        self.assertEqual(vp.parse_frontmatter('tags: ["a, b", c]')['tags'], ['a, b', 'c'])

    def test_block_list(self):
        fm = vp.parse_frontmatter('feeds:\n  - "[[vectordigital]]"\n  - natalia-cv\nstatus: hot')
        self.assertEqual(fm['feeds'], ['vectordigital', 'natalia-cv'])
        self.assertEqual(fm['status'], 'hot')

    def test_block_list_item_with_colon(self):
        fm = vp.parse_frontmatter('links:\n- https://strummy.online\n- http://x:8080/a')
        self.assertEqual(fm['links'], ['https://strummy.online', 'http://x:8080/a'])
        self.assertNotIn('- https', fm)

    def test_block_list_trailing_comment(self):
        fm = vp.parse_frontmatter('paths:\n  - ~/code/a # planning\n  - "b # kept"')
        self.assertEqual(fm['paths'], ['~/code/a', 'b # kept'])


class TestAsList(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(vp.as_list(['a', '', 'b']), ['a', 'b'])
        self.assertEqual(vp.as_list('[[home-ops]]'), ['home-ops'])
        self.assertEqual(vp.as_list(''), [])
        self.assertEqual(vp.as_list(None), [])


if __name__ == '__main__':
    unittest.main()
