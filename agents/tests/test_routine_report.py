"""Unit tests for agents/routine_report.py — request shaping, no network."""
from __future__ import annotations

import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest import mock

from agents import routine_report as rr


class FakeReporter(rr.Reporter):
    def __init__(self, routine: str, responses: dict[str, dict]) -> None:
        super().__init__(routine, 'http://x', 't')
        self.calls: list[tuple[str, str, dict | None]] = []
        self.responses = responses

    def _call(self, method, path, body=None):
        self.calls.append((method, path, body))
        return self.responses.get(path.split('?')[0], {})


class ReporterTest(unittest.TestCase):
    def test_card_trims_and_caps_items(self):
        r = FakeReporter('seo-analyse', {'/api/cards': {'card': {'id': 1}}})
        r.card('x' * 300, items=[(f'item {i}', None) for i in range(8)], metric={'label': 'n', 'value': 1})
        _, path, body = r.calls[0]
        self.assertEqual(path, '/api/cards')
        self.assertEqual(len(body['headline']), 200)
        self.assertEqual(len(body['items']), 5)
        self.assertNotIn('url', body['items'][0])

    def test_answers_skip_consumed(self):
        r = FakeReporter('seo-improve', {'/api/decisions': {'decisions': [
            {'id': 1, 'answer': 'yes', 'consumed_at': None},
            {'id': 2, 'answer': 'no', 'consumed_at': '2026-10-13T00:00:00Z'},
        ]}})
        self.assertEqual([d['id'] for d in r.answers()], [1])
        self.assertIn('state=answered', r.calls[0][1])
        self.assertIn('routine=seo-improve', r.calls[0][1])

    def test_cli_ask_skip_if_open_does_not_file_twice(self):
        fake = FakeReporter('seo-improve', {'/api/decisions': {'decisions': [{'id': 9, 'ref': '53'}]}})
        with mock.patch.object(rr.Reporter, 'from_env', return_value=fake), \
                mock.patch.dict(os.environ, {'INGEST_URL': 'http://x', 'INGEST_TOKEN': 't'}):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rr.main(['ask', 'seo-improve', 'Merge PR #53?', '--ref', '53', '--skip-if-open'])
        self.assertTrue(json.loads(buf.getvalue())['skipped'])
        self.assertEqual([c[0] for c in fake.calls], ['GET'])

    def test_cli_card_parses_metric_and_options(self):
        fake = FakeReporter('seo-analyse', {'/api/cards': {'card': {'id': 1}}})
        with mock.patch.object(rr.Reporter, 'from_env', return_value=fake), redirect_stdout(io.StringIO()):
            rr.main(['card', 'seo-analyse', 'down', '--metric', 'findings=17', '--delta', '-2',
                     '--lower-is-better', '--item', 'a|https://e.com'])
        body = fake.calls[0][2]
        self.assertEqual(body['metric'], {'label': 'findings', 'value': 17, 'delta': -2, 'lower_is_better': True})
        self.assertEqual(body['items'], [{'text': 'a', 'url': 'https://e.com'}])
        self.assertEqual(rr._parse_option('yes:Merge'), {'key': 'yes', 'label': 'Merge'})


if __name__ == '__main__':
    unittest.main()
