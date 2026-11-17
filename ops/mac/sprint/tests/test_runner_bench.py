"""runner.execute for `kind: bench`: the runner saves the answer (bench_result) and the task ends in done/; a failed run
saves nothing. Reuses the fixture and the execute helper of test_runner_execute.

Run:
    python3 -m unittest discover -s ops/mac/sprint/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_runner_execute as base  # noqa: E402
from test_runner_execute import row_run  # noqa: E402


class BenchExecuteTest(unittest.TestCase):
    setUp = base.ExecuteTest.setUp
    execute = base.ExecuteTest.execute

    def test_a_bench_answer_is_saved_by_the_runner_and_the_task_is_done(self):
        run = row_run('done', 'bn', rc=0)
        run['res'].update(is_error=False, result='odpowiedź modelu')
        self.execute(run, kind='bench', _where='done')
        text = (self.state / 'results' / 'bn.md').read_text()
        self.assertIn('# bn — wynik bench (zapisany przez runner)', text)
        self.assertIn('odpowiedź modelu', text)
        self.assertTrue((self.state / 'done' / 'bn.md').exists())

    def failed_bench(self, tid: str, rc: int, is_error: bool) -> dict:
        run = row_run('done', tid, rc=rc)
        run['res'].update(is_error=is_error, result='błąd')
        task = self.execute(run, kind='bench')
        self.assertFalse((self.state / 'results' / f'{tid}.md').exists())
        return task

    def test_a_bench_run_with_a_bad_rc_and_is_error_saves_no_result_and_retries(self):
        self.assertEqual(self.failed_bench('bf', 1, True)['attempts'], 1)

    def test_a_bench_run_with_only_a_bad_rc_saves_no_result(self):  # kills the mutant without the rc condition
        self.assertEqual(self.failed_bench('bc', 1, False)['attempts'], 1)

    def test_a_bench_run_with_only_is_error_saves_no_result(self):  # kills the mutant without the is_error condition
        self.failed_bench('be2', 0, True)

    def test_a_bench_run_with_an_empty_result_retries(self):
        run = row_run('done', 'be', rc=0)
        run['res'].update(is_error=False, result='  ')
        task = self.execute(run, kind='bench')
        self.assertEqual(task['attempts'], 1)
        self.assertFalse((self.state / 'results' / 'be.md').exists())


if __name__ == '__main__':
    unittest.main()
