"""Tests for idea.py (ideas into the vault note) and journal.py (daily count of local-model runs).

Run:
    python3 -m unittest discover -s ops/mac/sprint/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import idea  # noqa: E402
import journal  # noqa: E402

NOTE = '# Mac\n\n## Pomysły\n\n- [ ] 2026-11-15 pierwszy\n\n## Propozycje GPU\n\n- coś\n'


class IdeaTest(unittest.TestCase):
    def test_clean_folds_lines_and_strips_marks(self):
        self.assertEqual(idea.clean('mac: przepuść\n- [x] wokale\n## przez whisper'), 'przepuść - wokale przez whisper')
        self.assertEqual(len(idea.clean('a' * 500)), 300)
        self.assertEqual(idea.clean('  mac:   '), '')

    def test_insert_lands_at_the_end_of_the_section(self):
        out = idea.insert(NOTE, '- [ ] 2026-11-16 drugi')
        self.assertIn('- [ ] 2026-11-15 pierwszy\n- [ ] 2026-11-16 drugi\n\n## Propozycje GPU', out)

    def test_insert_into_empty_last_section(self):
        out = idea.insert('# Mac\n\n## Pomysły\n', '- [ ] x')
        self.assertTrue(out.endswith('## Pomysły\n- [ ] x\n'))


class JournalTest(unittest.TestCase):
    def test_local_runs_today(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / 'logs').mkdir()
            today = date.today().isoformat()
            rows = [{'ts': '2000-01-01T10:00:00', 'outcome': 'done', 'model': 'local:qwen3.8:27b'},
                    {'ts': f'{today}T01:00:00', 'outcome': 'done', 'model': 'local:qwen3.8:27b'},
                    {'ts': f'{today}T02:00:00', 'outcome': 'retry', 'model': 'sonnet'},
                    {'ts': f'{today}T03:00:00', 'outcome': 'retry', 'model': 'local:gemma4:26b'}]
            (state / 'logs' / 'runs.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
            self.assertEqual(journal.local_runs_today(state), 2)


if __name__ == '__main__':
    unittest.main()
