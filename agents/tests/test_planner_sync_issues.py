"""planner-sync wiring of the GitHub Issues pilot: which notes get rendered,
and what a Dziś toggle does on a generated vs a manual line. GitHub and git
are stubbed — no network, no repo.

Run:
    python3 -m unittest discover -s agents/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_planner_sync():
    os.environ.setdefault('INGEST_URL', 'http://x/api/ingest')
    os.environ.setdefault('INGEST_TOKEN', 'y')
    spec = importlib.util.spec_from_file_location('planner_sync_issues',
                                                  REPO_ROOT / 'agents' / 'elitedesk' / 'planner-sync.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ps = _load_planner_sync()

ISSUES = [{'number': 1, 'title': 'Generated', 'labels': [{'name': 'plan/now'}, {'name': 'klasa/fokus'}],
           'body': '', 'created_at': '2026-11-14T00:00:00Z', 'html_url': 'https://github.com/o/r/issues/1'}]
OPTED_IN = '---\nstatus: hot\nproject: p\nzadania: github\nrepo: "o/r"\n---\n# P\n\n## Now\n\n- [ ] manual line\n'
PLAIN = '---\nstatus: hot\nproject: q\nrepo: "q"\n---\n# Q\n\n## Now\n\n- [ ] untouched\n'


class IssuesWiringTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / '1-Projekty').mkdir()
        self.p = root / '1-Projekty' / 'p.md'
        self.q = root / '1-Projekty' / 'q.md'
        self.p.write_text(OPTED_IN, encoding='utf-8')
        self.q.write_text(PLAIN, encoding='utf-8')
        self.saved = {k: getattr(ps, k) for k in
                      ('PLANNER_DIR', 'fetch_open_issues', 'set_issue_state', '_run_git', 'post_log')}
        self.fetched: list[str] = []
        self.closed: list[tuple] = []
        ps.PLANNER_DIR = root
        ps.fetch_open_issues = lambda repo: self.fetched.append(repo) or ISSUES
        ps.set_issue_state = lambda repo, n, done: self.closed.append((repo, n, done)) or True
        ps._run_git = lambda *a: subprocess.CompletedProcess(a, 0, '', '')
        ps.post_log = lambda *a, **k: None
        ps._issues_due = 0.0
        ps._board_conflict_warned.clear()
        ps._orphan_warned.clear()

    def tearDown(self) -> None:
        for k, v in self.saved.items():
            setattr(ps, k, v)
        self.tmp.cleanup()

    def test_renders_only_opted_in_notes_and_respects_interval(self) -> None:
        ps.issues_sync_once()
        self.assertEqual(self.fetched, ['o/r'])
        self.assertIn('**Generated** — [#1](https://github.com/o/r/issues/1)', self.p.read_text())
        self.assertIn('- [ ] manual line', self.p.read_text())
        self.assertEqual(self.q.read_text(), PLAIN)
        ps.issues_sync_once()  # within ISSUES_INTERVAL: no second fetch
        self.assertEqual(self.fetched, ['o/r'])

    def test_toggle_on_generated_line_closes_issue_and_forces_rerender(self) -> None:
        ps.issues_sync_once()
        before = self.p.read_text()
        text = next(line for line in before.split('\n') if '[#1]' in line)[len('- [ ] '):]
        status, err = ps._apply_one_toggle({'slug': 'p', 'section': 'now', 'idx': 0, 'done': True, 'text': text})
        self.assertEqual((status, err), ('applied', None))
        self.assertEqual(self.closed, [('o/r', 1, True)])
        self.assertEqual(self.p.read_text(), before)
        self.assertEqual(ps._issues_due, 0.0)

    def test_toggle_on_manual_line_still_edits_markdown(self) -> None:
        ps.issues_sync_once()
        status, _ = ps._apply_one_toggle({'slug': 'p', 'section': 'now', 'idx': 1, 'done': True,
                                          'text': 'manual line'})
        self.assertEqual(status, 'applied')
        self.assertEqual(self.closed, [])
        self.assertIn('- [x] manual line', self.p.read_text())

    def test_fetch_failure_leaves_file_and_git_untouched(self) -> None:
        git_calls: list[tuple] = []
        ps.fetch_open_issues = lambda repo: None
        ps._run_git = lambda *a: git_calls.append(a) or subprocess.CompletedProcess(a, 0, '', '')
        before = self.p.read_text()
        ps.issues_sync_once()
        self.assertEqual(self.p.read_text(), before)
        self.assertEqual(git_calls, [])

    def test_edit_pulled_in_before_write_is_kept(self) -> None:
        """Obsidian edit lands between the tick's read and the pre-push pull."""
        def git(*a):
            if a[0] == 'pull':
                with self.p.open('a', encoding='utf-8') as f:
                    f.write('- [ ] added in Obsidian\n')
            return subprocess.CompletedProcess(a, 0, '', '')
        ps._run_git = git
        ps.issues_sync_once()
        text = self.p.read_text()
        self.assertIn('- [ ] added in Obsidian', text)
        self.assertIn('**Generated** — [#1]', text)

    def test_rebuild_noop_after_pull_skips_commit(self) -> None:
        commits: list[tuple] = []
        def git(*a):
            if a[0] == 'commit':
                commits.append(a)
            if a[0] == 'pull':  # the pull brings in exactly the rendered block
                self.p.write_text(ps.replace_issue_blocks(self.p.read_text(), ps.render_issue_blocks(ISSUES)))
            return subprocess.CompletedProcess(a, 0, '', '')
        ps._run_git = git
        ps.issues_sync_once()
        self.assertEqual(commits, [])

    def test_note_on_board_is_skipped_with_warning(self) -> None:
        logs: list[tuple] = []
        ps.post_log = lambda *a, **k: logs.append(a)
        before = self.p.read_text()
        ps.issues_sync_once(board_slugs=['p'])
        self.assertEqual(self.fetched, [])
        self.assertEqual(self.p.read_text(), before)
        self.assertTrue(any(a[0] == 'warn' and 'is on the Board' in a[1] for a in logs))

    def test_note_on_board_warns_once_per_process(self) -> None:
        logs: list[tuple] = []
        ps.post_log = lambda *a, **k: logs.append(a)
        for _ in range(3):
            ps._issues_due = 0.0
            ps.issues_sync_once(board_slugs=['p'])
        self.assertEqual(sum('is on the Board' in a[1] for a in logs), 1)

    def test_stale_toggle_of_generated_line_leaves_manual_lines_alone(self) -> None:
        """Issue closed → block re-rendered without the line → toggle with a stale idx."""
        ps.issues_sync_once()
        text = next(line for line in self.p.read_text().split('\n') if '[#1]' in line)[len('- [ ] '):]
        ps.fetch_open_issues = lambda repo: []
        ps._issues_due = 0.0
        ps.issues_sync_once()
        self.assertNotIn('[#1]', self.p.read_text())
        git_calls: list[tuple] = []
        ps._run_git = lambda *a: git_calls.append(a) or subprocess.CompletedProcess(a, 0, '', '')
        before = self.p.read_text()
        for done in (False, True):
            status, err = ps._apply_one_toggle({'slug': 'p', 'section': 'now', 'idx': 0, 'done': done, 'text': text})
            self.assertEqual((status, err), ('applied', None))
        self.assertEqual(self.p.read_text(), before)
        self.assertIn('- [ ] manual line', before)
        self.assertEqual(self.closed, [('o/r', 1, False), ('o/r', 1, True)])
        self.assertEqual([c for c in git_calls if 'commit' in c], [])

    def _stale_manual_setup(self) -> tuple[str, list[tuple]]:
        """Block with 1 issue + 2 manual lines; the view was rendered with 2 issues, M2 edited since."""
        ps.issues_sync_once()
        self.p.write_text(self.p.read_text().replace('- [ ] manual line', '- [ ] M1\n- [ ] M2 reworded'), encoding='utf-8')
        git_calls: list[tuple] = []
        ps._run_git = lambda *a: git_calls.append(a) or subprocess.CompletedProcess(a, 0, '', '')
        return self.p.read_text(), git_calls

    def test_stale_text_in_note_with_block_never_falls_back_to_idx(self) -> None:
        before, git_calls = self._stale_manual_setup()
        status, err = ps._apply_one_toggle({'slug': 'p', 'section': 'now', 'idx': 2, 'done': True, 'text': 'M2 old'})
        self.assertEqual((status, err), ('conflict', 'task changed since the view was rendered'))
        self.assertEqual(self.p.read_text(), before)
        self.assertEqual([c for c in git_calls if 'commit' in c], [])

    def test_note_without_block_keeps_idx_fallback(self) -> None:
        self.p.write_text(OPTED_IN, encoding='utf-8')
        status, _ = ps._apply_one_toggle({'slug': 'p', 'section': 'now', 'idx': 0, 'done': True, 'text': 'reworded'})
        self.assertEqual(status, 'applied')
        self.assertIn('- [x] manual line', self.p.read_text())

    def test_reworded_manual_line_linking_to_foreign_repo_does_not_close_it(self) -> None:
        ps.issues_sync_once()
        self.p.write_text(self.p.read_text().replace(
            '- [ ] manual line', '- [ ] 🔴 **Secret** — [#9](https://github.com/x/other/issues/9)'), encoding='utf-8')
        before = self.p.read_text()
        old = '🔴 **Secret old** — [#9](https://github.com/x/other/issues/9)'
        status, err = ps._apply_one_toggle({'slug': 'p', 'section': 'now', 'idx': 1, 'done': True, 'text': old})
        self.assertEqual((status, err), ('conflict', 'issue link outside the note repo'))
        self.assertEqual(self.closed, [])
        self.assertEqual(self.p.read_text(), before)

    def test_orphan_start_is_warned_once_and_not_duplicated(self) -> None:
        ps.issues_sync_once()
        broken = self.p.read_text().replace('<!-- github-issues:end -->\n', '', 1)
        self.p.write_text(broken, encoding='utf-8')
        logs: list[tuple] = []
        ps.post_log = lambda *a, **k: logs.append(a)
        for _ in range(2):
            ps._issues_due = 0.0
            ps.issues_sync_once()
        self.assertEqual(self.p.read_text(), broken)
        self.assertEqual(len([a for a in logs if 'START without END' in a[1]]), 1)

    def test_write_failures_are_logged_without_board_sync_prefix(self) -> None:
        logs: list[tuple] = []
        ps.post_log = lambda *a, **k: logs.append(a)
        ps._run_git = lambda *a: subprocess.CompletedProcess(a, 1, '', 'boom')
        ps.issues_sync_once()
        warns = [a[1] for a in logs if a[0] == 'warn']
        self.assertTrue(warns)
        self.assertFalse(any('board-sync' in w for w in warns))

    def test_bad_repo_is_skipped(self) -> None:
        self.p.write_text(OPTED_IN.replace('o/r', 'https://github.com/o/r'), encoding='utf-8')
        ps.issues_sync_once()
        self.assertEqual(self.fetched, [])


if __name__ == '__main__':
    unittest.main()
