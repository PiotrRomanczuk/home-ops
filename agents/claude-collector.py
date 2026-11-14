#!/usr/bin/env python3
"""claude-collector — ship what was done with Claude Code on this host to home-ops.

Reads Claude Code transcripts (~/.claude/projects/<cwd>/<session>.jsonl and
<session>/subagents/*.jsonl) from the byte offset reached last run, folds them
into one row per session (claude_transcript.py) and POSTs:
  /api/claude/sessions  {host, sessions:[…], live:[{session_id, status}]}
  /api/claude/events    {host, events:[…]}   prompts, commands, edits, PRs …
Secrets are masked before anything leaves the host (redact.py). Raw
transcripts stay where they are. If a POST fails, the state is not saved and
the next run re-reads the same lines — events are idempotent on their uuid.

One-shot: the Mac runs it from launchd every 5 min, elitedesk from a
systemd timer. The first run backfills everything still on disk.

Env:
  INGEST_URL / INGEST_TOKEN  (required) as every agent
  HOST_NAME                  'mac' on the Mac, 'elitedesk' on uwh
  CLAUDE_HOME                default ~/.claude
  COLLECTOR_STATE            default ~/.local/state/home-ops/claude-collector.json
"""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from typing import Any, Iterator

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))
sys.path.insert(0, str(_here.parent))
from _common import IngestClient  # noqa: E402
import claude_state  # noqa: E402
from claude_transcript import feed, new_state, row  # noqa: E402

HOST_NAME = os.environ.get('HOST_NAME') or socket.gethostname().split('.')[0]
CLAUDE_HOME = Path(os.environ.get('CLAUDE_HOME', '~/.claude')).expanduser()
STATE_PATH = Path(os.environ.get('COLLECTOR_STATE', '~/.local/state/home-ops/claude-collector.json')).expanduser()
DESKTOP = Path('~/Library/Application Support/Claude/claude-code-sessions').expanduser()
SESSIONS_BATCH, EVENTS_BATCH = 200, 500


def transcripts(root: Path) -> Iterator[tuple[Path, str, bool]]:
    for path in sorted(root.glob('*/*.jsonl')):
        yield path, path.stem, False
    for path in sorted(root.glob('*/*/subagents/*.jsonl')):
        yield path, path.parent.parent.name, True


def read_new(st: dict[str, Any], events: list[dict[str, Any]], touched: set[str]) -> None:
    """Feed every line appended since the saved offset; collect touched session ids."""
    for path, sid, side in transcripts(CLAUDE_HOME / 'projects'):
        key = str(path)
        offset = int(st['files'].get(key, 0))
        size = path.stat().st_size
        if size < offset:  # rewritten from scratch: fold the whole session again
            st['files'] = {k: v for k, v in st['files'].items() if sid not in k}
            st['sessions'].pop(sid, None)
            return read_new(st, events, touched)
        if size == offset:
            continue
        with path.open('rb') as f:
            f.seek(offset)
            chunk = f.read(size - offset)
        end = chunk.rfind(b'\n')
        if end < 0:
            continue  # a line still being written
        sess = st['sessions'].setdefault(sid, new_state(sid))
        for line in chunk[:end + 1].decode('utf-8', 'replace').splitlines():
            events.extend(feed(sess, line, side))
        st['files'][key] = offset + end + 1
        touched.add(sid)
    return None


def post(ic: IngestClient, path: str, body: dict[str, Any]) -> bool:
    status, resp = ic.request(ic.events_url.rsplit('/api/', 1)[0] + path, body, timeout=30)
    if not 200 <= status < 300:
        print(f'{path} → {status} {resp}', file=sys.stderr)
    return 200 <= status < 300


def main() -> int:
    ic = IngestClient.from_env(host=HOST_NAME, source='agent:claude-collector')
    st = claude_state.load(STATE_PATH)
    events: list[dict[str, Any]] = []
    touched: set[str] = set()
    read_new(st, events, touched)
    titles = claude_state.desktop_titles(DESKTOP) if DESKTOP.is_dir() else {}
    rows = []
    for sid in sorted(touched):
        r = row(st['sessions'][sid])
        if r:
            r['git_remote'] = claude_state.git_remote(st, r['cwd'])
            r['title'] = r['title'] or titles.get(sid)
            rows.append(r)
    live = claude_state.live_sessions(CLAUDE_HOME / 'sessions')
    for i in range(0, max(len(rows), 1), SESSIONS_BATCH):
        body = {'host': HOST_NAME, 'sessions': rows[i:i + SESSIONS_BATCH], 'live': live}
        if not post(ic, '/api/claude/sessions', body):
            return 1
    for i in range(0, len(events), EVENTS_BATCH):
        if not post(ic, '/api/claude/events', {'host': HOST_NAME, 'events': events[i:i + EVENTS_BATCH]}):
            return 1
    claude_state.save(STATE_PATH, st)
    print(f'claude-collector: {len(rows)} sessions, {len(events)} events, {len(live)} live')
    return 0


if __name__ == '__main__':
    sys.exit(main())
