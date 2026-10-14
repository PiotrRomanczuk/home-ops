"""Unit tests for render-digest.py (pure JSON model → HTML)."""
from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / 'render-digest.py'
_spec = importlib.util.spec_from_file_location('render_digest', _PATH)
rd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rd)

NOW = datetime(2026, 10, 14, 5, 0, tzinfo=timezone.utc)  # 07:00 Warsaw


def model(**over):
    m = {
        'mode': 'morning',
        'verdict': '2 things need you and 1 decision waits.',
        'hosts': [
            {'host': 'rpi', 'status': 'ok', 'last_metric_ts': '2026-10-14T04:59:30Z', 'cpu_pct': 1, 'mem_pct': 16, 'disk_pct': 67},
            {'host': 'win10', 'status': 'warn', 'last_metric_ts': '2026-10-14T04:59:30Z', 'cpu_pct': 4, 'mem_pct': 23, 'disk_pct': 95},
            {'host': 'elitedesk', 'status': 'off', 'last_metric_ts': None, 'cpu_pct': None, 'mem_pct': None, 'disk_pct': None},
        ],
        'problems': [{
            'source': 'agent:planner-sync', 'host': 'elitedesk', 'level': 'error', 'pattern': 'sync failed',
            'sample': 'sync failed', 'n_24h': 1438, 'n_patterns': 3, 'first_seen': '2026-10-10T22:48:43Z',
        }],
        'muted_problems': 1,
        'sites': [],
        'focus': 'Ansible-ize deploys',
        'next': ['rpi-sentinel fire drill'],
        'cards': [
            {'routine': 'seo-analyse', 'status': 'ok', 'headline': 'Traffic flat, 2 hypotheses added',
             'items': [{'text': 'H3: district pages', 'url': 'https://example.com/h3'}],
             'metric': {'label': 'clicks 7d', 'value': 12, 'delta': 3}, 'ran_at': '2026-10-14T04:30:00Z',
             'is_fresh': True, 'runs_7d': 7, 'runs_prev_7d': 5},
            {'routine': 'job-tracker', 'status': 'ok', 'headline': 'refresh OK', 'items': [], 'metric': None,
             'ran_at': '2026-08-03T04:30:00Z', 'is_fresh': False, 'runs_7d': 0, 'runs_prev_7d': 0},
        ],
        'acceptance': [{'routine': 'seo-analyse', 'answered': 4, 'accepted': 3, 'expired': 0}],
        'decisions': [{
            'id': 9, 'routine': 'seo-improve', 'question': 'Merge PR #52 <title>?', 'context_url': 'https://github.com/x/pull/52',
            'expires_at': '2026-10-16T05:00:00Z', 'options': [{'key': 'yes', 'label': 'Merge'}, {'key': 'no', 'label': 'Skip'}],
            'links': {'yes': 'http://c/d/9/yes/1/s', 'no': 'http://c/d/9/no/1/s'},
        }],
        'narrative': None,
        'board_url': 'http://elitedesk:64421/#tab=decisions',
    }
    m.update(over)
    return m


class RenderDigestTest(unittest.TestCase):
    def test_decision_buttons_carry_signed_links_and_escape_question(self):
        html = rd.render(model(), NOW)
        self.assertIn('href="http://c/d/9/yes/1/s"', html)
        self.assertIn('>Merge<', html)
        self.assertIn('expires Fri 07:00', html)  # a future deadline, not 'just now'
        self.assertIn('Merge PR #52 &lt;title&gt;?', html)
        self.assertNotIn('<title>?', html)

    def test_problem_shows_count_and_since(self):
        html = rd.render(model(), NOW)
        self.assertIn('1438× in 24 h · 2 other messages', html)
        self.assertIn('since Sun 00:48', html)  # 22:48 UTC Sat 10 Oct = 00:48 Sun in Warsaw
        self.assertIn('1 known-noise pattern hidden', html)

    def test_hosts_flag_full_disk_and_missing_metrics(self):
        html = rd.render(model(), NOW)
        self.assertIn('win10 disk is 95% full', html)
        self.assertIn('Logs only, no metrics', html)

    def test_stale_card_reads_as_did_not_run(self):
        html = rd.render(model(), NOW)
        self.assertIn('job-tracker did not run', html)
        self.assertNotIn('refresh OK', html)

    def test_fresh_card_shows_metric_delta_trend_and_acceptance(self):
        html = rd.render(model(), NOW)
        self.assertIn('seo-analyse: Traffic flat', html)
        self.assertIn('+3', html)
        self.assertIn('7 runs this week, 5 last', html)
        self.assertIn('accepted 3 of 4 proposals', html)

    def test_lower_is_better_delta_is_green(self):
        card = dict(model()['cards'][0], metric={'label': 'crawl findings', 'value': 19, 'delta': -2, 'lower_is_better': True},
                    runs_7d=1, runs_prev_7d=0)
        html = rd.render(model(cards=[card]), NOW)
        self.assertIn('color:#34c759">-2', html)
        self.assertIn('1 run this week', html)

    def test_quiet_day_omits_empty_sections(self):
        html = rd.render(model(problems=[], decisions=[], muted_problems=0, cards=[], hosts=[], focus=None, next=[],
                               verdict='All quiet. Nothing needs you.'), NOW)
        self.assertIn('All quiet. Nothing needs you.', html)
        for title in ('Needs you', 'Needs attention', 'Routines', 'Today'):
            self.assertNotIn(f'>{title}<', html)


if __name__ == '__main__':
    unittest.main()
