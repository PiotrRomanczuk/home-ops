"""Unit tests for seo-analyse's pure parts: window split, deltas, district
classification, GA4 summary, card rendering and prompt assembly. No DB, no
network, no Claude CLI."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from seo_llm import build_prompt, extract_plan_updates  # noqa: E402
from seo_metrics import area_breakdown, ga4_summary, query_deltas, split_windows, totals  # noqa: E402
from seo_render import render_card, render_findings, render_plan  # noqa: E402

CFG = json.loads((HERE / 'seo-districts.json').read_text())


def row(day: str, query: str, imp: int, clicks: int = 0, pos: float = 5.0, page: str = 'https://gitarawarszawa.pl/'):
    return {'day': day, 'query': query, 'page': page, 'clicks': clicks, 'impressions': imp, 'position': pos}


ROWS = [
    row('2026-10-10', 'nauka gry na gitarze praga-północ', 5, 0, 3.2),
    row('2026-10-09', 'nauka gry na gitarze praga-północ', 3, 1, 4.0),
    row('2026-10-08', 'nauka gitary targówek', 2, 0, 12.0),
    row('2026-10-10', 'lekcje gitary dla seniorów', 1, 0, 9.0),
    row('2026-10-02', 'nauka gry na gitarze praga-północ', 4, 0, 8.0),   # previous window
    row('2026-10-01', 'nauka gitary warszawa', 6, 0, 40.0),               # previous window, lost
]


class WindowsTest(unittest.TestCase):
    def test_splits_two_consecutive_7d_windows(self):
        cur, prev = split_windows(ROWS, date(2026, 10, 10), 7)
        self.assertEqual(len(cur), 4)
        self.assertEqual(len(prev), 2)

    def test_totals_weight_position_by_impressions(self):
        cur, _ = split_windows(ROWS, date(2026, 10, 10), 7)
        t = totals(cur)
        self.assertEqual((t['impressions'], t['clicks']), (11, 1))
        self.assertAlmostEqual(t['position'], (5 * 3.2 + 3 * 4.0 + 2 * 12 + 1 * 9) / 11, places=1)


class QueryDeltasTest(unittest.TestCase):
    def test_top_new_lost(self):
        cur, prev = split_windows(ROWS, date(2026, 10, 10), 7)
        q = query_deltas(cur, prev)
        top = q['top'][0]
        self.assertEqual(top['query'], 'nauka gry na gitarze praga-północ')
        self.assertEqual(top['impressions'], 8)
        self.assertEqual(top['d_impressions'], 4)
        self.assertAlmostEqual(top['d_position'], 3.5 - 8.0, places=1)  # improved → negative
        self.assertEqual({n['query'] for n in q['new']}, {'nauka gitary targówek', 'lekcje gitary dla seniorów'})
        self.assertEqual([lo['query'] for lo in q['lost']], ['nauka gitary warszawa'])


class AreaTest(unittest.TestCase):
    def test_first_match_wins_and_unmatched_is_labelled(self):
        cur, prev = split_windows(ROWS, date(2026, 10, 10), 7)
        areas = {a['area']: a for a in area_breakdown(cur, prev, CFG)}
        self.assertEqual(areas['praga-polnoc']['impressions'], 8)
        self.assertEqual(areas['praga-polnoc']['d_impressions'], 4)
        self.assertEqual(areas['targowek']['line'], 'M2')
        self.assertEqual(areas[CFG['no_area_label']]['queries'], ['lekcje gitary dla seniorów'])
        self.assertEqual(areas['warszawa']['impressions'], 0)   # only in previous window
        self.assertEqual(areas['warszawa']['d_impressions'], -6)

    def test_m1_and_right_bank_patterns(self):
        from seo_metrics import classify_area, compile_areas
        areas = compile_areas(CFG)
        for q, key in [('gitara zoliborz', 'zoliborz'), ('lekcje gitary bródno', 'brodno'),
                       ('nauka gitary gocław', 'praga-poludnie'), ('gitara marki', 'marki-zabki'),
                       ('nauka gry na gitarze warszawa', 'warszawa'), ('gitara mokotów', 'mokotow-ursynow'),
                       ('lekcje gitary centrum', 'srodmiescie'), ('nauka gitary', None)]:
            self.assertEqual(classify_area(q, areas), key, q)


class Ga4Test(unittest.TestCase):
    def test_sums_sessions_and_events(self):
        s = ga4_summary([
            {'source_medium': 'google / organic', 'sessions': 4, 'events': {'phone_click': 1}},
            {'source_medium': 'google / organic', 'sessions': 2, 'events': {'phone_click': 1, 'booking_success': 1}},
            {'source_medium': 'olx / referral', 'sessions': 9, 'events': {}},
        ])
        self.assertEqual(s['sessions'], 15)
        self.assertEqual(s['by_source'][0]['source_medium'], 'olx / referral')
        self.assertEqual(s['events'], {'booking_success': 1, 'phone_click': 2})


class RenderTest(unittest.TestCase):
    def _metrics(self, rows):
        cur, prev = split_windows(rows, date(2026, 10, 10), 7)
        return {'site': 'gitarawarszawa.pl', 'window_end': '2026-10-10', 'window_days': 7,
                'totals': totals(cur), 'totals_prev': totals(prev), 'queries': query_deltas(cur, prev),
                'pages': [], 'areas': area_breakdown(cur, prev, CFG), 'ga4': None}

    def test_card_has_sections_and_fits_width(self):
        card = render_card(self._metrics(ROWS))
        self.assertIn('DZIELNICE', card)
        self.assertIn('Praga-Północ', card)
        self.assertIn('ZNIKNĘŁY: nauka gitary warszawa', card)
        self.assertTrue(all(len(line) <= 78 for line in card.splitlines()), card)

    def test_empty_window_is_explained_not_crashing(self):
        card = render_card(self._metrics([]))
        self.assertIn('brak danych', card)

    def test_prompt_substitutes_metrics_and_history(self):
        with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False) as f:
            f.write('H:\n{{HISTORY}}\nM:\n{{METRICS_JSON}}')
        p = build_prompt(Path(f.name), {'site': 'x'}, [{'day': '2026-10-12', 'narrative': 'ok'}])
        self.assertIn('### 2026-10-12\nok', p)
        self.assertIn('"site": "x"', p)


class PlanIoTest(unittest.TestCase):
    def test_extract_plan_updates_block(self):
        text = 'CO SIĘ ZMIENIŁO\nnic\n```plan-updates\n[{"action": "propose", "title": "x"}, "junk"]\n```'
        narrative, ups = extract_plan_updates(text)
        self.assertEqual(narrative, 'CO SIĘ ZMIENIŁO\nnic')
        self.assertEqual(ups, [{'action': 'propose', 'title': 'x'}])
        self.assertEqual(extract_plan_updates('tekst ```plan-updates\n[broken\n```'), ('tekst', []))

    def test_render_plan_and_findings(self):
        plan = [{'id': 1, 'status': 'shipped', 'priority': 70, 'title': 'Targówek', 'verdict': {'day14': {'status': 'helped'}}}]
        self.assertIn('#1   shipped   p70  helped/—  Targówek', render_plan(plan))
        self.assertIn('pusty', render_plan([]))
        self.assertIn('no-cta', render_findings([{'severity': 'warn', 'path': '/poradnik/x', 'rule': 'no-cta', 'detail': 'brak'}]))


if __name__ == '__main__':
    unittest.main()
