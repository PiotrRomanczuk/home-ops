"""Unit tests for seo-collect's pure parts: row shaping (must match the
POST /api/seo/ingest contract) and the openssl-signed service-account JWT.
No network; the JWT test needs only the `openssl` binary."""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seo_google import jwt_signing_input, rs256_sign  # noqa: E402
from seo_sources import ga4_rows, gsc_rows, place_row  # noqa: E402


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


class GscRowsTest(unittest.TestCase):
    def test_maps_keys_and_casts_counts(self):
        rows = gsc_rows('gitarawarszawa.pl', [{
            'keys': ['2026-10-05', 'nauka gry na gitarze warszawa', 'https://gitarawarszawa.pl/'],
            'clicks': 2.0, 'impressions': 41.0, 'ctr': 0.0487, 'position': 7.4,
        }])
        self.assertEqual(rows, [{
            'site': 'gitarawarszawa.pl', 'day': '2026-10-05', 'query': 'nauka gry na gitarze warszawa',
            'page': 'https://gitarawarszawa.pl/', 'clicks': 2, 'impressions': 41, 'ctr': 0.0487, 'position': 7.4,
        }])
        self.assertIsInstance(rows[0]['clicks'], int)


class Ga4RowsTest(unittest.TestCase):
    def test_merges_traffic_and_events_on_day_and_source(self):
        dv = lambda *vs: [{'value': v} for v in vs]  # noqa: E731
        traffic = {'rows': [{'dimensionValues': dv('20261005', 'google / organic'), 'metricValues': dv('9', '7')}]}
        events = {'rows': [
            {'dimensionValues': dv('20261005', 'google / organic', 'booking_success'), 'metricValues': dv('2')},
            {'dimensionValues': dv('20261005', 'olx / referral', 'phone_click'), 'metricValues': dv('1')},
        ]}
        rows = sorted(ga4_rows('gitarawarszawa.pl', traffic, events), key=lambda r: r['source_medium'])
        self.assertEqual(rows[0], {'site': 'gitarawarszawa.pl', 'day': '2026-10-05', 'source_medium': 'google / organic',
                                   'sessions': 9, 'users': 7, 'events': {'booking_success': 2}})
        # An event with no matching traffic row still lands, with zero sessions.
        self.assertEqual(rows[1]['sessions'], 0)
        self.assertEqual(rows[1]['events'], {'phone_click': 1})

    def test_empty_reports(self):
        self.assertEqual(ga4_rows('x', {}, {}), [])


class PlaceRowTest(unittest.TestCase):
    def test_listing_without_reviews_keeps_nulls(self):
        row = place_row({'label': 'self', 'is_self': True}, {'id': 'ChIJ1', 'displayName': {'text': 'Piotr'}}, '2026-10-05')
        self.assertEqual(row, {'place_id': 'ChIJ1', 'day': '2026-10-05', 'label': 'self', 'name': 'Piotr',
                               'is_self': True, 'rating': None, 'review_count': None})

    def test_falls_back_to_label_when_name_missing(self):
        row = place_row({'label': 'tetmajer'}, {'id': 'ChIJ2', 'rating': 5.0, 'userRatingCount': 63}, '2026-10-05')
        self.assertEqual((row['name'], row['is_self'], row['review_count']), ('tetmajer', False, 63))


class JwtTest(unittest.TestCase):
    def test_claims_and_openssl_signature_verify(self):
        with tempfile.TemporaryDirectory() as d:
            key, pub = Path(d, 'k.pem'), Path(d, 'p.pem')
            subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048',
                            '-out', str(key)], check=True, capture_output=True)
            subprocess.run(['openssl', 'pkey', '-in', str(key), '-pubout', '-out', str(pub)],
                           check=True, capture_output=True)
            sa = {'client_email': 'seo@proj.iam.gserviceaccount.com', 'private_key': key.read_text()}
            unsigned = jwt_signing_input(sa, 1_000_000)
            sig = rs256_sign(unsigned, sa['private_key'])

            claims = json.loads(_b64d(unsigned.split('.')[1]))
            self.assertEqual(claims['iss'], sa['client_email'])
            self.assertEqual(claims['exp'] - claims['iat'], 3600)
            self.assertIn('webmasters.readonly', claims['scope'])

            sig_file = Path(d, 'sig')
            sig_file.write_bytes(_b64d(sig))
            ok = subprocess.run(['openssl', 'dgst', '-sha256', '-verify', str(pub), '-signature', str(sig_file)],
                                input=unsigned.encode(), capture_output=True)
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)


if __name__ == '__main__':
    unittest.main()
