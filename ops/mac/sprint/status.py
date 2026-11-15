#!/usr/bin/env python3
"""status.py — a phone-sized status page for the Mac worker.

One stdlib HTTP server that renders the state directory on each request (no build step, no
framework), until the data lives in home-ops proper. Routes:
  GET  /            budget, counts, running tasks, GPU supervisor, last runs, failed, "Czeka na Piotra"
  GET  /r/<id>      one task's result file
  POST /stop        creates the STOP file (workers finish their task and quit)

Env: SPRINT_STATE (as runner.py), SPRINT_STATUS_PORT (8787),
SPRINT_STATUS_HOST (127.0.0.1; 0.0.0.0 = whole LAN, no login — the page shows task results).
"""
from __future__ import annotations

import html
import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import sprint_tasks as q
import status_panels as panels

STATE = Path(os.environ.get('SPRINT_STATE', '~/.local/state/home-ops/sprint')).expanduser()
PORT = int(os.environ.get('SPRINT_STATUS_PORT', '8787'))
HOST = os.environ.get('SPRINT_STATUS_HOST', '127.0.0.1')  # set 0.0.0.0 to reach it from the phone on the LAN
CSS = ('body{margin:0;padding:12px;background:#0e1116;color:#d0d7de;font:15px/1.45 -apple-system,sans-serif}'
       'h1{font-size:18px;margin:0 0 8px}h2{font-size:13px;text-transform:uppercase;color:#8b949e;margin:18px 0 6px}'
       '.t{display:flex;gap:8px;flex-wrap:wrap}.t div{background:#161b22;border:1px solid #30363d;border-radius:8px;'
       'padding:8px 12px;min-width:70px}.t b{display:block;font:600 20px ui-monospace,monospace}'
       '.t span{font-size:11px;color:#8b949e}table{border-collapse:collapse;width:100%;font-size:13px}'
       'td,th{text-align:left;padding:5px 6px;border-bottom:1px solid #21262d;vertical-align:top}'
       'th{color:#8b949e;font-weight:500}a{color:#58a6ff;text-decoration:none}.m{font-family:ui-monospace,monospace}'
       '.bad{color:#f85149}.ok{color:#3fb950}.dim{color:#8b949e}pre{white-space:pre-wrap;word-break:break-word}'
       'button{background:#21262d;color:#f85149;border:1px solid #f85149;border-radius:8px;padding:8px 14px;font-size:14px}'
       'li{margin:3px 0}ul{padding-left:18px;margin:4px 0}')
e = html.escape


def runs(n: int = 30) -> list[dict]:
    try:
        lines = (STATE / 'logs' / 'runs.jsonl').read_text().splitlines()[-n:]
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in reversed(lines)]


def waiting() -> list[tuple[str, str]]:
    """Bullets under '## Czeka na Piotra' in every result file, newest file first."""
    out = []
    for path in sorted((STATE / 'results').glob('*.md'), key=lambda p: -p.stat().st_mtime):
        m = re.search(r'^## Czeka na Piotra\s*\n(.*?)(?=^## |\Z)', path.read_text(errors='replace'), re.S | re.M)
        for line in (m.group(1).splitlines() if m else []):
            line = line.strip()
            if line.startswith('- ') and len(line) > 4 and line[2:].strip().lower() not in ('brak', 'nic', '…', '—'):
                out.append((path.stem, line[2:]))
    return out[:60]


def page() -> str:
    count = {d: len(list((STATE / d).glob('*.md'))) for d in ('queue', 'running', 'done', 'failed')}
    all_runs = runs(2000)
    cost = sum((r['res'].get('total_cost_usd') or 0) for r in all_runs)
    state = 'ZATRZYMANY' if (STATE / 'STOP').exists() else 'działa'
    budget_tiles, why = panels.budget_tiles(STATE)
    why = 'zatrzymani plikiem STOP' if (STATE / 'STOP').exists() else why
    tiles = [(count['running'], 'w toku'), (count['queue'], 'w kolejce'), (count['done'], 'zrobione'),
             (count['failed'], 'nieudane'), *budget_tiles, (f'{cost:.0f} $', 'wartość wg cennika')]
    out = [f'<h1>Mac worker · {e(state)}</h1><div class="t">',
           *[f'<div><b>{e(str(v))}</b><span>{e(k)}</span></div>' for v, k in tiles],
           f'</div><p class="dim">Agenci Claude: {e(why)}</p><h2>GPU</h2>{panels.gpu_html(STATE)}<h2>W toku</h2><table>']
    for p in sorted((STATE / 'running').glob('*.md')):
        t = q.parse(p)
        mins = int((time.time() - p.stat().st_mtime) / 60)
        out.append(f'<tr><td class="m">{e(t["id"])}</td><td>{e(str(t.get("model")))}</td><td class="dim">{mins} min</td></tr>')
    out.append('</table><h2>Ostatnie przebiegi</h2><table><tr><th>kiedy</th><th>zadanie</th><th>model</th><th>min</th><th>$</th><th></th></tr>')
    for r in all_runs[:30]:
        cls = 'ok' if r['outcome'] == 'done' else 'bad'
        link = f'<a href="/r/{e(r["id"])}">{e(r["id"])}</a>' if (STATE / 'results' / f'{r["id"]}.md').exists() else e(r['id'])
        out.append(f'<tr><td class="dim">{e(r["ts"][5:16].replace("T", " "))}</td><td class="m">{link}</td><td>{e(r["model"])}</td>'
                   f'<td>{r["seconds"] // 60}</td><td>{(r["res"].get("total_cost_usd") or 0):.2f}</td><td class="{cls}">{e(r["outcome"])}</td></tr>')
    out.append('</table><h2>Czeka na Piotra</h2><ul>')
    out += [f'<li>{e(text)} <a class="dim" href="/r/{e(tid)}">({e(tid)})</a></li>' for tid, text in waiting()] or ['<li class="dim">nic</li>']
    out.append('</ul><h2>Nieudane</h2><ul>')
    out += [f'<li class="m">{e(p.stem)}</li>' for p in sorted((STATE / 'failed').glob('*.md'))] or ['<li class="dim">brak</li>']
    out.append('</ul><h2>Wyłącznik</h2><form method="post" action="/stop" onsubmit="return confirm(\'Zatrzymać agentów?\')">'
               '<button>Zatrzymaj agentów Claude</button></form>')
    return ''.join(out)


class Handler(BaseHTTPRequestHandler):
    def send(self, body: str, refresh: bool = False) -> None:
        meta = '<meta http-equiv="refresh" content="30">' if refresh else ''
        doc = (f'<!doctype html><html lang="pl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
               f'initial-scale=1">{meta}<title>Mac worker</title><style>{CSS}</style>{body}</html>').encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(doc)))
        self.end_headers()
        self.wfile.write(doc)

    def do_GET(self) -> None:  # noqa: N802
        m = re.fullmatch(r'/r/([A-Za-z0-9._-]+)', self.path)
        path = STATE / 'results' / f'{m.group(1)}.md' if m else None
        if path and path.is_file():
            self.send(f'<p><a href="/">← sprint</a></p><pre>{e(path.read_text(errors="replace"))}</pre>')
        else:
            self.send(page(), refresh=True)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == '/stop':
            (STATE / 'STOP').touch()
        self.send_response(303)
        self.send_header('Location', '/')
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


if __name__ == '__main__':
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
