"""kind='embed' — one-shot Ollama /api/embed call.

Payload: { model: str, input: str | list[str] }
Result:  { embeddings: list[list[float]], count }

Used for pluggable embedding work (e.g., Stano YT backfill).
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
    body = {'model': p['model'], 'input': p['input']}
    req = urllib.request.Request(
        OLLAMA_URL + '/api/embed',
        data=json.dumps(body).encode(),
        method='POST',
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = json.loads(r.read())
    embs = raw.get('embeddings') or []
    return {'embeddings': embs, 'count': len(embs), 'dim': len(embs[0]) if embs else 0}
