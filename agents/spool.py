"""spool.py — keep POST bodies on disk while home-ops is unreachable.

A laptop agent loses the server whenever it leaves the LAN or the tunnel is
down. Instead of dropping samples it appends them here (one JSON line per
item: {"path": "/api/metrics", "item": {...}}) and replays them in order once
a POST succeeds again, batched the way the endpoints accept them:
  /api/metrics → {"metrics": [...]}   /api/ingest → {"events": [...]}
Items carry their own ts, so late delivery keeps the timeline right.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

BATCH = 500
WRAP = {'/api/metrics': 'metrics', '/api/ingest': 'events'}

Send = Callable[[str, dict[str, Any]], bool]


class Spool:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, api_path: str, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a') as f:
            for item in items:
                f.write(json.dumps({'path': api_path, 'item': item}, ensure_ascii=False) + '\n')

    def pending(self) -> int:
        try:
            with self.path.open() as f:
                return sum(1 for _ in f)
        except FileNotFoundError:
            return 0

    def flush(self, send: Send) -> bool:
        """Replay everything; stop at the first failed batch and keep the rest.
        Returns True when the spool is empty afterwards."""
        try:
            lines = self.path.read_text().splitlines()
        except FileNotFoundError:
            return True
        recs = []
        for line in lines:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn last line from a crash — drop it
            if isinstance(rec, dict) and rec.get('path') in WRAP:
                recs.append(rec)
        done = 0
        while done < len(recs):
            path = recs[done]['path']
            batch = []
            for rec in recs[done:]:
                if rec['path'] != path or len(batch) >= BATCH:
                    break
                batch.append(rec['item'])
            if not send(path, {WRAP[path]: batch}):
                break
            done += len(batch)
        rest = recs[done:]
        if rest:
            self.path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rest))
        else:
            self.path.unlink(missing_ok=True)
        return not rest
