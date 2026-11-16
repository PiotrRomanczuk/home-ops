"""Tests for process_git — the git sequence behind a BPMN save, on throwaway
repos (bare remote + two clones in a temp dir; the real vault is never touched).

Run:
    python3 -m unittest discover -s agents/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'elitedesk'))
import process_git as pg  # noqa: E402

REL = 'procesy/pr-flow.bpmn'
OLD = '<bpmn:definitions>old</bpmn:definitions>'
NEW = '<bpmn:definitions>new — zażółć</bpmn:definitions>'
OBSIDIAN = '<bpmn:definitions>edited in obsidian</bpmn:definitions>'
MSG = 'procesy: pr-flow edytowany w Mapie (home-ops, zapis #1)'


def sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
                          capture_output=True, text=True)


class ProcessGitTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.remote = root / 'remote.git'
        subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(self.remote)], check=True)
        self.clone = self._clone(root / 'clone')
        (self.clone / 'procesy').mkdir()
        (self.clone / REL).write_text(OLD, encoding='utf-8')
        git(self.clone, 'add', '.')
        git(self.clone, 'commit', '-qm', 'init')
        git(self.clone, 'push', '-q', '-u', 'origin', 'main')
        self.other = self._clone(root / 'other')  # Obsidian's side
        self.run_git = lambda *a: git(self.clone, *a)

    def tearDown(self):
        self._tmp.cleanup()

    def _clone(self, path: Path) -> Path:
        subprocess.run(['git', 'clone', '-q', str(self.remote), str(path)], check=True, capture_output=True)
        return path

    def apply(self, run_git=None, base=OLD, xml=NEW):
        return pg.apply_process_write(run_git or self.run_git, self.clone / REL, REL, xml, sha(base), MSG)

    def obsidian_pushes(self, text: str) -> None:
        git(self.other, 'pull', '-q', '--ff-only')
        (self.other / REL).write_text(text, encoding='utf-8')
        git(self.other, 'commit', '-qam', 'obsidian edit')
        self.assertEqual(git(self.other, 'push', '-q').returncode, 0)

    def assert_clean_and_in_sync(self):
        self.assertEqual(git(self.clone, 'status', '--porcelain').stdout, '')
        git(self.clone, 'fetch', '-q')
        self.assertEqual(git(self.clone, 'rev-parse', 'HEAD').stdout, git(self.clone, 'rev-parse', '@{u}').stdout)

    def test_applies_commits_and_pushes(self):
        self.assertEqual(self.apply(), ('applied', None))
        self.assertEqual((self.clone / REL).read_text(encoding='utf-8'), NEW)
        self.assertEqual(git(self.remote, 'show', f'main:{REL}').stdout, NEW)
        self.assertIn('zapis #1', git(self.remote, 'log', '-1', '--format=%s').stdout)
        self.assert_clean_and_in_sync()

    def test_edit_that_lands_during_the_pull_is_not_overwritten(self):
        # B1: Obsidian pushed after the sync tick read the vault, before our pull.
        self.obsidian_pushes(OBSIDIAN)
        status, reason = self.apply()
        self.assertEqual(status, 'conflict')
        self.assertIn('reload', reason)
        self.assertEqual((self.clone / REL).read_text(encoding='utf-8'), OBSIDIAN)
        self.assertEqual(git(self.remote, 'rev-list', '--count', 'main').stdout.strip(), '2')
        self.assert_clean_and_in_sync()

    def test_rejected_push_leaves_the_clone_on_the_remote_head(self):
        # B2: the remote moves between our pull and our push.
        def racing(*args):
            if args[0] == 'push' and not getattr(racing, 'done', False):
                racing.done = True
                self.obsidian_pushes(OBSIDIAN)
            return self.run_git(*args)
        status, reason = self.apply(racing)
        self.assertEqual(status, 'conflict')
        self.assertIn('push rejected', reason)
        self.assertEqual((self.clone / REL).read_text(encoding='utf-8'), OBSIDIAN)
        self.assert_clean_and_in_sync()
        self.assertEqual(git(self.clone, 'log', '--format=%s').stdout.split('\n')[0], 'obsidian edit')

    def test_hook_rejected_push_drops_the_local_commit(self):
        hook = self.remote / 'hooks' / 'pre-receive'
        hook.write_text('#!/bin/sh\necho no >&2\nexit 1\n')
        hook.chmod(0o755)
        status, _ = self.apply()
        self.assertEqual(status, 'conflict')
        self.assertEqual((self.clone / REL).read_text(encoding='utf-8'), OLD)
        self.assert_clean_and_in_sync()
        self.assertEqual(git(self.clone, 'rev-list', '--count', 'HEAD').stdout.strip(), '1')

    def test_failed_commit_restores_the_file(self):
        # B3: add/commit dies (index.lock, hook…) after the file was written.
        def failing(*args):
            if 'commit' in args:
                return subprocess.CompletedProcess(args, 1, '', 'fatal: index.lock exists')
            return self.run_git(*args)
        status, reason = self.apply(failing)
        self.assertEqual(status, 'conflict')
        self.assertIn('commit failed', reason)
        self.assertEqual((self.clone / REL).read_text(encoding='utf-8'), OLD)
        self.assert_clean_and_in_sync()

    def test_failed_add_restores_the_file(self):
        def failing(*args):
            if args[0] == 'add':
                return subprocess.CompletedProcess(args, 1, '', 'fatal: Unable to create index.lock')
            return self.run_git(*args)
        self.assertEqual(self.apply(failing)[0], 'conflict')
        self.assertEqual((self.clone / REL).read_text(encoding='utf-8'), OLD)
        self.assert_clean_and_in_sync()

    def test_save_with_no_change_is_applied_without_a_commit(self):
        # B4: diagram dragged away and back.
        self.assertEqual(self.apply(xml=OLD), ('applied', None))
        self.assertEqual(git(self.remote, 'rev-list', '--count', 'main').stdout.strip(), '1')
        self.assert_clean_and_in_sync()

    def test_pre_write_pull_failure_writes_nothing(self):
        git(self.clone, 'config', 'pull.ff', 'only')
        (self.clone / 'local.txt').write_text('x')
        git(self.clone, 'add', 'local.txt')
        git(self.clone, 'commit', '-qm', 'local only')  # clone diverges once the remote moves
        self.obsidian_pushes(OBSIDIAN)
        status, reason = self.apply()
        self.assertEqual(status, 'conflict')
        self.assertIn('pre-write pull failed', reason)
        self.assertEqual((self.clone / REL).read_text(encoding='utf-8'), OLD)

    def test_git_sequence_holds_the_shared_lock(self):
        held: list[bool] = []

        def probe(*args):
            def try_lock():
                got = pg.GIT_LOCK.acquire(blocking=False)
                held.append(not got)
                if got:
                    pg.GIT_LOCK.release()
            t = threading.Thread(target=try_lock)
            t.start()
            t.join()
            return self.run_git(*args)
        self.apply(probe)
        self.assertTrue(held and all(held))


if __name__ == '__main__':
    unittest.main()
