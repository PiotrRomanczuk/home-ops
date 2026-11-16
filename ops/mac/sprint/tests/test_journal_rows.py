"""Tests for journal.record: the rows of STATE/logs/runs.jsonl.

Run:
    python3 -m unittest discover -s ops/mac/sprint/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import journal  # noqa: E402


class RecordTest(unittest.TestCase):
    def test_row_has_an_offset_the_task_frontmatter_and_the_whole_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, vault = Path(tmp) / 'state', Path(tmp) / 'vault'
            (state / 'logs').mkdir(parents=True)
            (vault / '3-Zasoby' / 'analysis').mkdir(parents=True)
            task = {'id': 't', 'project': 'p', 'kind': 'code', 'model': 'sonnet', 'attempts': 0, 'interrupts': 1,
                    'not_before': '2026-11-16T04:50:00+01:00', 'resume': 'sess-1', 'body': 'SECRET PROMPT', 'path': Path('/x')}
            run = {'id': 't', 'model': 'sonnet', 'rc': 143, 'stderr': 'e' * 50_000, 'started': 1.0, 'seconds': 70,
                   'resumed': False, 'res': {'result': 'x', 'total_cost_usd': 0.5}}
            with mock.patch.object(journal, 'VAULT', vault):
                journal.record(state, task, run, 'interrupted', date(2026, 11, 16), threading.Lock())
            (row,) = [json.loads(line) for line in (state / 'logs' / 'runs.jsonl').read_text().splitlines()]
        self.assertRegex(row['ts'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$')
        self.assertEqual(row['task'], {'id': 't', 'project': 'p', 'kind': 'code', 'model': 'sonnet', 'attempts': 0,
                                       'interrupts': 1, 'not_before': '2026-11-16T04:50:00+01:00', 'resume': 'sess-1'})
        self.assertNotIn('SECRET PROMPT', json.dumps(row))
        self.assertEqual((row['outcome'], row['rc'], len(row['stderr'])), ('interrupted', 143, 50_000))

    def test_local_runs_today_still_reads_rows_with_an_offset_and_a_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / 'logs').mkdir()
            now = date.today().isoformat()
            row = {'ts': f'{now}T01:00:00+01:00', 'outcome': 'done', 'task': {'model': 'local:qwen'}, 'model': 'local:qwen'}
            (state / 'logs' / 'runs.jsonl').write_text(json.dumps(row) + '\n')
            self.assertEqual(journal.local_runs_today(state), 1)


if __name__ == '__main__':
    unittest.main()
