"""Unit tests for gmail_unsub: header parsing, method detection, one-click POST. No network."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gmail_unsub import headers_of, one_click, parse_unsub, unsubscribe  # noqa: E402


class FakeResp(io.BytesIO):
    status = 200


class UnsubTest(unittest.TestCase):
    def test_method_detection(self):
        both = '<mailto:u@x.pl>, <https://x.pl/u?id=1>'
        self.assertEqual(parse_unsub(both, 'List-Unsubscribe=One-Click')['method'], 'one-click')
        self.assertEqual(parse_unsub(both, '')['method'], 'link')
        self.assertEqual(parse_unsub('<mailto:u@x.pl>', '')['method'], 'mailto')
        self.assertEqual(parse_unsub('', '')['method'], 'none')
        self.assertEqual(parse_unsub('<http://x.pl/u>', 'List-Unsubscribe=One-Click')['method'], 'none')

    def test_headers_unfolded_and_decoded(self):
        raw = (b'From: =?UTF-8?Q?Sklep?= <a@x.pl>\r\nList-Unsubscribe: <mailto:u@x.pl>,\r\n'
               b' <https://x.pl/u>\r\nList-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n\r\n')
        h = headers_of(raw)
        self.assertEqual(parse_unsub(h['list-unsubscribe'], h['list-unsubscribe-post'])['https'], 'https://x.pl/u')
        self.assertIn('a@x.pl', h['from'])

    def test_one_click_posts_rfc8058_body(self):
        seen = []

        def opener(req, timeout=None):
            seen.append(req)
            return FakeResp(b'')
        self.assertEqual(one_click('https://x.pl/u', opener), (True, '200'))
        self.assertEqual(seen[0].get_method(), 'POST')
        self.assertEqual(seen[0].data, b'List-Unsubscribe=One-Click')

    def test_unsubscribe_skips_non_one_click_and_logs(self):
        def opener(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 410, 'gone', {}, io.BytesIO(b''))
        entries = [{'from': 'a@x.pl', 'method': 'one-click', 'https': 'https://x.pl/u'},
                   {'from': 'b@x.pl', 'method': 'mailto', 'https': None}]
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / 'log.jsonl'
            self.assertEqual(unsubscribe(entries, log, opener, log=lambda *_: None), 0)
            lines = [json.loads(x) for x in log.read_text().splitlines()]
        self.assertEqual([(e['from'], e['ok'], e['status']) for e in lines], [('a@x.pl', False, '410')])


if __name__ == '__main__':
    unittest.main()
