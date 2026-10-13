"""seo_llm.py — headless Claude Code call for seo-analyse.py / seo-improve.sh.

`claude -p` with the prompt file + metrics JSON on stdin. No tools: the model
answers from the numbers it is given. Any failure (logged-out CLI, timeout,
non-zero exit) returns None so the caller still ships the deterministic card.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

CLAUDE_BIN = os.environ.get('CLAUDE_BIN', 'claude')
CLAUDE_MODEL = os.environ.get('CLAUDE_MODEL', 'sonnet')
CLAUDE_TIMEOUT = int(os.environ.get('CLAUDE_TIMEOUT', '420'))


def build_prompt(template_path: Path, metrics: dict[str, Any], history: list[dict[str, Any]]) -> str:
    tpl = template_path.read_text()
    hist = '\n\n'.join(f"### {h['day']}\n{h['narrative']}" for h in history if h.get('narrative')) or '(brak)'
    return (tpl
            .replace('{{METRICS_JSON}}', json.dumps(metrics, ensure_ascii=False, indent=1))
            .replace('{{HISTORY}}', hist))


def narrate(prompt: str) -> tuple[str | None, str]:
    """Returns (text, model) — text None when the CLI is missing or fails."""
    if not shutil.which(CLAUDE_BIN):
        return None, CLAUDE_MODEL
    cmd = [CLAUDE_BIN, '-p', '--output-format', 'text', '--model', CLAUDE_MODEL,
           '--max-turns', '3', '--tools', '']
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=CLAUDE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, CLAUDE_MODEL
    if r.returncode != 0 or not r.stdout.strip():
        return None, CLAUDE_MODEL
    return r.stdout.strip(), CLAUDE_MODEL
