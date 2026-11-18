"""Golden (characterisation) test for planner-sync, through its entry points.

2026-11-17 — pins the externally visible behaviour of `sync_once()` and one
pass of the toggle drain BEFORE planner-sync.py is split into modules
(analysis 2026-11-16-home-ops-planner-sync-podzial, task hops-ps-00).

Real pieces: the module itself (loaded with importlib, env read at import),
git against a temporary bare remote, the on-disk state files. Faked: ingest —
a ThreadingHTTPServer on 127.0.0.1:<random> that records every request and
keeps a tiny stateful board. No network beyond loopback, no real vault, no uwh.

Asserted: what reaches ingest (projects, Now/Next/Later, queue, toggle marks,
Postęp signals), what is written and pushed to the vault, and where the state
files live (`STATE_FILE`, `{PLANNER_DIR}.ticks.json`). Internal names are not
asserted, except the toggle drain which has no public name yet.

Run:
    python3 -m unittest agents.tests.test_planner_sync_golden -v
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import tempfile
import threading
import unittest
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TOKEN = 'golden-token'

HOME_OPS_MD = """---
status: hot
path: ~/code/homelab/home-ops
last_commit: 2026-11-16
commits_30d: 12
updated: 2026-11-16
---

# home-ops

## Now
- [ ] first now task
- [ ] second now task

## Next
- [ ] next task

## Later
- [x] later task already done

## Pain points
- one pain

## Notes
free text
"""

P_MD = """---
status: warm
---

# P project

## Now
- [ ] p now task
"""

QUEUE_MD = """# Kolejka

