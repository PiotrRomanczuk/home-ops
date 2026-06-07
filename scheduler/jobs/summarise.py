"""kind='summarise' — multi-step LLM summarisation.

Payload: { model: str, chunks: list[str], lang?: str }
Result:  { summary: str, sections: list[{chunk_idx, partial}] }

Demonstrates cooperative pausing — checks `cancel` between chunks.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request
from typing import Any

OLLAMA_URL = (os.environ.get('OLLAMA_URL') or 'http://127.0.0.1:11434').rstrip('/')


def _ollama_generate(model: str, prompt: str, timeout: float = 300) -> str:
    body = {'model': model, 'prompt': prompt, 'stream': False}
    req = urllib.request.Request(
        OLLAMA_URL + '/api/generate',
        data=json.dumps(body).encode(),
        method='POST',
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = json.loads(r.read())
    return str(raw.get('response') or '')


def run(job: dict[str, Any], cancel: threading.Event) -> dict[str, Any]:
    p = job.get('payload') or {}
    model = p['model']
    chunks = list(p.get('chunks') or [])
    lang = p.get('lang', 'pl')

    partials: list[dict[str, Any]] = []
    for i, chunk in enumerate(chunks):
        if cancel.is_set():
            return {'summary': None, 'sections': partials, 'cancelled_at_chunk': i}
        prompt = f'Streść poniższy fragment w jednym akapicie ({lang}):\n\n{chunk}' if lang == 'pl' \
                 else f'Summarise the following in one paragraph ({lang}):\n\n{chunk}'
        out = _ollama_generate(model, prompt)
        partials.append({'chunk_idx': i, 'partial': out})

    if cancel.is_set() or not partials:
        return {'summary': None, 'sections': partials}

    joined = '\n\n'.join(s['partial'] for s in partials)
    final_prompt = f'Połącz poniższe streszczenia w jedno krótkie, spójne podsumowanie ({lang}):\n\n{joined}' if lang == 'pl' \
                   else f'Combine the partial summaries into one short, coherent summary ({lang}):\n\n{joined}'
    summary = _ollama_generate(model, final_prompt)
    return {'summary': summary, 'sections': partials}
