"""seo_db.py — psql access for the SEO jobs through the compose container.

No driver to install: SQL goes over `docker exec psql`, like daily-digest.sh.
Reads come back as JSON (json_agg), writes take psql -v variables so values are
never string-interpolated into SQL.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any

CONTAINER = os.environ.get('CONTAINER', 'home-ops-postgres-1')
DB, DB_USER = os.environ.get('DB', 'home_ops'), os.environ.get('DB_USER', 'postgres')


def psql_json(sql: str) -> list[dict[str, Any]]:
    """Run SQL wrapped in json_agg through the compose container; [] when empty."""
    wrapped = f"SELECT COALESCE(json_agg(t), '[]'::json) FROM ({sql}) t"
    r = subprocess.run(['docker', 'exec', '-i', CONTAINER, 'psql', '-U', DB_USER, '-d', DB, '-X', '-q', '-t', '-A'],
                       input=wrapped, capture_output=True, text=True, check=True)
    return json.loads(r.stdout.strip() or '[]')


def psql_exec(sql: str, params: dict[str, str]) -> None:
    """Parameterised write via psql -v (values are passed as literal variables, not interpolated)."""
    cmd = ['docker', 'exec', '-i', CONTAINER, 'psql', '-U', DB_USER, '-d', DB, '-X', '-q', '-v', 'ON_ERROR_STOP=1']
    for k, v in params.items():
        cmd += ['-v', f'{k}={v}']
    subprocess.run(cmd, input=sql, capture_output=True, text=True, check=True)
