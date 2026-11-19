"""Tests for seed.py — the sprint's starting queue.

Run:
    python3 -m unittest discover -s ops/mac/sprint/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import seed  # noqa: E402

PR = {'repository': {'nameWithOwner': 'PiotrRomanczuk/home-ops'}, 'number': 7, 'title': 't', 'url': 'https://x/7'}


class SeedTest(unittest.TestCase):
    def seed_with(self, vault: Path, state: Path) -> list[str]:
        gh = mock.Mock(stdout=json.dumps([PR]))
        with mock.patch.object(seed, 'STATE', state), mock.patch.object(seed, 'VAULT', vault), \
                mock.patch.object(seed.subprocess, 'run', return_value=gh), \
                mock.patch.object(seed, 'repo_dirs', return_value={}), \
                mock.patch.object(seed.lifecycle, 'single_instance', return_value=object()):
            seed.main()
        return sorted(p.stem for p in (state / 'queue').glob('*.md'))

    def test_no_active_notes_skips_vault_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault, state = Path(tmp) / 'vault', Path(tmp) / 'state'
            vault.mkdir()
            self.assertEqual(self.seed_with(vault, state), ['review-home-ops-7'])

    def test_active_note_gets_pilot_and_review_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault, state = Path(tmp) / 'vault', Path(tmp) / 'state'
            (vault / '1-Projekty').mkdir(parents=True)
            (vault / '1-Projekty' / 'alpha.md').write_text('---\ntype: project\nstatus: hot\n---\n')
            self.assertEqual(self.seed_with(vault, state),
                             ['review-home-ops-7', 'vault-pilot-alpha', 'vault-pilot-review'])


if __name__ == '__main__':
    unittest.main()
