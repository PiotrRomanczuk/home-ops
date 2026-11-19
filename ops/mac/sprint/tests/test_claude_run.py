"""Tests for claude_run.py + deny_rules.py: the flag list, the hard time limit on the whole process group.

Run:
    python3 -m unittest discover -s ops/mac/sprint/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import claude_run  # noqa: E402
import deny_rules  # noqa: E402

TASK = {'id': 't1', 'body': 'prompt', 'max_minutes': 1}
MUST_DENY = ('Bash(gh pr merge:*)', 'Bash(gh pr review --approve:*)', 'Bash(ssh:*)', 'Bash(git push --force:*)',
             'Bash(git push * --force*)', 'Bash(git push * -f)', 'Edit(~/.claude/**)', 'Write(~/.claude/**)')


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class CommandTest(unittest.TestCase):
    def test_deny_list_follows_the_flag_up_to_the_next_flag(self):
        state = Path(tempfile.gettempdir()) / 'sprint-x'
        cmd = claude_run.command('claude', TASK, 'sonnet', state, state)
        listed = cmd[cmd.index('--disallowedTools') + 1:cmd.index('--model')]
        self.assertEqual(listed, deny_rules.denied(state))
        for rule in (*MUST_DENY, f'Edit(/{state}/config.json)', f'Write(/{state}/config.json)', f'Write(/{state}/STOP)'):
            self.assertIn(rule, listed)
        self.assertEqual(cmd[1], '-p')
        self.assertTrue(cmd[2].startswith('prompt'))

    def test_state_under_home_is_written_home_relative(self):
        rules = deny_rules.denied(Path('~/.local/state/home-ops/sprint').expanduser())
        self.assertIn('Edit(~/.local/state/home-ops/sprint/config.json)', rules)
        self.assertIn('Write(~/.local/state/home-ops/sprint/STOP)', rules)

    def test_the_other_flags_are_still_there(self):
        state = Path(tempfile.gettempdir())
        cmd = claude_run.command('claude', {**TASK, 'effort': 'high'}, 'local:qwen', state, state)
        for flag in ('--permission-mode', '--output-format', '--strict-mcp-config', '--append-system-prompt', '--add-dir', '-n'):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index('--model') + 1], 'qwen')
        self.assertNotIn('--dangerously-skip-permissions', cmd)

    def test_the_hook_dependency_is_documented(self):
        self.assertIn('guard-bash.py', claude_run.__doc__)
        self.assertIn('guard-bash.py', deny_rules.__doc__)


class ProcessGroupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_task(self, script: str, **kw) -> dict:
        fake = self.dir / 'claude'
        fake.write_text('#!/bin/sh\n' + script)
        fake.chmod(0o755)
        return claude_run.run(str(fake), {**TASK, 'cwd': str(self.dir)}, 'sonnet', self.dir, self.dir, '', **kw)

    def test_timeout_kills_the_grandchildren_too(self):
        pidfile = self.dir / 'grandchild.pid'
        started = time.time()
        r = self.run_task(f'sleep 300 &\necho $! > {pidfile}\nwait\n', timeout=1, grace=5)
        self.assertEqual(r['rc'], 124)
        self.assertLess(time.time() - started, 20)
        self.assertTrue(r['stderr'].startswith('timeout'))
        time.sleep(0.3)
        self.assertFalse(alive(int(pidfile.read_text())))

    def test_what_ignores_sigterm_is_killed_after_the_grace_period(self):
        pidfile = self.dir / 'stubborn.pid'
        started = time.time()
        r = self.run_task(f"trap '' TERM\nsleep 300 &\necho $! > {pidfile}\nwait\n", timeout=1, grace=1)
        self.assertEqual(r['rc'], 124)
        self.assertLess(time.time() - started, 15)
        time.sleep(0.3)
        self.assertFalse(alive(int(pidfile.read_text())))

    def test_a_local_run_stops_at_the_configs_cap_whatever_the_task_says(self):
        fake = self.dir / 'claude'
        fake.write_text('#!/bin/sh\nsleep 6  # a mutant without the cap ends here with rc 0, not hanging the suite\n')
        fake.chmod(0o755)
        r = claude_run.run(str(fake), {**TASK, 'max_minutes': 60, 'cwd': str(self.dir)}, 'local:qwen', self.dir, self.dir,
                           'http://127.0.0.1:1', grace=1, local_minutes=0.02)
        self.assertEqual(r['rc'], 124)  # only the cap yields 124; no wall-clock bound, so a loaded Mac cannot fail it
        self.assertFalse((self.dir / 'gpu' / 'borrow').exists())

    def test_a_worktree_left_behind_is_named_not_removed(self):
        worktree = self.dir / '.claude' / 'worktrees' / 'sprint-t1'
        worktree.mkdir(parents=True)
        r = self.run_task('sleep 300\n', timeout=1, grace=2)
        self.assertEqual(r['res']['orphan_worktree'], str(worktree))
        self.assertTrue(worktree.exists())

    def test_normal_run_keeps_json_and_the_whole_stderr(self):
        r = self.run_task('head -c 40000 /dev/zero | tr "\\0" e >&2\necho \'{"result":"ok","session_id":"s"}\'\n')
        self.assertEqual((r['rc'], r['res']['result'], len(r['stderr'])), (0, 'ok', 40000))
        self.assertNotIn('orphan_worktree', r['res'])

    def test_output_that_is_not_a_json_object_becomes_an_error_result(self):
        r = self.run_task("echo '[1, 2]'\n")
        self.assertEqual((r['res']['is_error'], r['res']['result'].strip()), (True, '[1, 2]'))


if __name__ == '__main__':
    unittest.main()
