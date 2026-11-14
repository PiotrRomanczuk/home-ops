"""Tests for issues_md — GitHub Issues → generated Now/Next/Later blocks.

Run:
    python3 -m unittest discover -s agents/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location('issues_md', REPO_ROOT / 'agents' / 'elitedesk' / 'issues_md.py')
assert _spec is not None and _spec.loader is not None
im = importlib.util.module_from_spec(_spec)
sys.modules['issues_md'] = im
_spec.loader.exec_module(im)

URL = 'https://github.com/o/r/issues/'


def issue(n: int, title: str, labels: list[str], body: str = '', created: str = '2026-11-14T10:00:00Z',
          pr: bool = False) -> dict:
    d = {'number': n, 'title': title, 'labels': [{'name': x} for x in labels], 'body': body,
         'created_at': created, 'html_url': f'{URL}{n}'}
    if pr:
        d['pull_request'] = {}
    return d


NOTE = """---
status: hot
zadania: github
---
# P

## Now (≤ 3)

- [ ] 🔴 S 2026-10-17 **Poufne** — tylko w vaulcie

## Next (≤ 7)
- [ ] 🔴 S 2026-10-17 **Rotacja** — [#5](https://github.com/o/r/issues/5) odsyłacz w ręcznej linii

## Later

## Pain points

- coś
"""


class IssueLineTest(unittest.TestCase):
    def test_rubric_format_with_planner_date(self) -> None:
        line = im.issue_line(issue(7, 'Rozliczenia:  karnety', ['klasa/przychod', 'size-l', 'odblokowuje', 'tor-lokalny'],
                                   body='x\n<!-- planner-date: 2026-11-12 -->'))
        self.assertEqual(line, f'- [ ] 💰 L ⛓ 🖥 2026-11-12 **Rozliczenia: karnety** — [#7]({URL}7)')

    def test_falls_back_to_created_date_and_skips_missing_class(self) -> None:
        line = im.issue_line(issue(8, 'Bez klasy', ['plan/later']))
        self.assertEqual(line, f'- [ ] 2026-11-14 **Bez klasy** — [#8]({URL}8)')


class RenderTest(unittest.TestCase):
    def test_sections_sort_and_filter(self) -> None:
        out = im.render_issue_blocks([
            issue(1, 'idea', ['plan/later', 'klasa/pomysl', 'size-s']),
            issue(2, 'hygiene L', ['plan/later', 'klasa/higiena', 'size-l']),
            issue(3, 'hygiene S', ['plan/later', 'klasa/higiena', 'size-s']),
            issue(4, 'blocker', ['plan/later', 'klasa/higiena', 'size-l', 'odblokowuje']),
            issue(5, 'now', ['plan/now', 'klasa/przychod']),
            issue(6, 'unplanned', ['klasa/fokus']),
            issue(9, 'a PR', ['plan/now'], pr=True),
        ])
        self.assertEqual([x.split('**')[1] for x in out['later']], ['blocker', 'hygiene S', 'hygiene L', 'idea'])
        self.assertEqual(len(out['now']), 1)
        self.assertEqual(out['next'], [])


class ReplaceBlocksTest(unittest.TestCase):
    rendered = {'now': ['- [ ] 💰 S 2026-11-14 **A** — [#1](https://github.com/o/r/issues/1)'],
                'next': [], 'later': ['- [ ] 🧹 S 2026-11-14 **B** — [#2](https://github.com/o/r/issues/2)']}

    def test_inserts_blocks_and_keeps_manual_lines(self) -> None:
        out = im.replace_issue_blocks(NOTE, self.rendered)
        now = out.split('## Now (≤ 3)\n')[1].split('## Next')[0]
        self.assertEqual(now, f'\n{im.START}\n{self.rendered["now"][0]}\n{im.END}\n\n'
                              '- [ ] 🔴 S 2026-10-17 **Poufne** — tylko w vaulcie\n\n')
        self.assertIn('odsyłacz w ręcznej linii', out)
        self.assertIn(f'## Later\n\n{im.START}\n{self.rendered["later"][0]}\n{im.END}\n\n## Pain points', out)

    def test_idempotent_and_replaces_existing_block(self) -> None:
        once = im.replace_issue_blocks(NOTE, self.rendered)
        self.assertEqual(im.replace_issue_blocks(once, self.rendered), once)
        emptied = im.replace_issue_blocks(once, {'now': [], 'next': [], 'later': []})
        self.assertNotIn('**A**', emptied)
        self.assertIn('**Poufne**', emptied)
        self.assertEqual(emptied.count(im.START), 3)

    def test_missing_section_is_skipped(self) -> None:
        self.assertEqual(im.replace_issue_blocks('# P\n\nno sections\n', self.rendered), '# P\n\nno sections\n')


class ToggleTest(unittest.TestCase):
    def test_only_generated_lines_count_as_issue_lines(self) -> None:
        md = im.replace_issue_blocks(NOTE, ReplaceBlocksTest.rendered)
        generated = ReplaceBlocksTest.rendered['now'][0][len('- [ ] '):]
        manual = '🔴 S 2026-10-17 **Rotacja** — [#5](https://github.com/o/r/issues/5) odsyłacz w ręcznej linii'
        self.assertTrue(im.in_issue_block(md, generated))
        self.assertFalse(im.in_issue_block(md, manual))
        self.assertEqual(im.issue_ref(generated), ('o/r', 1))
        self.assertIsNone(im.issue_ref('no link here'))


if __name__ == '__main__':
    unittest.main()
