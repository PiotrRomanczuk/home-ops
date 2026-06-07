"""kind='generate' — one-shot Ollama generate call.

Payload: { model: str, prompt: str, system?: str, options?: dict }
Result:  { response: str, eval_count, total_duration_ms, prompt_eval_count }
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
    body = {
        'model': p['model'],
        'prompt': p.get('prompt', ''),
        'stream': False,
    }
    if 'system' in p: body['system'] = p['system']
    if 'options' in p: body['options'] = p['options']

    req = urllib.request.Request(
        OLLAMA_URL + '/api/generate',
        data=json.dumps(body).encode(),
        method='POST',
        headers={'Content-Type': 'application/json'},
    )
    # Ollama doesn't natively support mid-call cancellation; rely on the scheduler
    # to pause AFTER the call returns. Long jobs should chunk via multiple kind='generate' inserts.
    with urllib.request.urlopen(req, timeout=600) as r:
        raw = json.loads(r.read())
    return {
        'response': raw.get('response', ''),
        'eval_count': raw.get('eval_count'),
        'total_duration_ns': raw.get('total_duration'),
        'prompt_eval_count': raw.get('prompt_eval_count'),
    }
