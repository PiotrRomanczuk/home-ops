"""Tests for POST /stop on the status page: it needs STATE/status.token.

Run:
    python3 -m unittest discover -s ops/mac/sprint/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import http.client
import stat
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sprint_tasks as q  # noqa: E402
import status  # noqa: E402
import status_auth as auth  # noqa: E402


class StopTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        q.setup(self.state)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), status.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.patches = [mock.patch.object(status, 'STATE', self.state), mock.patch.object(status, 'HOST', '127.0.0.1')]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def call(self, method: str, path: str, form: dict | None = None) -> tuple[int, str]:
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=10)
        body = urlencode(form) if form is not None else None
        conn.request(method, path, body=body, headers={'Content-Type': 'application/x-www-form-urlencoded'} if body else {})
        resp = conn.getresponse()
        text = resp.read().decode()
        conn.close()
        return resp.status, text

    def test_stop_without_or_with_a_wrong_token_is_refused(self):
        self.assertEqual(self.call('POST', '/stop')[0], 403)
        self.assertEqual(self.call('POST', '/stop', {})[0], 403)
        self.assertEqual(self.call('POST', '/stop', {'token': 'guess'})[0], 403)
        self.assertFalse((self.state / 'STOP').exists())

    def test_stop_with_the_token_from_the_page_works(self):
        code, page = self.call('GET', '/')
        token = (self.state / 'status.token').read_text().strip()
        self.assertEqual(code, 200)
        self.assertIn(f'name="token" value="{token}"', page)  # loopback: a hidden field of the form
        self.assertEqual(self.call('POST', '/stop', {'token': token})[0], 303)
        self.assertTrue((self.state / 'STOP').exists())

    def test_token_file_is_private_and_stable(self):
        first = auth.token(self.state)
        self.assertEqual(stat.S_IMODE((self.state / 'status.token').stat().st_mode), 0o600)
        self.assertEqual(auth.token(self.state), first)
        self.assertTrue(auth.valid(self.state, first))
        self.assertFalse(auth.valid(self.state, ''))

    def test_page_on_the_lan_asks_for_the_token_instead_of_printing_it(self):
        with mock.patch.object(status, 'HOST', '0.0.0.0'):
            _, page = self.call('GET', '/')
        token = (self.state / 'status.token').read_text().strip()
        self.assertNotIn(token, page)
        self.assertIn('type="password" name="token"', page)


if __name__ == '__main__':
    unittest.main()
