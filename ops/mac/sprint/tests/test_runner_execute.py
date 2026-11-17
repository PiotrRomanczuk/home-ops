"""Tests for runner.execute — the wiring between claude_run.run, outcomes.classify and sprint_tasks.finish — on real
runs.jsonl rows (fixtures/runs-2026-11.jsonl). classify and finish have their own tests; these catch execute
dropping what classify decided (the 14–15.11 failure: a session limit filed as a retry on a stronger model).

Run:
    python3 -m unittest discover -s ops/mac/sprint/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import runner  # noqa: E402
import sprint_tasks as q  # noqa: E402

ROWS = {r['fixture']: r for r in map(json.loads, (Path(__file__).parent / 'fixtures' / 'runs-2026-11.jsonl').read_text().splitlines())}


def row_run(fixture: str, tid: str, **change) -> dict:
    """The fixture row as claude_run.run returns it, as if it ended just now."""
    row = ROWS[fixture]
    return {'id': tid, 'model': row['model'], 'rc': row['rc'], 'stderr': row['stderr'], 'started': time.time() - row['seconds'],
            'seconds': row['seconds'], 'resumed': False, 'res': dict(row['res']), **change}


class ExecuteTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / 'state'
        vault = Path(tmp.name) / 'vault'
        (vault / '3-Zasoby' / 'analysis').mkdir(parents=True)
        q.setup(self.state)
        for name, value in (('STATE', self.state), ('paused_until', 0.0)):
            self.addCleanup(setattr, runner, name, getattr(runner, name))
            setattr(runner, name, value)
        self.addCleanup(setattr, runner.budget, 'limits', runner.budget.limits)
        runner.budget.limits = {}
        for patch in (mock.patch.object(runner.journal, 'VAULT', vault), mock.patch.object(runner.budget, 'refresh'),
                      mock.patch.object(runner.lifecycle, 'notify'), mock.patch.object(q, 'MIN_AGE', 0)):
            patch.start()
            self.addCleanup(patch.stop)

    def execute(self, run: dict, _where: str = 'queue', **meta) -> dict:
        tid = run['id']
        q.write(self.state / 'queue' / f'{tid}.md', {'id': tid, 'model': run['model'], **meta, 'body': f'do {tid}'})
        task = q.claim(self.state)
        with mock.patch.object(runner.claude_run, 'run', return_value=run) as called:
            runner.execute(task, config.load(self.state))
        self.assertEqual(called.call_args.kwargs['local_minutes'], config.DEFAULTS['local']['max_minutes'])
        self.assertFalse((self.state / 'running' / f'{tid}.md').exists())
        return q.parse(self.state / _where / f'{tid}.md')

    def test_a_session_limit_requeues_on_the_same_model_and_pauses_every_worker(self):
        before = time.time()
        task = self.execute(row_run('limit-450am', 'lim'), kind='code')
        self.assertEqual((task['model'], task['attempts']), ('sonnet', 0))
        self.assertEqual(task['resume'], ROWS['limit-450am']['res']['session_id'])
        not_before = datetime.fromisoformat(task['not_before'])
        self.assertGreater(not_before.timestamp(), before)
        self.assertEqual((not_before.astimezone(runner.outcomes.ZoneInfo('Europe/Warsaw')).hour, not_before.minute), (4, 50))
        self.assertEqual(runner.paused_until, not_before.timestamp())
        self.assertIsNotNone(runner.claude_reason({'max_minutes': 1}, config.load(self.state)['claude']))

    def test_a_models_own_limit_holds_only_that_task(self):
        reset = datetime.now(timezone.utc) + timedelta(days=3)
        runner.budget.limits = {'session': {'percent': 20.0, 'resets_at': reset}, 'weekly': {'percent': 50.0, 'resets_at': reset},
                                'fable': {'percent': 100.0, 'resets_at': reset}}
        run = row_run('limit-pm', 'fab', model='fable')
        run['res']['result'] = "You've hit your limit"
        task = self.execute(run)
        self.assertEqual(runner.paused_until, 0.0)
        self.assertEqual((task['model'], task['attempts']), ('fable', 0))
        self.assertEqual(datetime.fromisoformat(task['not_before']), reset.replace(microsecond=0))

    def test_a_claude_timeout_is_an_interruption_on_the_same_model(self):
        task = self.execute(row_run('timeout-local', 'slow', model='sonnet'))
        self.assertEqual((task['model'], task['attempts'], task['interrupts']), ('sonnet', 0, 1))
        self.assertGreater(datetime.fromisoformat(task['not_before']).timestamp(), time.time())
        self.assertEqual(runner.paused_until, 0.0)

    def test_a_lost_session_starts_afresh_on_the_same_model(self):
        run = row_run('done', 'lost', rc=1, resumed=True)
        run['res'].update(is_error=True, result='No conversation found with session ID: 00000000-0000-4000-8000-000000000001')
        task = self.execute(run, resume='00000000-0000-4000-8000-000000000001', kind='vault')
        self.assertEqual((task['model'], task['attempts'], task['interrupts']), ('sonnet', 0, 1))
        self.assertNotIn('resume', task)
        self.assertNotIn('not_before', task)

    def failing(self, tid: str) -> dict:
        run = row_run('done', tid, rc=1)
        run['res'].update(is_error=True, result='lint failed')
        return run

    def test_a_failed_code_task_on_sonnet_retries_on_sonnet(self):
        task = self.execute(self.failing('code'), kind='code')  # outcomes.NO_ESCALATION: meta['escalate'] is False
        self.assertEqual((task['model'], task['attempts']), ('sonnet', 1))

    def test_a_failed_vault_task_on_sonnet_retries_on_a_stronger_model(self):
        task = self.execute(self.failing('vault'), kind='vault')
        self.assertEqual((task['model'], task['attempts']), (q.stronger('sonnet'), 1))
        self.assertNotEqual(task['model'], 'sonnet')

    def test_a_bench_answer_is_saved_by_the_runner_and_the_task_is_done(self):
        run = row_run('done', 'bn', rc=0)
        run['res'].update(is_error=False, result='odpowiedź modelu')
        self.execute(run, kind='bench', _where='done')
        text = (self.state / 'results' / 'bn.md').read_text()
        self.assertIn('# bn — wynik bench (zapisany przez runner)', text)
        self.assertIn('odpowiedź modelu', text)

    def test_a_bench_run_with_an_empty_result_retries(self):
        run = row_run('done', 'be', rc=0)
        run['res'].update(is_error=False, result='  ')
        task = self.execute(run, kind='bench')
        self.assertEqual(task['attempts'], 1)
        self.assertFalse((self.state / 'results' / 'be.md').exists())

    def test_a_code_task_that_wrote_no_file_still_retries(self):
        run = row_run('done', 'cn', rc=0)
        run['res'].update(is_error=False, result='gotowe')
        task = self.execute(run, kind='code')
        self.assertEqual(task['attempts'], 1)
        self.assertFalse((self.state / 'results' / 'cn.md').exists())


if __name__ == '__main__':
    unittest.main()
