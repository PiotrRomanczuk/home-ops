"""kind='summarise' — multi-step LLM summarisation with mid-chunk cancel.

Payload: { model: str, chunks: list[str], lang?: str }
Result:  { summary: str | None, sections: list[{chunk_idx, partial}],
           cancelled_at_chunk?: int, cancelled_mid_stream: bool }

Two levels of cancel responsiveness:
  * between chunks (existing) — natural breakpoint, full chunks already done
  * within an Ollama call — stream=true + check between JSONL lines, so a
    multi-minute chunk can be cancelled within ~50ms instead of waiting for
    the whole paragraph to generate.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request
from typing import Any

OLLAMA_URL = (os.environ.get('OLLAMA_URL') or 'http://127.0.0.1:11434').rstrip('/')


def _ollama_generate_stream(model: str, prompt: str, cancel: threading.Event,
                            timeout: float = 300, think: bool | None = False) -> tuple[str, bool]:
    """Returns (response_text, cancelled_mid_stream). think=False by default
    because reasoning-model chain-of-thought on every chunk doubles cost
    here; the summary use case rarely needs it."""
    body: dict[str, Any] = {'model': model, 'prompt': prompt, 'stream': True}
    if think is not None: body['think'] = think
    req = urllib.request.Request(
        OLLAMA_URL + '/api/generate',
        data=json.dumps(body).encode(),
        method='POST',
        headers={'Content-Type': 'application/json'},
    )
    tokens: list[str] = []
    cancelled = False
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw_line in r:
            if cancel.is_set():
                cancelled = True
                break
            line = raw_line.strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (tok := chunk.get('response')):
                tokens.append(tok)
            if chunk.get('done'):
                break
    return ''.join(tokens), cancelled


def run(
    job: dict[str, Any],
    cancel: threading.Event,
    *,
    partial: Any = None,  # noqa: ARG001  accepted for signature consistency; mid-flight emit is a v2
) -> dict[str, Any]:
    p = job.get('payload') or {}
    model = p['model']
    chunks = list(p.get('chunks') or [])
    lang = p.get('lang', 'pl')

    partials: list[dict[str, Any]] = []
    mid_stream_cancel = False
    for i, chunk in enumerate(chunks):
        if cancel.is_set():
            return {'summary': None, 'sections': partials,
                    'cancelled_at_chunk': i, 'cancelled_mid_stream': mid_stream_cancel}
        prompt = (f'Streść poniższy fragment w jednym akapicie ({lang}):\n\n{chunk}'
                  if lang == 'pl'
                  else f'Summarise the following in one paragraph ({lang}):\n\n{chunk}')
        out, mid = _ollama_generate_stream(model, prompt, cancel)
        partials.append({'chunk_idx': i, 'partial': out})
        if mid:
            mid_stream_cancel = True
            return {'summary': None, 'sections': partials,
                    'cancelled_at_chunk': i, 'cancelled_mid_stream': True}

    if cancel.is_set() or not partials:
        return {'summary': None, 'sections': partials, 'cancelled_mid_stream': mid_stream_cancel}

    joined = '\n\n'.join(s['partial'] for s in partials)
    final_prompt = (f'Połącz poniższe streszczenia w jedno krótkie, spójne podsumowanie ({lang}):\n\n{joined}'
                    if lang == 'pl'
                    else f'Combine the partial summaries into one short, coherent summary ({lang}):\n\n{joined}')
    summary, mid = _ollama_generate_stream(model, final_prompt, cancel)
    return {'summary': summary if not mid else None, 'sections': partials,
            'cancelled_mid_stream': mid}
