"""gmail_db.py — Postgres side of the Gmail cleanup (schema `gmail`, migration 025).

Same transport as seo_db: SQL over `docker exec psql`, no driver to install.
Bulk loads go through COPY FROM STDIN into a staging table, then an upsert, so
107k rows take seconds. Pure helpers (row shaping, journal flattening) are
separate from the psql calls so they can be unit-tested.
"""
from __future__ import annotations

import csv
import io
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from seo_db import psql_json

CONTAINER = os.environ.get('CONTAINER', 'home-ops-postgres-1')
DB, DB_USER = os.environ.get('DB', 'home_ops'), os.environ.get('DB_USER', 'postgres')
MESSAGE_COLS = ('id', 'thread_id', 'internal_at', 'size_bytes', 'from_addr', 'from_name', 'from_domain',
                'to_addrs', 'subject', 'has_unsub', 'gmail_labels')
APPLIED_COLS = ('journal', 'line_no', 'message_id', 'op', 'label', 'had_inbox', 'note', 'ts')
STATE_COLS = ('message_id', 'category', 'subcategory', 'reason', 'in_trash', 'in_inbox', 'unread', 'protected')


def psql_script(script: str) -> str:
    """Run a multi-statement psql script (may contain COPY … FROM STDIN blocks) in one transaction."""
    r = subprocess.run(['docker', 'exec', '-i', CONTAINER, 'psql', '-U', DB_USER, '-d', DB, '-X', '-q',
                        '-v', 'ON_ERROR_STOP=1', '-1'], input=script, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:800])
    return r.stdout


def _iso(ms: int | None) -> str:
    return datetime.fromtimestamp((ms or 0) / 1000, tz=timezone.utc).isoformat()


def message_row(r: Any) -> tuple:
    """SQLite `messages` row (sqlite3.Row or 11-tuple) -> gmail.message columns."""
    r = tuple(r)
    return (r[0], r[1], _iso(r[2]), r[3] or 0, r[4] or '', r[5] or '', r[6] or '', r[7] or '', r[8] or '',
            bool(r[9]), r[10] or '')


def journal_rows(path: Path) -> list[tuple]:
    """Flatten one JSONL undo journal into gmail.applied rows (one per message)."""
    out: list[tuple] = []
    for line_no, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        e = json.loads(line)
        op, ts = e['op'], _iso(e['ts'] * 1000)
        label = e.get('label') or {'trash': 'TRASH', 'archive': 'INBOX', 'read': 'UNREAD'}.get(op) or e.get('label_id')
        inbox = set(e.get('inbox_ids', ()))
        for i in e.get('ids', ()):
            out.append((path.name, line_no, i, op, label, i in inbox, e.get('note'), ts))
        if not e.get('ids'):  # label-level ops (rename, delete, visibility) — one row, no message
            out.append((path.name, line_no, '', op, e.get('label') or e.get('from'), False, json.dumps(e, ensure_ascii=False)[:300], ts))
    return out


def copy_block(table: str, cols: tuple[str, ...], rows: list[tuple]) -> str:
    """`COPY table (cols) FROM STDIN` + CSV body + terminator, for psql_script."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    for r in rows:
        w.writerow(['\\N' if v is None else ('t' if v is True else 'f' if v is False else v) for v in r])
    return f"COPY {table} ({', '.join(cols)}) FROM STDIN WITH (FORMAT csv, NULL '\\N');\n{buf.getvalue()}\\.\n"


def upsert_messages(rows: list[tuple]) -> int:
    if not rows:
        return 0
    cols = ', '.join(MESSAGE_COLS)
    sets = ', '.join(f'{c} = EXCLUDED.{c}' for c in MESSAGE_COLS[1:])
    psql_script(f"CREATE TEMP TABLE stage (LIKE gmail.message INCLUDING DEFAULTS) ON COMMIT DROP;\n"
                + copy_block('stage', MESSAGE_COLS, rows)
                + f"INSERT INTO gmail.message ({cols}) SELECT {cols} FROM stage ON CONFLICT (id) DO UPDATE SET {sets};\n")
    return len(rows)


def insert_applied(rows: list[tuple]) -> int:
    if not rows:
        return 0
    psql_script("CREATE TEMP TABLE stage (LIKE gmail.applied) ON COMMIT DROP;\n"
                + copy_block('stage', APPLIED_COLS, rows)
                + "INSERT INTO gmail.applied SELECT * FROM stage ON CONFLICT DO NOTHING;\n")
    return len(rows)


def replace_state(rows: list[tuple]) -> int:
    """Rewrite gmail.message_state wholesale (it is derived; ~33k rows)."""
    psql_script("TRUNCATE gmail.message_state;\n" + copy_block('gmail.message_state', STATE_COLS, rows))
    return len(rows)


def load_rules() -> dict:
    """The rules JSON (same shape as gmail-rules.json) assembled by gmail.rules_json()."""
    out = psql_json('SELECT gmail.rules_json() AS r')
    return out[0]['r'] if out else {}


def import_rules(raw: dict) -> int:
    """Replace gmail.rule + gmail.config with the contents of a rules JSON dict."""
    rows = [(n, 'rule', None, r['label'], '{' + ','.join(r.get('from', [])) + '}', r.get('subject'),
             bool(r.get('automated_only')), True, None) for n, r in enumerate(raw['rules'])]
    rows += [(n, 'subrule', r['parent'], r['label'], '{' + ','.join(r.get('from', [])) + '}', r.get('subject'),
              False, True, None) for n, r in enumerate(raw.get('subrules', []))]
    cfg = [(k, json.dumps(raw[k], ensure_ascii=False)) for k in ('_doc', 'me', 'freemail', 'protect') if k in raw]
    psql_script("TRUNCATE gmail.rule, gmail.config;\n"
                + copy_block('gmail.rule', ('position', 'kind', 'parent', 'label', 'senders', 'subject', 'automated_only', 'enabled', 'note'), rows)
                + copy_block('gmail.config', ('key', 'value'), cfg))
    return len(rows)
