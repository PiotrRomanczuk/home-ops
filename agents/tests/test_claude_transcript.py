"""Tests for claude_transcript / claude_tools / claude_parts — transcript lines → session + events.

Lines are synthetic but shaped like Claude Code 2.1.31x transcripts (field names
checked against real files on 2026-11-14). No real prompts.

Run:
    python3 -m unittest discover -s agents/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from claude_transcript import feed, new_state, row  # noqa: E402

TS = '2026-11-14T15:12:43.297Z'


def line(**d) -> str:
    return json.dumps({'parentUuid': None, 'timestamp': TS, 'sessionId': 's1', **d})


def user(uuid: str, content, **extra) -> str:
    return line(type='user', uuid=uuid, message={'role': 'user', 'content': content}, cwd='/Users/x/code/app',
                gitBranch='main', entrypoint='cli', version='2.1.311', **extra)


def assistant(uuid: str, mid: str, blocks, model='claude-opus-5-5', **extra) -> str:
    usage = {'input_tokens': 10, 'output_tokens': 5, 'cache_read_input_tokens': 100,
             'cache_creation_input_tokens': 7, 'output_tokens_details': {'thinking_tokens': 2}}
    return line(type='assistant', uuid=uuid, message={'id': mid, 'model': model, 'content': blocks, 'usage': usage},
                **extra)


def run(lines, sidechain=False, st=None):
    st = st or new_state('s1')
    events = []
    for ln in lines:
        events += feed(st, ln, sidechain)
    return st, events


class TranscriptTest(unittest.TestCase):
    def test_human_prompt_counts_meta_and_commands_do_not(self):
        st, ev = run([
            user('u1', 'zrób raport', turnOrigin='human', promptSource='typed'),
            user('u2', [{'type': 'text', 'text': 'kolejka'}], turnOrigin='human', promptSource='queued'),
            user('u3', '<command-name>/model</command-name>'),
            user('u4', 'caveat', turnOrigin='human', isMeta=True),
            user('u5', [{'type': 'tool_result', 'tool_use_id': 't', 'content': 'ok'}], turnOrigin='human'),
        ])
        self.assertEqual(st['prompts_n'], 2)
        self.assertEqual([e['uuid'] for e in ev if e['kind'] == 'prompt'], ['u1', 'u2'])
        self.assertEqual(ev[0]['detail'], {'source': 'typed'})

    def test_usage_counted_once_per_message_id(self):
        st, _ = run([assistant('a1', 'm1', [{'type': 'text', 'text': 'x'}]),
                     assistant('a2', 'm1', [{'type': 'tool_use', 'id': 't1', 'name': 'Read', 'input': {}}]),
                     assistant('a3', 'm2', [], model='claude-haiku-5-5')])
        self.assertEqual(st['tokens']['claude-opus-5-5'],
                         {'in': 10, 'out': 5, 'cache_read': 100, 'cache_write': 7, 'thinking': 2})
        self.assertEqual(st['tokens']['claude-haiku-5-5']['in'], 10)

    def test_tools_become_counters_and_events(self):
        blocks = [
            {'type': 'tool_use', 'id': 't1', 'name': 'Bash', 'input': {'command': 'curl -H "Authorization: Bearer abcdefghijklmnop" x', 'description': 'call'}},
            {'type': 'tool_use', 'id': 't2', 'name': 'Edit', 'input': {'file_path': '/a.py'}},
            {'type': 'tool_use', 'id': 't3', 'name': 'Agent', 'input': {'subagent_type': 'Explore', 'description': 'map'}},
            {'type': 'tool_use', 'id': 't4', 'name': 'Skill', 'input': {'skill': 'home-infra'}},
            {'type': 'tool_use', 'id': 't5', 'name': 'mcp__obsidian__get', 'input': {}},
            {'type': 'tool_use', 'id': 't6', 'name': 'Edit', 'input': {'file_path': '/a.py'}},
        ]
        st, ev = run([assistant('a1', 'm1', blocks)])
        self.assertEqual(st['tool_calls_n'], 6)
        self.assertEqual(st['tools']['Edit'], 2)
        self.assertEqual(st['subagents'], {'Explore': 1})
        self.assertEqual(st['skills'], {'home-infra': 1})
        self.assertEqual(st['mcp'], {'obsidian': 1})
        self.assertEqual(st['files_edited'], ['/a.py'])
        bash = next(e for e in ev if e['kind'] == 'bash')
        self.assertIn('Bearer abcdef...', bash['text'])
        self.assertNotIn('abcdefghijklmnop', bash['text'])
        self.assertEqual([e['uuid'] for e in ev], ['t1', 't2', 't3', 't4', 't5', 't6'])

    def test_errors_git_prs_and_summaries(self):
        st, ev = run([
            user('u1', [{'type': 'tool_result', 'tool_use_id': 'tx', 'is_error': True, 'content': 'boom'}]),
            user('u2', [{'type': 'tool_result', 'tool_use_id': 'ty', 'content': 'ok'}],
                 toolUseResult={'gitOperation': {'push': {'branch': 'feat/x'}}}),
            json.dumps({'type': 'pr-link', 'prUrl': 'https://github.com/o/r/pull/7', 'prNumber': '7',
                        'prRepository': 'o/r', 'timestamp': TS}),
            user('u3', [], toolUseResult={'gitOperation': {'pr': {'number': 7, 'url': 'https://github.com/o/r/pull/7'}}}),
            line(type='system', subtype='away_summary', uuid='s1', content='Zrobione: raport.'),
            line(type='system', subtype='turn_duration', uuid='s2', durationMs=61_000),
            line(type='system', subtype='compact_boundary', uuid='s3'),
        ])
        self.assertEqual(st['tool_errors_n'], 1)
        self.assertEqual(st['pushes'], ['feat/x'])
        self.assertEqual(len(st['prs']), 1)
        self.assertEqual((st['active_ms'], st['compactions_n']), (61_000, 1))
        self.assertEqual(sorted(e['kind'] for e in ev), ['error', 'git', 'pr', 'summary'])

    def test_titles_cost_and_surface(self):
        st, _ = run([
            user('u1', 'hej', turnOrigin='human'),
            json.dumps({'type': 'ai-title', 'aiTitle': 'Auto', 'sessionId': 's1'}),
            json.dumps({'type': 'custom-title', 'customTitle': 'Mój tytuł', 'sessionId': 's1'}),
            json.dumps({'type': 'bridge-session', 'sessionId': 's1', 'bridgeSessionId': 'cse_1'}),
            json.dumps({'type': 'cost-state', 'totalCostUSD': '1.23456', 'totalLinesAdded': 10, 'totalLinesRemoved': '2'}),
            '{"type":"api-request-blob","x":1}',
            'not json',
        ])
        r = row(st)
        self.assertEqual((r['title'], r['surface'], r['cost_usd'], r['lines_added'], r['lines_removed']),
                         ('Mój tytuł', 'remote', 1.2346, 10, 2))
        self.assertEqual((r['cwd'], r['git_branch'], r['started_at']), ('/Users/x/code/app', 'main', TS))

    def test_sidechain_counts_tools_not_prompts_and_keeps_parent_cwd(self):
        st, _ = run([user('u1', 'hej', turnOrigin='human')])
        sub = user('u9', 'task for agent', turnOrigin='human', isSidechain=True, agentId='ag1')
        sub = sub.replace('/Users/x/code/app', '/tmp/elsewhere')
        st, ev = run([sub, assistant('a9', 'm9', [{'type': 'tool_use', 'id': 't9', 'name': 'Bash',
                                                     'input': {'command': 'ls'}}], agentId='ag1')], True, st)
        self.assertEqual(st['prompts_n'], 1)
        self.assertEqual(st['cwd'], '/Users/x/code/app')
        self.assertEqual(ev[0]['detail']['agent'], 'ag1')

    def test_cwd_is_where_the_session_started(self):
        later = user('u2', 'dalej', turnOrigin='human').replace('/Users/x/code/app', '/Users/x/code/other')
        st, _ = run([user('u1', 'hej', turnOrigin='human'), later])
        self.assertEqual(st['cwd'], '/Users/x/code/app')

    def test_surfaces(self):
        from claude_parts import surface
        cases = [({'entrypoint': 'claude-desktop'}, 'desktop'), ({'entrypoint': 'sdk-cli', 'client_platform': 'ios'}, 'phone'),
                 ({'entrypoint': 'sdk-cli'}, 'headless'), ({'entrypoint': 'cli'}, 'cli'), ({}, 'unknown')]
        for st, want in cases:
            self.assertEqual(surface(st), want)

    def test_row_waits_for_a_timestamp(self):
        self.assertIsNone(row(new_state('s1')))


class StateTest(unittest.TestCase):
    def test_normalize_remote(self):
        from claude_state import normalize_remote
        for url in ('git@github.com:PiotrRomanczuk/home-ops.git', 'https://github.com/PiotrRomanczuk/home-ops',
                    'ssh://git@github.com/PiotrRomanczuk/home-ops.git/'):
            self.assertEqual(normalize_remote(url), 'PiotrRomanczuk/home-ops')
        self.assertIsNone(normalize_remote('nonsense'))


if __name__ == '__main__':
    unittest.main()
