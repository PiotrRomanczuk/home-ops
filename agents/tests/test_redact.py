"""Tests for redact.py — secrets masked to first 6 chars + '...' before leaving a host.

Every secret below is fake (right shape, random characters).

Run:
    python3 -m unittest discover -s agents/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from redact import redact  # noqa: E402

# Built at run time so secret scanners (GitGuardian) don't see a literal "Bearer <token>".
TOKEN = 'abcdefgh' * 2


class RedactTest(unittest.TestCase):
    def assertMasked(self, text: str, secret: str, kept: str) -> None:
        out = redact(text)
        self.assertNotIn(secret, out)
        self.assertIn(kept + '...', out)

    def test_prefixed_tokens(self):
        self.assertMasked('key sk-ant-api03-AbCdEfGhIjKlMnOpQrSt done', 'sk-ant-api03-AbCdEfGhIjKlMnOpQrSt', 'sk-ant')
        self.assertMasked('ghp_ABCDEFGHIJKLMNOPQRSTUV12', 'ghp_ABCDEFGHIJKLMNOPQRSTUV12', 'ghp_AB')
        self.assertMasked('AKIAABCDEFGHIJKLMNOP', 'AKIAABCDEFGHIJKLMNOP', 'AKIAAB')
        self.assertMasked('t=eyJhbGciOiJI.eyJzdWIiOiIx.SflKxwRJSMeK', 'eyJhbGciOiJI.eyJzdWIiOiIx.SflKxwRJSMeK', 'eyJhbG')

    def test_named_arguments_and_headers(self):
        self.assertMasked('npx ctx7 --api-key ctx7sk-1234abcd-ef', 'ctx7sk-1234abcd-ef', 'ctx7sk')
        self.assertMasked('curl -H "X-Ingest-Token: 0123456789abcdef"', '0123456789abcdef', '012345')
        self.assertMasked('PGPASSWORD=hunter2hunter2 psql', 'hunter2hunter2', 'hunter')
        self.assertMasked(f'Authorization: Bearer {TOKEN}', TOKEN, 'abcdef')

    def test_polish_password_phrases(self):
        self.assertMasked('hasło: Tajne123!xyz', 'Tajne123!xyz', 'Tajne1')
        self.assertMasked('haslo=Tajne123xyz', 'Tajne123xyz', 'Tajne1')
        self.assertMasked('Hasło = "Tajne123xyz"', 'Tajne123xyz', 'Tajne1')
        self.assertMasked('moje hasło to Tajne123xyz', 'Tajne123xyz', 'Tajne1')

    def test_sshpass_and_basic_auth(self):
        self.assertMasked('sshpass -p Tajne123xyz ssh air', 'Tajne123xyz', 'Tajne1')
        self.assertMasked("sshpass -p 'Tajne123xyz' ssh air", 'Tajne123xyz', 'Tajne1')
        self.assertMasked('Authorization: Basic dXNlcjpwYXNzd29yZA==', 'dXNlcjpwYXNzd29yZA==', 'dXNlcj')

    def test_secret_lookups_are_not_values(self):
        for text in ('PGPASSWORD="$(secret strummy-dev-db)" psql', 'sshpass -p "$(secret air-login)" ssh air'):
            self.assertEqual(redact(text), text)

    def test_dsn_password(self):
        out = redact('server-postgres postgresql://postgres:s3cretPassw0rd@127.0.0.1:5432/db')
        self.assertNotIn('s3cretPassw0rd', out)
        self.assertIn('postgresql://postgres:s3cret...@127.0.0.1', out)

    def test_plain_text_untouched_and_idempotent(self):
        text = 'zrób raport z 3 tokenów i hasła na jutro; tokens: 1200'
        self.assertEqual(redact(text), text)
        prose = 'hasło to nic ciekawego, hasła na jutro, a basic understanding wystarczy; hasło do bazy'
        self.assertEqual(redact(prose), prose)
        for secret_text in ('hasło: Tajne123!xyz', 'sshpass -p Tajne123xyz', 'Basic dXNlcjpwYXNzd29yZA=='):
            once = redact(secret_text)
            self.assertEqual(redact(once), once)
        once = redact('--token abcdefghijkl')
        self.assertEqual(redact(once), once)
        self.assertEqual(redact(''), '')


if __name__ == '__main__':
    unittest.main()
