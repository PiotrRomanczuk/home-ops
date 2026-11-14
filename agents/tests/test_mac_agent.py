"""Tests for the Mac agent helpers: mac_sample (ioreg/nettop parsing), mac_procs
(session attribution + notable-process tracking), spool (offline replay),
day_prompt (LLM prompt + Dziś card).

ioreg/nettop text is trimmed from real output on the Mac (2026-11-14).

Run:
    python3 -m unittest discover -s agents/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

AGENTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENTS))
sys.path.insert(0, str(AGENTS / 'mac'))
import day_prompt  # noqa: E402
from mac_procs import Tracker, lineage, registry, session_of  # noqa: E402
from mac_sample import NetCounter, on_home_lan, parse_ioreg, parse_nettop  # noqa: E402
from spool import Spool  # noqa: E402

IOREG = ('| "PerformanceStatistics" = {"Alloc system memory"=12177424384,"Renderer Utilization %"=8,'
         '"Device Utilization %"=93,"In use system memory"=8686288896}')
NETTOP_1 = ',bytes_in,bytes_out,\nollama.45720,1000,50,\nGoogle Chrome H.76304,10,10,\n'
NETTOP_2 = ',bytes_in,bytes_out,\nollama.45720,5000,80,\nGoogle Chrome H.76304,10,10,\nnew.9,7,7,\n'
SID = '1dfde554-1f0f-4607-a7e7-b605816af30f'
SCRATCH = f'/private/tmp/claude-501/-Users-pionat-code/{SID}/scratchpad'


class SampleTest(unittest.TestCase):
    def test_ioreg(self):
        self.assertEqual(parse_ioreg(IOREG), {'gpu_pct': 93, 'renderer_pct': 8, 'mem_bytes': 8686288896})
        self.assertEqual(parse_ioreg(''), {})

    def test_nettop_and_deltas(self):
        self.assertEqual(parse_nettop(NETTOP_1)[76304], ('Google Chrome H', 10, 10))
        net = NetCounter()
        self.assertEqual(net.deltas(NETTOP_1), {})
        self.assertEqual(net.deltas(NETTOP_2), {45720: ('ollama', 4000, 30)})

    def test_home_lan(self):
        class A:
            def __init__(self, a): self.address = a
        self.assertTrue(on_home_lan({'en0': [A('192.168.1.54')]}))
        self.assertFalse(on_home_lan({'en0': [A('10.0.0.2')], 'utun3': [A('100.86.1.1')]}))


def procs():
    return {
        1: {'name': 'launchd', 'ppid': 0, 'cmd': ''},
        100: {'name': 'claude', 'ppid': 1, 'cmd': 'claude'},
        101: {'name': 'zsh', 'ppid': 100, 'cmd': 'zsh -c source snapshot'},
        102: {'name': 'npm', 'ppid': 100, 'cmd': 'npm exec mcp'},
        103: {'name': 'node', 'ppid': 102, 'cmd': 'node mcp', 'started': 0},
        104: {'name': 'pytest', 'ppid': 101, 'cmd': 'pytest', 'started': 0},
        200: {'name': 'zsh', 'ppid': 1, 'cmd': f'zsh -c (for m in a b; do ollama pull $m; done) > {SCRATCH}/logs/p.log'},
        201: {'name': 'ollama', 'ppid': 200, 'cmd': 'ollama pull gemma4:26b', 'started': 0},
        300: {'name': 'Spotify', 'ppid': 1, 'cmd': 'Spotify', 'started': 0, 'cpu_pct': 40.0},
    }


REG = {100: {'session_id': 'live-1', 'name': 'praca', 'status': 'busy'}}


class ProcsTest(unittest.TestCase):
    def test_attribution(self):
        p = procs()
        self.assertEqual(session_of(104, p, REG), 'live-1')
        self.assertEqual(session_of(201, p, REG), SID)  # orphaned job, found by its scratchpad path
        self.assertIsNone(session_of(300, p, REG))
        self.assertEqual(lineage(103, p, REG), (100, 102))
        self.assertEqual(lineage(201, p, REG), (None, None))

    def test_tracker_flags_jobs_hogs_and_downloads(self):
        t, p = Tracker(), procs()
        first = t.update(p, REG, {}, now=1000, interval=30)
        names = {r['name']: r['reason'] for r in first}
        self.assertEqual(names, {'pytest': 'claude', 'ollama': 'claude'})  # MCP node is plumbing, shells skipped
        second = t.update(p, REG, {300: ('Spotify', 40_000_000, 0)}, now=1030, interval=30)
        self.assertEqual([(r['name'], r['reason']) for r in second], [('Spotify', 'net')])
        del p[201]
        stop = t.update(p, REG, {}, now=1100, interval=30)
        self.assertEqual([(r['event'], r['name'], r['duration_s']) for r in stop], [('stop', 'ollama', 1100)])

    def test_registry_reads_json_only(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, '100.json').write_text(json.dumps({'pid': 100, 'sessionId': 's', 'name': 'n', 'status': 'idle'}))
            Path(d, '100.key').write_text('secret')
            Path(d, 'bad.json').write_text('{')
            self.assertEqual(registry(Path(d)), {100: {'session_id': 's', 'name': 'n', 'status': 'idle'}})


class SpoolTest(unittest.TestCase):
    def test_replays_in_batches_and_keeps_the_rest_on_failure(self):
        with tempfile.TemporaryDirectory() as d:
            sp = Spool(Path(d) / 's.jsonl')
            sp.append('/api/metrics', [{'n': i} for i in range(3)])
            sp.append('/api/ingest', [{'e': 1}])
            sent = []
            ok = sp.flush(lambda path, body: sent.append((path, body)) or path == '/api/metrics')
            self.assertFalse(ok)
            self.assertEqual(sent[0], ('/api/metrics', {'metrics': [{'n': 0}, {'n': 1}, {'n': 2}]}))
            self.assertEqual(sp.pending(), 1)
            self.assertTrue(sp.flush(lambda path, body: True))
            self.assertEqual(sp.pending(), 0)


JOURNAL = {
    'day': '2026-11-14', 'awake_min': 600,
    'claude': {'totals': {'sessions': 5, 'prompts': 80, 'active_min': 185, 'errors': 3},
               'by_project': [{'project_slug': 'home-ops', 'active_min': 120, 'prompts': 50, 'sessions': 2},
                              {'project_slug': None, 'active_min': 65, 'prompts': 30, 'sessions': 3}],
               'sessions': [{'host': 'mac', 'session_id': 'abc', 'title': 'Dziennik Maca', 'prompts_day': 40}],
               'prs': ['https://github.com/o/home-ops/pull/80']},
    'apps': {'cpu': [{'name': 'ollama', 'cpu_s': 3600}], 'net': [{'name': 'ollama', 'mb': 58000.0}]},
    'procs': [{'name': 'ollama', 'reason': 'claude', 'cmd': 'ollama pull gemma4:26b'}],
}


class DayPromptTest(unittest.TestCase):
    def test_prompt_has_facts_and_tasks_of_todays_projects_first(self):
        p = day_prompt.build_prompt(JOURNAL, ['strummy: karnety', 'home-ops: wdrożyć 032'])
        for want in ('3 h 05 min', 'projekt home-ops', 'ollama pull gemma4:26b', '\n## Dzień\n', '\n## Co dalej\n'):
            self.assertIn(want, p)
        self.assertLess(p.index('home-ops: wdrożyć 032'), p.index('strummy: karnety'))

    def test_next_steps_parse(self):
        text = '## Dzień\nDużo pracy.\n- nie to\n## Co dalej\n- **Wdrożyć** 032\n* Przejrzeć PR\nkoniec'
        self.assertEqual(day_prompt.next_steps(text), ['Wdrożyć 032', 'Przejrzeć PR'])

    def test_card(self):
        c = day_prompt.card(JOURNAL, ['krok'], prev_active_min=125)
        self.assertTrue(c['headline'].startswith('sob 14.11: 3 h 05 min z Claude · 5 sesji · 80 promptów'))
        self.assertEqual(c['items'], [('krok', None)])
        self.assertEqual(c['metric'], {'label': 'aktywny czas z Claude', 'value': 3.1, 'unit': 'h', 'delta': 1.0})
        fallback = day_prompt.card(JOURNAL, [], None)
        self.assertNotIn('delta', fallback['metric'])
        self.assertTrue(fallback['items'])


if __name__ == '__main__':
    unittest.main()
