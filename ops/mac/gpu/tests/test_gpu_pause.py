"""Tests for gpu_pause.py — the GPU borrow marker and pausing shards.

Run:
    python3 -m unittest discover -s ops/mac/gpu/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gpu_pause  # noqa: E402


class BorrowedTest(unittest.TestCase):
    def test_marker_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gpu = Path(tmp)
            self.assertFalse(gpu_pause.borrowed(gpu))  # no marker
            (gpu / 'borrow').write_text('not a pid')
            self.assertFalse(gpu_pause.borrowed(gpu))
            (gpu / 'borrow').write_text(str(os.getpid()))
            self.assertTrue(gpu_pause.borrowed(gpu))
            (gpu / 'borrow').write_text('999999999')
            self.assertFalse(gpu_pause.borrowed(gpu))


class PauseTest(unittest.TestCase):
    def test_pause_and_resume_log_once(self) -> None:
        shards = {1: {'proc': mock.Mock(pid=42), 'paused': False}}
        events: list[tuple[str, int]] = []
        log = lambda event, **kw: events.append((event, kw['shard']))  # noqa: E731
        with mock.patch.object(gpu_pause.procs, 'send', return_value=True) as send:
            gpu_pause.pause(shards, True, log)
            gpu_pause.pause(shards, True, log)  # already paused: no second signal
            gpu_pause.pause(shards, False, log)
        self.assertEqual([c.args for c in send.call_args_list], [(42, signal.SIGSTOP), (42, signal.SIGCONT)])
        self.assertEqual(events, [('paused', 1), ('resumed', 1)])
        self.assertFalse(shards[1]['paused'])


if __name__ == '__main__':
    unittest.main()
