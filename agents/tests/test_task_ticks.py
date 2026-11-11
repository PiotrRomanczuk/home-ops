"""Tests for task_ticks — vault Now/Next/Later diffs → tasks_done/tasks_added.

Run:
    python3 -m unittest discover -s agents/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location('task_ticks', REPO_ROOT / 'agents' / 'elitedesk' / 'task_ticks.py')
assert _spec is not None and _spec.loader is not None
tt = importlib.util.module_from_spec(_spec)
sys.modules['task_ticks'] = tt
_spec.loader.exec_module(tt)


def rec(slug: str, now: str = '', nxt: str = '', later: str = '') -> dict:
    return {'slug': slug, 'now_md': now, 'next_md': nxt, 'later_md': later}


class KeyTest(unittest.TestCase):
    def test_key_ignores_date_marks_and_suffix_after_60_chars(self) -> None:
        a = tt.task_key('2026-11-08 **Zakładka „Postęp”** (etapy 3–4 tego samego planu): tabela `project_signals`')
        b = tt.task_key('Zakładka „Postęp” (etapy 3–4 tego samego planu): tabela project_signals → zrobione w PR #71')
        self.assertEqual(a, b)
        self.assertEqual(len(a), tt.KEY_LEN)


class DiffTest(unittest.TestCase):
    def test_first_sight_is_a_baseline(self) -> None:
        cur = tt.snapshot([rec('home-ops', now='- [ ] a\n- [x] b')])
        self.assertEqual(tt.diff({}, cur), {})

    def test_ticked_added_moved_and_removed(self) -> None:
        prev = tt.snapshot([rec('home-ops', now='- [ ] 2026-11-01 deploy runner\n- [ ] fix mail\n- [ ] old idea')])
        cur = tt.snapshot([rec('home-ops',
                               now='- [x] 2026-11-01 deploy runner\n- [ ] new task',
                               nxt='- [ ] fix mail',            # moved, still open
                               later='- [x] born done')])       # added already ticked
        self.assertEqual(tt.diff(prev, cur), {'home-ops': (2, 1)})  # 'old idea' removed: not counted

    def test_unticking_and_unchanged_count_nothing(self) -> None:
        prev = tt.snapshot([rec('s', now='- [x] a\n- [ ] b')])
        cur = tt.snapshot([rec('s', now='- [ ] a\n- [ ] b')])
        self.assertEqual(tt.diff(prev, cur), {})

    def test_rows(self) -> None:
        self.assertEqual(tt.rows_for({'s': (2, 0)}, '2026-11-08'),
                         [{'project_slug': 's', 'day': '2026-11-08', 'signal': 'tasks_done', 'n': 2}])


NOTE = '''---
project: home-ops
status: hot
---

# home-ops

## Now

- [x] 2026-11-08 Serwer tab
- [ ] Postęp tab

## Pain points

- [ ] not a task for Postęp

## Next — Session 4

- [ ] github-repo-sync deploy

### sub heading stays in Next
- [x] done under a sub heading

## Notes
- [x] old note checkbox
'''


class NoteTest(unittest.TestCase):
    def test_note_tasks_reads_only_now_next_later(self) -> None:
        self.assertEqual(tt.note_tasks(NOTE), {
            'serwer tab': True, 'postęp tab': False, 'github-repo-sync deploy': False, 'done under a sub heading': True,
        })

    def test_note_slug(self) -> None:
        self.assertEqual(tt.note_slug(NOTE, 'whatever'), 'home-ops')
        self.assertEqual(tt.note_slug('# Strummy\n- [ ] x', 'Strummy'), 'Strummy')


class TrackerTest(unittest.TestCase):
    def test_commit_persists_and_failed_post_retries(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'ticks.json'
            t = tt.TickTracker(path)
            rows, snap = t.pending([rec('s', now='- [ ] a')], '2026-11-08')
            self.assertEqual(rows, [])
            t.commit(snap)
            again = tt.TickTracker(path)  # survives a restart
            rows, snap = again.pending([rec('s', now='- [x] a')], '2026-11-08')
            self.assertEqual(rows[0]['signal'], 'tasks_done')
            # POST failed → no commit → the same tick is offered again
            rows2, _ = again.pending([rec('s', now='- [x] a')], '2026-11-08')
            self.assertEqual(rows2, rows)


if __name__ == '__main__':
    unittest.main()
