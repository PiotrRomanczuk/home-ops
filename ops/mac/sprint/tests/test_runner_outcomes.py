"""Tests for outcomes.py — what a run means for its task — on real runs.jsonl rows (fixtures/runs-2026-11.jsonl:
14–16.11, session ids replaced, task ids and answers removed).

Run:
    python3 -m unittest discover -s ops/mac/sprint/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import claude_run  # noqa: E402
import outcomes as o  # noqa: E402
import sprint_tasks as q  # noqa: E402

WAW = ZoneInfo('Europe/Warsaw')
ROWS = {r['fixture']: r for r in map(json.loads, (Path(__file__).parent / 'fixtures' / 'runs-2026-11.jsonl').read_text().splitlines())}


def at(fixture: str) -> datetime:
    """When that run ended (runs.jsonl `ts` is Warsaw local time)."""
    return datetime.fromisoformat(ROWS[fixture]['ts']).replace(tzinfo=WAW)


def run(fixture: str, **change) -> dict:
    row = ROWS[fixture]
    started = at(fixture).timestamp() - row['seconds']
    return {'id': 'task', 'model': row['model'], 'rc': row['rc'], 'stderr': row['stderr'], 'started': started,
            'seconds': row['seconds'], 'res': dict(row['res']), **change}


def waw(day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=WAW)


class LimitTest(unittest.TestCase):
    def test_session_limit_waits_for_the_hour_in_the_message_without_usage(self):
        for fixture, reset in (('limit-1250am', waw(16, 0, 50)), ('limit-450am', waw(15, 4, 50)), ('limit-pm', waw(14, 23, 50))):
            outcome, meta = o.classify(run(fixture), at(fixture), kind='code', limits={})
            self.assertEqual(outcome, 'limit', fixture)
            self.assertEqual(datetime.fromisoformat(meta['set']['not_before']), reset, fixture)
            self.assertEqual((meta['scope'], meta['pause_until']), ('session', reset), fixture)
            self.assertTrue(meta['set']['resume'].startswith('00000000-'), fixture)

    def test_reset_hour_already_past_means_tomorrow_unless_it_is_minutes_ago(self):
        text = ROWS['limit-450am']['res']['result']
        self.assertEqual(o.reset_at(text, waw(15, 5, 30)), waw(16, 4, 50))
        now = waw(15, 4, 50) + timedelta(seconds=20)  # the message rounds 04:50:00.4 down
        self.assertEqual(o.reset_at(text, now), now + timedelta(minutes=5))
        self.assertEqual(o.reset_at("resets Nov 23, 5pm (Europe/Warsaw)", waw(17, 9, 0)), waw(23, 17, 0))
        self.assertIsNone(o.reset_at('resets 4:50am (Mars/Olympus)', waw(15, 1, 0)))

    def test_429_without_an_hour_backs_off_or_uses_usage(self):
        now = waw(16, 0, 12)
        r = run('limit-1250am')
        r['res']['result'] = "You've hit your limit"
        self.assertTrue(o.wants_usage(r))
        outcome, meta = o.classify(r, now, limits={})
        self.assertEqual((outcome, meta['scope'], meta['pause_until']), ('limit', 'unknown', None))
        self.assertEqual(meta['set']['not_before'], (now + o.BACKOFF).isoformat(timespec='seconds'))
        reset = waw(16, 0, 50).astimezone(timezone.utc)
        session = {'session': {'percent': 100.0, 'resets_at': reset}, 'weekly': {'percent': 40.0, 'resets_at': reset}}
        outcome, meta = o.classify(r, now, limits=session)
        self.assertEqual((outcome, meta['scope'], meta['pause_until']), ('limit', 'session', reset))

    def test_a_models_own_limit_holds_only_that_task(self):
        now, reset = waw(17, 9, 0), waw(23, 17, 0).astimezone(timezone.utc)
        r = run('limit-pm', model='fable')
        r['res']['result'] = "You've hit your limit"
        fable = {'session': {'percent': 20.0, 'resets_at': reset}, 'weekly': {'percent': 60.0, 'resets_at': reset},
                 'fable': {'percent': 100.0, 'resets_at': reset}}
        outcome, meta = o.classify(r, now, limits=fable)
        self.assertEqual((outcome, meta['scope'], meta['pause_until']), ('limit', 'fable', None))
        self.assertEqual(datetime.fromisoformat(meta['set']['not_before']), reset)

    def test_the_word_limit_alone_is_an_ordinary_failure(self):
        r = run('done', rc=1)
        r['res'].update(is_error=True, result='CI failed: GitHub API rate limit in the test step')
        self.assertFalse(o.limit_until(r, at('done'), {}))
        self.assertEqual(o.classify(r, at('done'), kind='vault')[0], 'retry')


class InterruptTest(unittest.TestCase):
    def test_sigterm_and_claude_timeout_requeue_without_escalation(self):
        now = at('sigterm')
        for r in (run('sigterm'), run('sigterm', rc=137), run('sigterm', rc=-15), run('timeout-local', model='sonnet')):
            outcome, meta = o.classify(r, now, kind='vault')
            self.assertEqual(outcome, 'interrupted', r['rc'])
            self.assertNotIn('escalate', meta)
            self.assertEqual(meta['set']['not_before'], (now + o.REQUEUE_IN).isoformat(timespec='seconds'))

    def test_local_model_timeout_is_that_model_failing(self):
        outcome, meta = o.classify(run('timeout-local'), at('timeout-local'), kind='bench')
        self.assertEqual((outcome, meta['escalate']), ('retry', True))


class DoneTest(unittest.TestCase):
    def test_done_needs_the_result_file_written_during_the_run(self):
        r, now = run('done'), at('done')
        self.assertEqual(o.classify(r, now, kind='vault', result_mtime=r['started'] + 200)[0], 'done')
        self.assertEqual(o.classify(r, now, kind='vault', result_mtime=None)[0], 'retry')
        self.assertEqual(o.classify(r, now, kind='vault', result_mtime=r['started'] - 3600)[0], 'retry')

    def test_retry_escalates_except_pr_fix_ci_code_on_claude(self):
        r = run('done', rc=1)
        r['res'].update(is_error=True, result='lint failed')
        self.assertTrue(o.classify(r, at('done'), kind='vault')[1]['escalate'])
        outcome, meta = o.classify(r, at('done'), kind='pr-fix')
        self.assertEqual((outcome, meta['escalate'], meta['note']), ('retry', False, 'lint failed'))


class TaskFileTest(unittest.TestCase):
    """classify → finish → eligible → command, the way runner.worker strings them together."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        q.setup(self.state)
        q.write(self.state / 'queue' / 't.md', {'id': 't', 'model': 'sonnet', 'kind': 'code', 'body': 'zrób t'})
        self.task = q.claim(self.state)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def finish(self, outcome: str, meta: dict) -> dict:
        self.task.update(meta['set'])
        q.finish(self.state, self.task, outcome, meta.get('escalate', True))
        return q.parse(self.state / 'queue' / 't.md')

    def test_limit_keeps_model_and_attempts_waits_and_resumes(self):
        now = at('limit-1250am')
        t = self.finish(*o.classify(run('limit-1250am'), now, kind='code', limits={}))
        self.assertEqual((t['model'], t['attempts'], t['interrupts']), ('sonnet', 0, 0))
        self.assertEqual(q.eligible(self.state, now), [])
        self.assertEqual([x['id'] for x in q.eligible(self.state, waw(16, 0, 51))], ['t'])
        cmd = claude_run.command('claude', t, 'sonnet', self.state, self.state)
        self.assertEqual(cmd[cmd.index('--resume') + 1], t['resume'])
        self.assertTrue(cmd[2].startswith('Kontynuuj zadanie t od miejsca przerwania'))

if __name__ == '__main__':
    unittest.main()
