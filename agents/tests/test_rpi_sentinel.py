"""Tests for rpi-sentinel's pure logic.

Covers:
  * WatchdogState  — K-consecutive threshold, re-alert window, recovery,
                     blip handling (sub-threshold fails must not pollute
                     the next streak's down_since)
  * ProbeState     — per-URL transition-only emission
  * extract_deploy_urls — repo_meta.deploy.url preferred, raw_frontmatter
                     fallback, malformed rows skipped
  * check_health   — 200+ok:true / 503 / network error (mocked urlopen)
  * send_alert     — dry-run mode; SMTP failure returns False, never raises

No real network or SMTP anywhere. Run:
    python3 -m unittest discover -s agents/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_module():
    """Load rpi-sentinel.py as a module despite its hyphenated filename.
    Sets the env vars IngestClient.from_env requires so the import doesn't
    sys.exit — same trick as test_planner_sync.py."""
    os.environ.setdefault('INGEST_URL', 'http://x/api/ingest')
    os.environ.setdefault('INGEST_TOKEN', 'y')
    path = REPO_ROOT / 'agents' / 'rpi' / 'rpi-sentinel.py'
    spec = importlib.util.spec_from_file_location('rpi_sentinel', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_module()


class TestWatchdogState(unittest.TestCase):
    def test_no_alert_before_threshold(self):
        s = mod.WatchdogState(fails_to_alert=3)
        self.assertIsNone(s.record(False, 100))
        self.assertIsNone(s.record(False, 160))

    def test_down_at_threshold_exactly_once(self):
        s = mod.WatchdogState(fails_to_alert=3)
        s.record(False, 100)
        s.record(False, 160)
        self.assertEqual(s.record(False, 220), 'down')
        self.assertIsNone(s.record(False, 280))  # still down, window not elapsed

    def test_down_since_is_first_failure_of_streak(self):
        s = mod.WatchdogState(fails_to_alert=3)
        s.record(False, 100)
        s.record(False, 160)
        s.record(False, 220)
        self.assertEqual(s.down_since, 100)

    def test_realert_after_window(self):
        s = mod.WatchdogState(fails_to_alert=2, realert_seconds=3600)
        s.record(False, 0)
        self.assertEqual(s.record(False, 60), 'down')
        self.assertIsNone(s.record(False, 1000))
        self.assertEqual(s.record(False, 60 + 3600), 'realert')
        self.assertIsNone(s.record(False, 60 + 3600 + 100))  # window restarts

    def test_recovery_signaled_and_down_since_kept_for_caller(self):
        s = mod.WatchdogState(fails_to_alert=2)
        s.record(False, 100)
        s.record(False, 160)
        self.assertEqual(s.record(True, 500), 'recovered')
        self.assertEqual(s.down_since, 100)  # caller reads it for the message
        s.clear_outage()
        self.assertIsNone(s.down_since)

    def test_blip_does_not_pollute_next_streak(self):
        s = mod.WatchdogState(fails_to_alert=3)
        s.record(False, 100)              # blip: 1 fail
        self.assertIsNone(s.record(True, 160))
        self.assertIsNone(s.down_since)   # blip timestamp dropped
        s.record(False, 1000)
        s.record(False, 1060)
        self.assertEqual(s.record(False, 1120), 'down')
        self.assertEqual(s.down_since, 1000)  # not 100

    def test_success_resets_fail_count(self):
        s = mod.WatchdogState(fails_to_alert=3)
        s.record(False, 0)
        s.record(False, 60)
        s.record(True, 120)
        s.record(False, 180)
        s.record(False, 240)
        self.assertEqual(s.record(False, 300), 'down')  # needed 3 fresh fails


class TestProbeState(unittest.TestCase):
    def test_transition_only_emission(self):
        s = mod.ProbeState(fails_to_emit=2)
        self.assertIsNone(s.record('u', False, 0))
        self.assertEqual(s.record('u', False, 600), 'down')
        self.assertIsNone(s.record('u', False, 1200))   # stays down silently
        self.assertEqual(s.record('u', True, 1800), 'recovered')
        self.assertIsNone(s.record('u', True, 2400))    # stays up silently

    def test_keys_are_independent(self):
        s = mod.ProbeState(fails_to_emit=2)
        s.record('a', False, 0)
        s.record('b', True, 0)
        self.assertEqual(s.record('a', False, 600), 'down')
        self.assertIsNone(s.record('b', True, 600))

    def test_blip_clears_down_since(self):
        s = mod.ProbeState(fails_to_emit=2)
        s.record('u', False, 0)
        s.record('u', True, 600)
        self.assertNotIn('u', s.down_since)
        s.record('u', False, 1200)
        self.assertEqual(s.down_since['u'], 1200)


class TestExtractDeployUrls(unittest.TestCase):
    def test_repo_meta_preferred_and_fallback(self):
        payload = {'projects': [
            {'slug': 'strummy', 'repo_meta': {'deploy': {'url': 'strummy.vercel.app'}},
             'raw_frontmatter': {'deployed': 'old.example.com'}},
            {'slug': 'inborr', 'repo_meta': {}, 'raw_frontmatter': {'deployed': 'inborr.pl'}},
        ]}
        self.assertEqual(mod.extract_deploy_urls(payload), {
            'strummy': 'strummy.vercel.app',
            'inborr': 'inborr.pl',
        })

    def test_skips_projects_without_urls_and_malformed_rows(self):
        payload = {'projects': [
            {'slug': 'no-deploy', 'repo_meta': {}, 'raw_frontmatter': {}},
            {'slug': 'null-meta', 'repo_meta': None, 'raw_frontmatter': None},
            {'slug': 'non-string', 'raw_frontmatter': {'deployed': 123}},
            {'no_slug_at_all': True},
            'not-even-a-dict',
        ]}
        self.assertEqual(mod.extract_deploy_urls(payload), {})

    def test_non_dict_payload(self):
        self.assertEqual(mod.extract_deploy_urls(None), {})
        self.assertEqual(mod.extract_deploy_urls(['x']), {})


class TestCheckHealth(unittest.TestCase):
    @patch('urllib.request.urlopen')
    def test_ok_true(self, mock_urlopen):
        cm = MagicMock()
        cm.__enter__.return_value.status = 200
        cm.__enter__.return_value.read.return_value = json.dumps({'ok': True}).encode()
        mock_urlopen.return_value = cm
        self.assertTrue(mod.check_health())

    @patch('urllib.request.urlopen')
    def test_ok_false_body(self, mock_urlopen):
        cm = MagicMock()
        cm.__enter__.return_value.status = 200
        cm.__enter__.return_value.read.return_value = json.dumps({'ok': False}).encode()
        mock_urlopen.return_value = cm
        self.assertFalse(mod.check_health())

    @patch('urllib.request.urlopen')
    def test_503(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError('http://x', 503, 'Unavailable', {}, io.BytesIO(b''))
        self.assertFalse(mod.check_health())

    @patch('urllib.request.urlopen')
    def test_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError('no route to host')
        self.assertFalse(mod.check_health())


class TestSendAlert(unittest.TestCase):
    def test_dry_run_prints_and_succeeds(self):
        with patch.object(mod, 'ALERT_DRY_RUN', True), patch('sys.stdout', new=io.StringIO()) as out:
            self.assertTrue(mod.send_alert('subj', 'body'))
            self.assertIn('subj', out.getvalue())

    def test_missing_password_file_returns_false(self):
        with patch.object(mod, 'ALERT_DRY_RUN', False), \
             patch.object(mod, 'SMTP_PASS_FILE', Path('/nonexistent/smtp.pass')), \
             patch('sys.stderr', new=io.StringIO()):
            self.assertFalse(mod.send_alert('subj', 'body'))

    @patch('smtplib.SMTP')
    def test_smtp_failure_returns_false_never_raises(self, mock_smtp):
        mock_smtp.side_effect = OSError('connection refused')
        with patch.object(mod, 'ALERT_DRY_RUN', False), \
             patch.object(mod.Path, 'read_text', return_value='app-password'), \
             patch('sys.stderr', new=io.StringIO()):
            self.assertFalse(mod.send_alert('subj', 'body'))

    @patch('smtplib.SMTP')
    def test_sends_message_with_subject(self, mock_smtp):
        smtp_instance = mock_smtp.return_value.__enter__.return_value
        with patch.object(mod, 'ALERT_DRY_RUN', False), \
             patch.object(mod, 'ALERT_TO', 'p@example.com'), \
             patch.object(mod, 'ALERT_FROM', 'p@example.com'), \
             patch.object(mod.Path, 'read_text', return_value='app-password'):
            self.assertTrue(mod.send_alert('[home-ops] ingest DOWN (from rpi)', 'body text'))
        smtp_instance.starttls.assert_called_once()
        smtp_instance.login.assert_called_once()
        sent = smtp_instance.send_message.call_args[0][0]
        self.assertEqual(sent['Subject'], '[home-ops] ingest DOWN (from rpi)')


class TestFmtDuration(unittest.TestCase):
    def test_minutes_and_hours(self):
        self.assertEqual(mod._fmt_duration(65), '1m05s')
        self.assertEqual(mod._fmt_duration(3665), '1h01m')


if __name__ == '__main__':
    unittest.main()