## Kolejka
- [ ] 🎯 M [[home-ops]] HO-1 coś do zrobienia
"""

IGNORED_DATED_MD = '---\nstatus: hot\n---\n\n# dated snapshot\n\n## Now\n- [ ] x\n'
IGNORED_NO_STATUS_MD = '---\ntype: reference\n---\n\n# reference page\n\n## Now\n- [ ] y\n'


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f'git {args} failed: {r.stderr}'
    return r.stdout


class FakeIngest:
    """Loopback ingest: records requests, answers like the real API would."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.toggles: list[dict[str, Any]] = []
        self.boards: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a: Any) -> None:  # silence
                pass

            def _serve(self, method: str) -> None:
                url = urlparse(self.path)
                length = int(self.headers.get('Content-Length') or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                with fake._lock:
                    fake.requests.append({
                        'method': method, 'path': url.path, 'query': parse_qs(url.query),
                        'body': body, 'token': self.headers.get('X-Ingest-Token'),
                    })
                    payload = fake._answer(method, url.path, parse_qs(url.query), body)
                raw = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:  # noqa: N802
                self._serve('GET')

            def do_POST(self) -> None:  # noqa: N802
                self._serve('POST')

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.url = f'http://127.0.0.1:{self.port}/api/ingest'
        self._thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _answer(self, method: str, path: str, query: dict[str, list[str]], body: Any) -> dict[str, Any]:
        if method == 'GET' and path == '/api/task_toggles':
            return {'toggles': list(self.toggles)}
        if method == 'GET' and path == '/api/board/slugs':
            return {'slugs': []}
        if method == 'GET' and path == '/api/board':
            return self.boards.get(query['slug'][0], {'tasks': [], 'updatedAt': None})
        if method == 'POST' and path == '/api/board/import':
            rows = [{'id': i + 1, 'column_key': t['column'], 'position': i, 'text': t['text'],
                     'done': t['done'], 'is_focus': False} for i, t in enumerate(body['tasks'])]
            stamp = f'w{len(self.requests)}'
            self.boards[body['slug']] = {'tasks': rows, 'updatedAt': stamp}
            return {'updatedAt': stamp}
        m = re.fullmatch(r'/api/task_toggles/(\d+)/mark', path)
        if method == 'POST' and m:
            self.toggles = [t for t in self.toggles if t['id'] != int(m.group(1))]
            return {}
        if method == 'POST' and path == '/api/projects/sync':
            return {'upserted': len(body['projects']), 'removed': 0}
        if method == 'POST' and path == '/api/queue/sync':
            return {'status': 'ok'}
        return {}

    def calls(self, method: str, path: str) -> list[dict[str, Any]]:
        with self._lock:
            return [r for r in self.requests if r['method'] == method and r['path'] == path]

    def count(self) -> int:
        with self._lock:
            return len(self.requests)


class PlannerSyncGolden(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        # Isolate git from the user's config (signing, hooks, default branch).
        self._env = {
            'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_AUTHOR_NAME': 'obsidian', 'GIT_AUTHOR_EMAIL': 'o@example.com',
            'GIT_COMMITTER_NAME': 'obsidian', 'GIT_COMMITTER_EMAIL': 'o@example.com',
            'no_proxy': '127.0.0.1', 'NO_PROXY': '127.0.0.1',
        }

        self.ingest = FakeIngest()
        self.ingest.start()
        self.addCleanup(self.ingest.stop)

        self.remote = self.tmp / 'vault.git'
        self.mirror = self.tmp / 'mirror'           # PLANNER_DIR — created by planner-sync
        self.other = self.tmp / 'other'             # the Obsidian side
        self.state_file = self.tmp / 'board-state.json'
        self._seed_vault()

        self._patch_env(STATE_FILE=str(self.state_file))
        self.ps = self._load()

    # ── fixtures ──────────────────────────────────────────────────────

    def _patch_env(self, **extra: str) -> None:
        env = {
            **self._env,
            'INGEST_URL': self.ingest.url, 'INGEST_TOKEN': TOKEN,
            'PLANNER_DIR': str(self.mirror), 'PLANNER_REMOTE': str(self.remote),
        }
        env.update(extra)
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ('STATE_FILE', 'PROJECT_DIRS', 'QUEUE_FILE', 'BOARD_SLUG', 'HOST_NAME'):
            if name not in extra:
                os.environ.pop(name, None)

    def _seed_vault(self) -> None:
        with mock.patch.dict(os.environ, self._env):
            subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(self.remote)], check=True)
            subprocess.run(['git', 'clone', '-q', str(self.remote), str(self.other)],
                           capture_output=True, check=True)
            files = {
                '2-Obszary/homelab/home-ops.md': HOME_OPS_MD,
                '1-Projekty/p.md': P_MD,
                '1-Projekty/2026-11-01-ignored.md': IGNORED_DATED_MD,
                '1-Projekty/reference.md': IGNORED_NO_STATUS_MD,
                'QUEUE.md': QUEUE_MD,
            }
            for rel, text in files.items():
                path = self.other / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding='utf-8')
            _git(self.other, 'checkout', '-q', '-b', 'main')
            _git(self.other, 'add', '-A')
            _git(self.other, 'commit', '-q', '-m', 'seed vault')
            _git(self.other, 'push', '-q', '-u', 'origin', 'main')

    def _load(self) -> Any:
        """Fresh module instance — env is read at import, state is module-level."""
        spec = importlib.util.spec_from_file_location(
            'planner_sync_golden', REPO_ROOT / 'agents' / 'elitedesk' / 'planner-sync.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    # ── helpers ───────────────────────────────────────────────────────

    def _obsidian_edit(self, rel: str, old: str, new: str, msg: str = 'obsidian edit') -> None:
        with mock.patch.dict(os.environ, self._env):
            _git(self.other, 'pull', '-q', '--ff-only')
            path = self.other / rel
            text = path.read_text(encoding='utf-8')
            assert old in text
            path.write_text(text.replace(old, new), encoding='utf-8')
            _git(self.other, 'commit', '-q', '-am', msg)
            _git(self.other, 'push', '-q')

    def _remote_file(self, rel: str) -> str:
        with mock.patch.dict(os.environ, self._env):
            return _git(self.remote, 'show', f'main:{rel}')

    def _remote_subjects(self) -> list[str]:
        with mock.patch.dict(os.environ, self._env):
            return _git(self.remote, 'log', '--format=%s', 'main').splitlines()

    def _drain(self) -> None:
        # Today the drain is private; hops-ps-06 will expose drain_toggles_once.
        fn = getattr(self.ps, 'drain_toggles_once', None) or self.ps._drain_toggles_once
        fn()

    def _projects(self) -> dict[str, dict[str, Any]]:
        last = self.ingest.calls('POST', '/api/projects/sync')[-1]
        return {r['slug']: r for r in last['body']['projects']}

    # ── sync_once ─────────────────────────────────────────────────────

    def test_first_tick_posts_projects_queue_and_creates_state_files(self) -> None:
        self.ps.sync_once()

        self.assertTrue((self.mirror / '.git').exists(), 'clone created from PLANNER_REMOTE')
        syncs = self.ingest.calls('POST', '/api/projects/sync')
        self.assertEqual(len(syncs), 1)
        projects = self._projects()
        self.assertEqual(set(projects), {'home-ops', 'p'})  # dated note + no-status note excluded
        ho = projects['home-ops']
        self.assertEqual(ho['title'], 'home-ops')
        self.assertEqual(ho['status'], 'hot')
        self.assertEqual(ho['commits_30d'], 12)
        self.assertEqual(ho['last_commit'], '2026-11-16')
        self.assertEqual(ho['now_md'], '- [ ] first now task\n- [ ] second now task')
        self.assertEqual(ho['next_md'], '- [ ] next task')
        self.assertEqual(ho['later_md'], '- [x] later task already done')
        self.assertEqual(ho['pain_md'], '- one pain')
        self.assertEqual(ho['notes_md'], 'free text')
        self.assertEqual(projects['p']['status'], 'warm')
        self.assertEqual(projects['p']['now_md'], '- [ ] p now task')

        queue = self.ingest.calls('POST', '/api/queue/sync')
        self.assertEqual(len(queue), 1)
        self.assertIn('summary', queue[0]['body'])
        self.assertEqual(len(queue[0]['body']['source_hash']), 32)

        # board seeded from the vault into the (empty) board, state persisted
        imports = self.ingest.calls('POST', '/api/board/import')
        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0]['body']['slug'], 'home-ops')
        self.assertEqual(
            [(t['column'], t['text'], t['done']) for t in imports[0]['body']['tasks']],
            [('now', 'first now task', False), ('now', 'second now task', False),
             ('next', 'next task', False), ('later', 'later task already done', True)])
        state = json.loads(self.state_file.read_text(encoding='utf-8'))
        self.assertEqual(set(state), {'home-ops'})
        self.assertEqual(set(state['home-ops']), {'watermark', 'hash'})
        self.assertEqual(state['home-ops']['watermark'], self.ingest.boards['home-ops']['updatedAt'])

        ticks = Path(f'{self.mirror}.ticks.json')
        self.assertTrue(ticks.exists())
        self.assertEqual(set(json.loads(ticks.read_text(encoding='utf-8'))), {'home-ops', 'p'})
        self.assertEqual(self.ingest.calls('POST', '/api/progress/signals'), [])  # baseline only

        for r in self.ingest.requests:
            self.assertEqual(r['token'], TOKEN)
        # nothing to write back: the vault history is untouched
        self.assertEqual(self._remote_subjects(), ['seed vault'])

    def test_state_file_defaults_next_to_planner_dir(self) -> None:
        self._patch_env()  # STATE_FILE unset
        ps = self._load()
        ps.sync_once()
        self.assertTrue(Path(f'{self.mirror}.state.json').exists())
        self.assertFalse(self.state_file.exists())

    def test_second_tick_without_changes_does_not_repost_queue(self) -> None:
        self.ps.sync_once()
        self.ps.sync_once()
        self.assertEqual(len(self.ingest.calls('POST', '/api/queue/sync')), 1)
        self.assertEqual(len(self.ingest.calls('POST', '/api/projects/sync')), 2)  # projects: every tick
        self.assertEqual(len(self.ingest.calls('POST', '/api/board/import')), 1)
        self.assertEqual(self._remote_subjects(), ['seed vault'])

    def test_obsidian_edit_reaches_projects_board_and_signals(self) -> None:
        self.ps.sync_once()
        self._obsidian_edit('2-Obszary/homelab/home-ops.md',
                            '- [ ] next task\n', '- [ ] next task\n- [ ] added in obsidian\n')
        self.ps.sync_once()

        self.assertEqual(self._projects()['home-ops']['next_md'],
                         '- [ ] next task\n- [ ] added in obsidian')
        imports = self.ingest.calls('POST', '/api/board/import')
        self.assertEqual(len(imports), 2)  # seed + Obsidian edit imported into the board
        self.assertIn('added in obsidian', [t['text'] for t in imports[-1]['body']['tasks']])
        state = json.loads(self.state_file.read_text(encoding='utf-8'))
        self.assertEqual(state['home-ops']['watermark'], self.ingest.boards['home-ops']['updatedAt'])
        signals = self.ingest.calls('POST', '/api/progress/signals')
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['body'], {'rows': [
            {'project_slug': 'home-ops', 'day': date.today().isoformat(), 'signal': 'tasks_added', 'n': 1}]})
        self.assertIn('added in obsidian', self._remote_file('2-Obszary/homelab/home-ops.md'))
        self.assertEqual(self._remote_subjects()[0], 'obsidian edit')  # no commit from planner-sync

    def test_board_change_is_rendered_into_vault_and_pushed(self) -> None:
        self.ps.sync_once()
        self.ingest.boards['home-ops'] = {'updatedAt': 'db-1', 'tasks': [
            {'id': 1, 'column_key': 'now', 'position': 0, 'text': 'db task one', 'done': False},
            {'id': 2, 'column_key': 'now', 'position': 1, 'text': 'db task two', 'done': True},
            {'id': 3, 'column_key': 'later', 'position': 0, 'text': 'db later', 'done': False}]}
        self.ps.sync_once()

        text = self._remote_file('2-Obszary/homelab/home-ops.md')
        self.assertIn('## Now\n\n- [ ] db task one\n- [x] db task two\n\n## Next\n\n\n## Later\n\n- [ ] db later\n',
                      text)
        self.assertIn('## Pain points\n- one pain', text)  # unmanaged sections untouched
        self.assertTrue(text.startswith('---\nstatus: hot\n'))
        self.assertEqual(self._remote_subjects()[0], 'board sync: home-ops')
        self.assertEqual(self._projects()['home-ops']['now_md'], '- [ ] db task one\n- [x] db task two')
        state = json.loads(self.state_file.read_text(encoding='utf-8'))
        self.assertEqual(state['home-ops']['watermark'], 'db-1')
        # the mirror is clean and level with the remote
        with mock.patch.dict(os.environ, self._env):
            self.assertEqual(_git(self.mirror, 'status', '--porcelain'), '')
            self.assertEqual(_git(self.mirror, 'rev-parse', 'HEAD'), _git(self.remote, 'rev-parse', 'main'))

    def test_restart_keeps_state_and_does_not_overwrite_obsidian_edit(self) -> None:
        self.ps.sync_once()
        self._obsidian_edit('2-Obszary/homelab/home-ops.md', '- [ ] next task', '- [ ] next task edited')
        restarted = self._load()  # state comes back from STATE_FILE
        restarted.sync_once()

        self.assertIn('next task edited', self._remote_file('2-Obszary/homelab/home-ops.md'))
        self.assertEqual(self._remote_subjects()[0], 'obsidian edit')  # "DB wins" branch not taken
        self.assertEqual(len(self.ingest.calls('POST', '/api/board/import')), 2)
        self.assertIn('next task edited',
                      [t['text'] for t in self.ingest.calls('POST', '/api/board/import')[-1]['body']['tasks']])

    # ── toggle drain ──────────────────────────────────────────────────

    def _queue_toggle(self, **kw: Any) -> None:
        self.ingest.toggles = [{'id': 7, 'slug': 'home-ops', 'section': 'Now', 'idx': 1,
                                'done': True, 'text': 'second now task', **kw}]

    def test_toggle_is_applied_committed_pushed_and_marked(self) -> None:
        self.ps.sync_once()
        self._queue_toggle()
        self._drain()

        marks = self.ingest.calls('POST', '/api/task_toggles/7/mark')
        self.assertEqual([m['body'] for m in marks], [{'status': 'applied', 'error': None}])
        text = self._remote_file('2-Obszary/homelab/home-ops.md')
        self.assertIn('- [ ] first now task\n- [x] second now task\n', text)
        self.assertEqual(self._remote_subjects()[0], 'task toggle: home-ops/Now/1 → done')
        self.assertEqual(self.ingest.toggles, [])
        self.assertEqual(self.ingest.calls('GET', '/api/task_toggles')[0]['query']['status'], ['queued'])
        # the checkbox shows up as a tick on the next tick (Postęp)
        self.ps.sync_once()
        signals = self.ingest.calls('POST', '/api/progress/signals')
        self.assertEqual(signals[-1]['body']['rows'],
                         [{'project_slug': 'home-ops', 'day': date.today().isoformat(),
                           'signal': 'tasks_done', 'n': 1}])

    def test_toggle_back_to_open_unticks_the_task(self) -> None:
        self.ps.sync_once()
        self._queue_toggle(section='Later', idx=0, done=False, text='later task already done')
        self._drain()

        self.assertIn('- [ ] later task already done', self._remote_file('2-Obszary/homelab/home-ops.md'))
        self.assertEqual(self._remote_subjects()[0], 'task toggle: home-ops/Later/0 → open')
        self.assertEqual(self.ingest.calls('POST', '/api/task_toggles/7/mark')[0]['body']['status'], 'applied')

    def test_toggle_already_in_desired_state_is_applied_without_commit(self) -> None:
        self.ps.sync_once()
        self._queue_toggle(section='Later', idx=0, done=True, text='later task already done')
        self._drain()

        self.assertEqual(self.ingest.calls('POST', '/api/task_toggles/7/mark')[0]['body']['status'], 'applied')
        self.assertEqual(self._remote_subjects(), ['seed vault'])

    def test_toggle_failures_are_marked_failed(self) -> None:
        self.ps.sync_once()
        self._queue_toggle(slug='no-such-project')
        self._drain()
        body = self.ingest.calls('POST', '/api/task_toggles/7/mark')[0]['body']
        self.assertEqual(body['status'], 'failed')
        self.assertIn('no-such-project.md not found', body['error'])

        self._queue_toggle(idx=9, text='gone')
        self._drain()
        body = self.ingest.calls('POST', '/api/task_toggles/7/mark')[1]['body']
        self.assertEqual(body['status'], 'failed')
        self.assertIn('task not found', body['error'])
        self.assertEqual(self._remote_subjects(), ['seed vault'])

    def test_toggle_rejected_push_is_marked_conflict_and_logged(self) -> None:
        self.ps.sync_once()
        hook = self.remote / 'hooks' / 'pre-receive'
        hook.write_text('#!/bin/sh\nexit 1\n', encoding='utf-8')
        hook.chmod(0o755)
        self._queue_toggle()
        self._drain()

        body = self.ingest.calls('POST', '/api/task_toggles/7/mark')[0]['body']
        self.assertEqual(body['status'], 'conflict')
        self.assertIn('git push', body['error'])
        self.assertEqual(self._remote_subjects(), ['seed vault'])  # nothing reached the remote
        warns = [e for r in self.ingest.calls('POST', '/api/ingest') for e in r['body']['events']
                 if e['level'] == 'warn' and 'vault conflict on task toggle' in e['message']]
        self.assertEqual(len(warns), 1)
        self.assertEqual(warns[0]['data']['slug'], 'home-ops')
        self.assertEqual((warns[0]['data']['section'], warns[0]['data']['idx']), ('Now', 1))

    def test_drain_with_empty_queue_changes_nothing(self) -> None:
        self.ps.sync_once()
        before = self.ingest.count()
        self._drain()
        self.assertEqual(self.ingest.count(), before + 1)  # just the GET
        self.assertEqual(self.ingest.requests[-1]['path'], '/api/task_toggles')


if __name__ == '__main__':
    unittest.main()
