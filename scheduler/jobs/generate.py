"""kind='generate' — Ollama /api/generate with streaming + mid-stream cancel.

Payload: { model: str, prompt: str, system?: str, options?: dict, think?: bool }
Result:  { response: str, thinking: str, eval_count, total_duration_ns,
           prompt_eval_count, cancelled_mid_stream: bool }

stream=true so the runner can check `cancel.is_set()` between JSONL chunks
(~one-token-batch granularity, ~50ms). Closing the response body on cancel
breaks Ollama's pipe — it stops generating and frees the runner.

Thinking-model handling: qwen3 (and other reasoning models) stream into a
separate `thinking` field for hundreds of tokens before `response` starts
populating. We capture both. Pass `think: false` in payload to skip the
thinking phase entirely (faster, no chain-of-thought).
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request
from typing import Any

OLLAMA_URL = (os.environ.get('OLLAMA_URL') or 'http://127.0.0.1:11434').rstrip('/')


def run(job: dict[str, Any], cancel: threading.Event) -> dict[str, Any]:
    p = job.get('payload') or {}
    body: dict[str, Any] = {
        'model': p['model'],
        'prompt': p.get('prompt', ''),
        'stream': True,
    }
    if 'system' in p: body['system'] = p['system']
    if 'options' in p: body['options'] = p['options']
    if 'think' in p: body['think'] = p['think']

    req = urllib.request.Request(
        OLLAMA_URL + '/api/generate',
        data=json.dumps(body).encode(),
        method='POST',
        headers={'Content-Type': 'application/json'},
    )

    response_tokens: list[str] = []
    thinking_tokens: list[str] = []
    final: dict[str, Any] | None = None
    cancelled = False
    with urllib.request.urlopen(req, timeout=600) as r:
        for raw_line in r:
            if cancel.is_set():
                cancelled = True
                break  # exiting the `with` closes the connection → Ollama
                       # sees broken pipe on next write and drops the runner
            line = raw_line.strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (tok := chunk.get('response')):
                response_tokens.append(tok)
            if (thought := chunk.get('thinking')):
                thinking_tokens.append(thought)
            if chunk.get('done'):
                final = chunk
                break

    return {
        'response': ''.join(response_tokens),
        'thinking': ''.join(thinking_tokens),
        'eval_count': final.get('eval_count') if final else None,
        'total_duration_ns': final.get('total_duration') if final else None,
        'prompt_eval_count': final.get('prompt_eval_count') if final else None,
        'cancelled_mid_stream': cancelled,
    }
