"""Run SQL through psql, wherever psql is.

Production: `ssh uwh docker exec -i home-ops-postgres-1 psql -U postgres -d home_ops` (the song2logic
pattern: no driver, no password, no open port). Tests: `docker exec -i <container> psql …` or
`psql postgresql://…`. The command comes from an argument, else $DATASET_PSQL, else DEFAULT."""

import json
import os
import shlex
import subprocess
from collections.abc import Sequence

DEFAULT = "ssh -o ConnectTimeout=10 uwh docker exec -i home-ops-postgres-1 psql -U postgres -d home_ops"
FLAGS = ("-X", "-q", "-At", "-v", "ON_ERROR_STOP=1")


class PsqlError(RuntimeError):
    """psql exited non-zero; the open transaction was rolled back with the connection."""


def command(spec: str | None = None) -> list[str]:
    """The psql command as an argument list (off the home LAN pass `ssh … uwo …`)."""
    return shlex.split(spec or os.environ.get("DATASET_PSQL") or DEFAULT)


def run(script: str, psql: Sequence[str]) -> list[str]:
    """Feed `script` to psql on stdin; return the non-empty output lines."""
    done = subprocess.run([*psql, *FLAGS], input=script, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise PsqlError(done.stderr.strip()[-800:] or f"psql exited with {done.returncode}")
    return [line for line in done.stdout.splitlines() if line.strip()]


def query(sql: str, psql: Sequence[str]) -> list[dict[str, object]]:
    """Rows of one SELECT as dicts (one JSON object per line, so text may hold any character)."""
    lines = run(f"select to_jsonb(q) from ({sql.rstrip().rstrip(';')}) q;", psql)
    return [json.loads(line) for line in lines]
