"""Tests for queue_md — the QUEUE.md parser behind the "Kolejka" card.

Run:
    python3 -m unittest discover -s agents/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load():
    path = REPO_ROOT / 'agents' / 'elitedesk' / 'queue_md.py'
    spec = importlib.util.spec_from_file_location('queue_md', path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SAMPLE = (
    '---\ncreated: 2026-10-19\ntype: queue\n---\n'
    '# Kolejka\n\n'
    'Okno: 2026-10-19 → 2026-10-25 · pojemność ~6 h (etat od 10.2026) · fokus: 🔴 Strummy; [[analysis/x|social-hub]] czeka\n'
    'Zasady: 1 bilet w toku · agent nie merguje\n\n'
    '## W toku (max 1)\n\n'
    '- [ ] 🔴 S ⛓ [[projects/Strummy/Strummy|Strummy]] STR-10 zrzut konfiguracji · sonnet → sonnet · start 2026-10-19 · PR —\n'
    '  Brak: stos bez config.toml · Akceptacja: plik w NAS\n\n'
    '## Kolejka (uporządkowana wg §8)\n\n'
    '- [ ] 🔴 L ⛓ [[projects/Strummy/Strummy|Strummy]] STR-2 migracje na prod · fable → sonnet\n'
    '- [ ] 🧹 S 🖥 [[Strummy]] STR-13 jest.config gołe /worktrees/\n'
    '- [ ] zadanie bez klasy ani rozmiaru\n\n'
    '## Tor lokalny (drafty w tle, max 3)\n\n'
    '_(nieaktywny)_\n\n'
    '## Czeka na Piotra\n\n'
    '- [ ] 2026-10-20 Merge PR #928 (demo niewidoczne)\n\n'
    '## Zrobione (okno)\n\n'
    '- [x] 2026-10-19 🔴 S ⛓ STR-9 porty tylko z LAN — w budżecie (~30 min; plan fable)\n'
    '- [x] 2026-10-19 🔴 M STR-1 weryfikacja JWT — w budżecie (~1 h, fable, tylko odczyt)\n'
)


class TestHeader(unittest.TestCase):
    def setUp(self):
        self.q = _load().parse_queue_md(SAMPLE)

    def test_window_capacity_focus_rules(self):
        self.assertEqual(self.q['window_from'], '2026-10-19')
        self.assertEqual(self.q['window_to'], '2026-10-25')
        self.assertEqual(self.q['capacity_hours'], 6.0)
        self.assertEqual(self.q['focus'], '🔴 Strummy; social-hub czeka')
        self.assertEqual(self.q['rules'], '1 bilet w toku · agent nie merguje')


class TestTickets(unittest.TestCase):
    def setUp(self):
        self.mod = _load()
        self.q = self.mod.parse_queue_md(SAMPLE)

    def test_sections_present_and_counted(self):
        s = self.q['sections']
        self.assertEqual([len(s[k]) for k in ('in_progress', 'queue', 'local', 'waiting', 'done')], [1, 3, 0, 1, 2])
        self.assertEqual(self.q['summary']['queue'], 3)

    def test_in_progress_ticket_fields_and_brief(self):
        t = self.q['sections']['in_progress'][0]
        self.assertEqual((t['cls'], t['size'], t['flags'], t['project'], t['id']),
                         ('risk', 'S', ['unblocks'], 'Strummy', 'STR-10'))
        self.assertEqual(t['text'], 'zrzut konfiguracji')
        self.assertEqual(t['model'], 'sonnet → sonnet')
        self.assertEqual(t['meta'], 'start 2026-10-19 · PR —')
        self.assertEqual(t['brief'], 'Brak: stos bez config.toml · Akceptacja: plik w NAS')
        self.assertFalse(t['done'])

    def test_local_flag_and_bare_wikilink(self):
        t = self.q['sections']['queue'][1]
        self.assertEqual(t['flags'], ['local'])
        self.assertEqual(t['project'], 'Strummy')
        self.assertEqual(t['id'], 'STR-13')

    def test_unclassified_task_is_kept_as_text(self):
        t = self.q['sections']['queue'][2]
        self.assertIsNone(t['cls'])
        self.assertIsNone(t['size'])
        self.assertEqual(t['text'], 'zadanie bez klasy ani rozmiaru')

    def test_done_hours_sum_minutes_and_hours(self):
        done = self.q['sections']['done']
        self.assertTrue(all(t['done'] for t in done))
        self.assertEqual(done[0]['hours'], 0.5)
        self.assertEqual(done[1]['hours'], 1.0)
        self.assertEqual(self.q['summary']['done_hours'], 1.5)
        self.assertEqual(done[0]['date'], '2026-10-19')
        # date before class (the Dziennik/Zrobione convention) still classifies
        self.assertEqual((done[0]['cls'], done[0]['size'], done[0]['flags'], done[0]['id']), ('risk', 'S', ['unblocks'], 'STR-9'))

    def test_waiting_keeps_date_and_text(self):
        t = self.q['sections']['waiting'][0]
        self.assertEqual(t['date'], '2026-10-20')
        self.assertEqual(t['text'], 'Merge PR #928 (demo niewidoczne)')

    def test_empty_file(self):
        q = self.mod.parse_queue_md('')
        self.assertEqual(q['sections'], {})
        self.assertIsNone(q['window_from'])


if __name__ == '__main__':
    unittest.main()
