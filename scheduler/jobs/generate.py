"""kind='generate' — Ollama /api/generate with streaming + mid-stream cancel.

Payload: { model: str, prompt: str, system?: str, options?: dict, think?: bool }
Result:  { response: str, thinking: str, eval_count, total_duration_ns,
           prompt_eval_count, cancelled_mid_stream: bool, partial?: bool }

stream=true so the runner can check `cancel.is_set()` between JSONL chunks
(~one-token-batch granularity, ~50ms). Closing the response body on cancel
breaks Ollama's pipe — it stops generating and frees the runner.

Thinking-model handling: qwen3 (and other reasoning models) stream into a
separate `thinking` field for hundreds of tokens before `response` starts
populating. We capture both. Pass `think: false` in payload to skip the
thinking phase entirely (faster, no chain-of-thought).

Mid-flight streaming: if the runner passes a `partial` callback, we POST
the accumulated `response`/`thinking` to the ingest API every PARTIAL_MS
milliseconds (or every PARTIAL_CHUNKS chunks, whichever fires first). The
UI's polling loop picks these up and the running turn fills in live
instead of staring blank until /complete.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from typing import Any, Callable

OLLAMA_URL = (os.environ.get('OLLAMA_URL') or 'http://127.0.0.1:11434').rstrip('/')

PARTIAL_MS = 250
PARTIAL_CHUNKS = 30


def run(
    job: dict[str, Any],
    cancel: threading.Event,
    *,
    partial: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
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

    last_partial_ms = 0.0
    chunks_since_partial = 0

    def emit_partial() -> None:
        if partial is None:
            return
        try:
            partial({
                'response': ''.join(response_tokens),
                'thinking': ''.join(thinking_tokens),
                'partial': True,
            })
        except Exception:
            # Best-effort. A failed partial post must not kill the job —
            # /complete will still seal the final result.
            pass

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
            chunks_since_partial += 1

            now_ms = time.monotonic() * 1000
            if (
                partial is not None
                and (chunks_since_partial >= PARTIAL_CHUNKS or now_ms - last_partial_ms >= PARTIAL_MS)
            ):
                emit_partial()
                last_partial_ms = now_ms
                chunks_since_partial = 0

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
