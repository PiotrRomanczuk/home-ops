"""Unit tests for seo_plan (hypothesis verdicts), seo_drift (HTML rules) and
seo_opps (adaptive thresholds). No network, no DB."""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seo_drift import parse_page, rules, sitemap_paths  # noqa: E402
from seo_opps import low_ctr, striking_distance, thresholds  # noqa: E402
from seo_plan import evaluate, final_status, matches  # noqa: E402

HOME = 'https://gitarawarszawa.pl/'


def rows(days: list[tuple[str, str, int, int, float]]):
    return [{'day': d, 'query': q, 'page': HOME, 'clicks': c, 'impressions': i, 'position': p} for d, q, i, c, p in days]


class PlanTest(unittest.TestCase):
    H = {'id': 1, 'title': 'Targówek w sekcji dojazd', 'target_queries': 'targ[oó]wek', 'target_pages': [],
         'metric': 'impressions', 'shipped_at': '2026-09-01', 'observe_days': 28}

    def test_matches_by_query_regex_or_page_path(self):
        self.assertTrue(matches(self.H, {'query': 'nauka gitary Targówek', 'page': HOME}))
        self.assertFalse(matches(self.H, {'query': 'nauka gitary praga', 'page': HOME}))
        self.assertTrue(matches({'target_queries': '', 'target_pages': ['/poradnik/x']},
                                {'query': 'anything', 'page': HOME + 'poradnik/x'}))

    def test_pending_before_checkpoint(self):
        v = evaluate(self.H, [], [self.H], today=date(2026, 9, 10))
        self.assertEqual(v['day14']['status'], 'pending')
        self.assertIsNone(final_status(v))

    def test_helped_when_lift_beats_control(self):
        from datetime import timedelta
        ship, data = date(2026, 9, 1), []
        for k in range(1, 29):   # 28 days before ship: targówek 1/day, control 2/day
            d = (ship - timedelta(days=k)).isoformat()
            data += rows([(d, 'gitara targówek', 1, 0, 15.0), (d, 'gitara praga', 2, 0, 5.0)])
        for k in range(0, 28):   # after ship: targówek ×3, control flat
            d = (ship + timedelta(days=k)).isoformat()
            data += rows([(d, 'gitara targówek', 3, 0, 9.0), (d, 'gitara praga', 2, 0, 5.0)])
        v = evaluate(self.H, data, [self.H], today=date(2026, 10, 5))
        self.assertEqual(v['day14']['status'], 'helped')
        self.assertEqual(v['day28']['status'], 'helped')
        self.assertEqual(v['day28']['control_ratio'], 1.0)
        self.assertEqual(final_status(v), 'helped')

    def test_insufficient_when_too_few_impressions(self):
        data = rows([('2026-08-20', 'gitara targówek', 2, 0, 15.0), ('2026-09-05', 'gitara targówek', 4, 0, 9.0)])
        v = evaluate(self.H, data, [self.H], today=date(2026, 10, 5))
        self.assertEqual(v['day14']['status'], 'insufficient')
        self.assertEqual(final_status(v), 'neutral')


HTML = '''<html><head><title>Nauka gry na gitarze Praga-Północ — lekcje dla dorosłych</title>
<meta name="description" content="Lekcje gitary na Pradze-Północ przy metrze Szwedzka. Indywidualna nauka dla dorosłych od zera, 120 zł za godzinę.">
<link rel="canonical" href="https://gitarawarszawa.pl/"><script type="application/ld+json">{}</script></head>
<body><h1>Nauka gry</h1><p>''' + ('słowo ' * 300) + '''</p><a href="/cennik">Cennik</a><a href="tel:+48513602768">tel</a>
<a href="/poradnik">poradnik</a><a href="https://olx.pl">olx</a></body></html>'''


class DriftTest(unittest.TestCase):
    def test_parse_page_extracts_signals(self):
        p = parse_page(HTML, HOME)
        self.assertTrue(p['title'].startswith('Nauka gry na gitarze'))
        self.assertEqual(p['canonical'], HOME)
        self.assertTrue(p['has_jsonld'])
        self.assertEqual((p['cta_links'], p['internal_links']), (2, 2))
        self.assertGreater(p['words'], 290)

    def test_rules_clean_page_only_title_changed(self):
        snap = {'path': '/', 'status_code': 200, **parse_page(HTML, HOME)}
        self.assertEqual(rules(snap, None, HOME), [])
        found = rules(snap, {'title': 'Stary tytuł'}, HOME)
        self.assertEqual([f['rule'] for f in found], ['title-changed'])

    def test_rules_flag_thin_no_cta_noindex(self):
        snap = {'path': '/poradnik/x', 'status_code': 200, 'title': 'krótki', 'description': '', 'canonical': '/inny',
                'robots': 'noindex', 'has_jsonld': False, 'words': 50, 'cta_links': 0, 'internal_links': 0}
        got = {f['rule'] for f in rules(snap, None, HOME)}
        self.assertEqual(got, {'title-length', 'description-length', 'canonical-mismatch', 'noindex-in-sitemap',
                               'missing-jsonld', 'no-cta', 'thin-content'})

    def test_sitemap_paths_same_host_only(self):
        xml = '<urlset><url><loc>https://gitarawarszawa.pl/</loc></url><url><loc>https://gitarawarszawa.pl/poradnik</loc></url><url><loc>https://x.pl/</loc></url></urlset>'
        self.assertEqual(sitemap_paths(xml, HOME), ['/', '/poradnik'])


class OppsTest(unittest.TestCase):
    def test_thresholds_scale(self):
        self.assertEqual(thresholds(50)['min_imp'], 3)
        self.assertEqual(thresholds(5000)['min_imp'], 30)

    def test_striking_distance_and_low_ctr_on_tiny_site(self):
        data = rows([('2026-10-10', 'nauka gitary targówek', 4, 0, 12.0), ('2026-10-10', 'gitara praga', 6, 0, 3.0),
                     ('2026-10-10', 'lekcje gitary praga', 5, 2, 2.0), ('2026-10-10', 'x', 1, 0, 50.0)])
        sd = striking_distance(data)
        self.assertEqual([h['query'] for h in sd], ['nauka gitary targówek'])
        lc = low_ctr(data)
        self.assertEqual([h['query'] for h in lc], ['gitara praga'])


if __name__ == '__main__':
    unittest.main()
