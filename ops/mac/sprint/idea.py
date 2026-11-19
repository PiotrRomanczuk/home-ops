#!/usr/bin/env python3
"""idea.py — add one idea for the Mac to the "## Pomysły" section of the vault note.

    python3 idea.py "tekst"                          # from a terminal or a session
    IDEA_SOURCE=WhatsApp python3 idea.py <<'EOF'     # OpenClaw, a WhatsApp message "mac: …"
    tekst
    EOF

The text is folded to one line, stripped of checkbox and heading marks and capped at 300 characters,
so a message can't smuggle in a ticked box or a new section. The planner turns each unticked line
into a task or a question and marks it.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date
from pathlib import Path

NOTE = Path(os.environ.get('IDEA_NOTE', '~/Obsidian/MainCV-Planner/2-Obszary/homelab/mac-praca-w-tle.md')).expanduser()
HEADING = '## Pomysły'


def clean(text: str) -> str:
    text = ' '.join(text.split())
    text = re.sub(r'^mac:\s*', '', text, flags=re.I)
    text = re.sub(r'\[[ xX]?\]', '', text).replace('#', '')
    return ' '.join(text.split()).strip(' -*>')[:300]


def insert(note: str, line: str) -> str:
    """Add `line` as the last item of the HEADING section (before its trailing blank lines)."""
    lines = note.splitlines()
    start = lines.index(HEADING)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith('## ')), len(lines))
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    lines.insert(end, line)
    return '\n'.join(lines) + '\n'


def main(argv: list[str]) -> int:
    text = clean(' '.join(argv[1:]) if len(argv) > 1 else sys.stdin.read())
    if not text:
        print('Pusty pomysł, nic nie dopisano.')
        return 1
    source = clean(os.environ.get('IDEA_SOURCE', ''))[:30]
    line = f'- [ ] {date.today():%Y-%m-%d} {text}' + (f' ({source})' if source else '')
    NOTE.write_text(insert(NOTE.read_text(), line))
    print(f'Dopisane: {line}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
