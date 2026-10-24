"""Unit tests for gmail_api + gmail_inventory. No network: urlopen is faked."""
from __future__ import annotations

import io
import json
import sqlite3
import sys
import unittest
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gmail_inventory  # noqa: E402
from gmail_api import Gmail, GmailError  # noqa: E402
from gmail_ratelimit import RateLimiter  # noqa: E402


class FakeOpener:
    """Returns queued JSON bodies (or HTTP status ints) and records requests."""

    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        if isinstance(resp, int):
            raise urllib.error.HTTPError(req.full_url, resp, 'err', {}, io.BytesIO(b'boom'))
        return io.BytesIO(json.dumps(resp).encode())


def client(*responses):
    opener = FakeOpener(*responses)
    return Gmail(lambda: 'tok', sleep=lambda s: None, opener=opener), opener


class GmailApiTest(unittest.TestCase):
    def test_iter_ids_follows_pages(self):
        g, op = client({'messages': [{'id': 'a'}, {'id': 'b'}], 'nextPageToken': 'p2'},
                       {'messages': [{'id': 'c'}]})
        self.assertEqual(list(g.iter_ids('from:x')), ['a', 'b', 'c'])
        second = parse_qs(urlparse(op.requests[1].full_url).query)
        self.assertEqual(second['pageToken'], ['p2'])
        self.assertEqual(second['q'], ['from:x'])

    def test_iter_ids_limit(self):
        g, _ = client({'messages': [{'id': 'a'}, {'id': 'b'}], 'nextPageToken': 'p2'})
        self.assertEqual(list(g.iter_ids('', limit=1)), ['a'])

    def test_batch_modify_chunks_by_1000(self):
        g, op = client({}, {}, {})
        g.batch_modify([str(i) for i in range(2500)], add=['L1'], remove=['INBOX'])
        sizes = [len(json.loads(r.data)['ids']) for r in op.requests]
        self.assertEqual(sizes, [1000, 1000, 500])
        self.assertEqual(json.loads(op.requests[0].data)['removeLabelIds'], ['INBOX'])

    def test_retries_on_429_then_succeeds(self):
        g, op = client(429, 503, {'labels': [{'id': 'L'}]})
        self.assertEqual(g.labels(), [{'id': 'L'}])
        self.assertEqual(len(op.requests), 3)

    def test_retries_on_network_timeout(self):
        g, op = client(TimeoutError('read timed out'), {'labels': []})
        self.assertEqual(g.labels(), [])
        self.assertEqual(len(op.requests), 2)

    def test_retries_on_403_quota_but_not_plain_403(self):
        quota = urllib.error.HTTPError('u', 403, 'q', {}, io.BytesIO(b'Quota exceeded for quota metric'))
        g, op = client(quota, {'labels': []})
        self.assertEqual(g.labels(), [])
        g2, _ = client(403)
        with self.assertRaises(GmailError):
            g2.labels()

    def test_rate_limiter_paces_calls(self):
        slept = []
        lim = RateLimiter(100, sleep=slept.append)
        for _ in range(3):
            lim.take(50)
        self.assertGreaterEqual(sum(slept), 0.9)  # 150 units at 100/s ≈ 1 s of waiting

    def test_rate_limiter_aimd(self):
        lim = RateLimiter(200, sleep=lambda s: None)
        lim.penalize()
        lim.penalize()  # same burst → only one cut
        self.assertEqual(lim.rate, 100)
        for _ in range(100):
            lim.reward()
        self.assertAlmostEqual(lim.rate, 105)
        for _ in range(10_000):
            lim.reward()
        self.assertEqual(lim.rate, 200)  # capped at the configured ceiling

    def test_non_retryable_raises(self):
        g, _ = client(400)
        with self.assertRaises(GmailError):
            g.labels()

    def test_bearer_header(self):
        g, op = client({'labels': []})
        g.labels()
        self.assertEqual(op.requests[0].get_header('Authorization'), 'Bearer tok')


MSG = {
    'id': 'm1', 'threadId': 't1', 'internalDate': '1700000000000', 'sizeEstimate': 1234,
    'labelIds': ['INBOX', 'UNREAD', 'CATEGORY_PROMOTIONS'],
    'payload': {'headers': [
        {'name': 'From', 'value': 'Biedronka <Newsletter@Biedronka.pl>'},
        {'name': 'To', 'value': 'p.romanczuk@gmail.com'},
        {'name': 'Cc', 'value': 'A <a@x.pl>, b@y.pl'},
        {'name': 'Subject', 'value': 'Promocja'},
        {'name': 'List-Unsubscribe', 'value': '<mailto:u@b.pl>'},
    ]},
}


class InventoryTest(unittest.TestCase):
    def test_to_row_normalises(self):
        row = gmail_inventory.to_row(MSG)
        self.assertEqual(row[4:7], ('newsletter@biedronka.pl', 'Biedronka', 'biedronka.pl'))
        self.assertEqual(row[7], 'a@x.pl,b@y.pl,p.romanczuk@gmail.com')
        self.assertEqual(row[9], 1)
        self.assertIn('CATEGORY_PROMOTIONS', row[10])

    def test_sync_skips_known_ids(self):
        db = sqlite3.connect(':memory:')
        db.executescript(gmail_inventory.SCHEMA)
        db.execute('INSERT INTO messages (id) VALUES (?)', ('old',))
        g, op = client({'messages': [{'id': 'old'}, {'id': 'm1'}]}, MSG)
        fetched = gmail_inventory.sync(g, db, workers=1, log=lambda *_: None)
        self.assertEqual(fetched, 1)
        self.assertEqual(len(op.requests), 2)  # 1 list + 1 metadata, 'old' not refetched
        senders = gmail_inventory.senders(db, where="id = 'm1'")
        self.assertEqual(senders[0][:4], ('newsletter@biedronka.pl', 'biedronka.pl', 1, 1))


if __name__ == '__main__':
    unittest.main()
