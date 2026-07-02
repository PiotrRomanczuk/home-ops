#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp[cli]>=1.0"]
# ///
"""home-ops MCP server — exposes home-ops as MCP tools.

Lets any MCP client (Claude Desktop, Claude Code, etc.) read home-ops
state and drive the local LLM queue running qwen3 on win10.

Tools:
  query_logs            — search host_logs by host/source/level/grep/window
  list_recent_jobs      — gpu_jobs queue introspection (filter by kind/status)
  get_job               — single job state (polling)
  submit_llm_job        — POST /api/jobs and BLOCK until completion
  cancel_job            — kill a queued/running job
  list_projects         — vault-derived project list
  get_project           — single project with Now/Next/Later markdown
  get_host_metrics      — latest metric sample(s) for hosts
  models_loaded         — what's resident in win10 VRAM right now
  list_eval_tasks       — Evals board: cards + pass-rate stats per task
  create_eval_task      — add an 'idea' card to the board
  set_eval_task_stage   — move a card (controls what the 6h eval tick runs)
  update_eval_task      — edit a card's notes / timeout override
  get_eval_task_scores  — recent per-run results for one task

Env:
  INGEST_URL    e.g. http://elitedesk.tail266853.ts.net:64421/api/ingest
                or http://192.168.1.75:64421/api/ingest on LAN
  INGEST_TOKEN  shared secret (same one the watchers use)

Run:
  Easiest:    uv run mcp/server.py
  Or pip:     pip install 'mcp[cli]>=1.0' && python3 mcp/server.py

See mcp/README.md for Claude Desktop / Claude Code config snippets.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from mcp.server.fastmcp import FastMCP

INGEST_URL = (os.environ.get("INGEST_URL") or "").rstrip("/")
INGEST_TOKEN = os.environ.get("INGEST_TOKEN", "")

if not INGEST_URL or not INGEST_TOKEN:
    print("INGEST_URL and INGEST_TOKEN required", file=sys.stderr)
    sys.exit(1)

# /api/ingest is the events endpoint; the base API root is one segment up
BASE = INGEST_URL[: -len("/api/ingest")] if INGEST_URL.endswith("/api/ingest") else INGEST_URL

mcp = FastMCP("home-ops")


def _request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    body: dict | None = None,
    timeout: float = 10.0,
) -> tuple[int, dict | None]:
    """Single-shot HTTP. Returns (status, parsed_body). status=0 on network err."""
    url = BASE + path
    if params:
        cleaned = {k: v for k, v in params.items() if v is not None}
        if cleaned:
            url += "?" + urllib.parse.urlencode(cleaned, doseq=True)
    headers = {"X-Ingest-Token": INGEST_TOKEN}
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except (json.JSONDecodeError, ValueError, OSError):
            return e.code, None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, {"error": str(e)}


# ── tools ────────────────────────────────────────────────────────────


@mcp.tool()
def query_logs(
    host: str | None = None,
    source: str | None = None,
    level_min: str = "info",
    grep: str | None = None,
    since_min: int = 60,
    limit: int = 50,
) -> str:
    """Search home-ops host_logs.

    Args:
      host: filter by host id ('elitedesk' | 'win10' | 'rpi')
      source: filter by source string ('app:guitar-crm', 'journald:cloudflared', etc.)
      level_min: minimum log level: debug | info | warn | error | fatal
      grep: substring match across message + source + data
      since_min: time window in minutes (default 60)
      limit: max rows (default 50, capped at 200)

    Returns JSON: { rows: [{ts, host, source, level, message, data}], latest_id }
    """
    capped = max(1, min(int(limit), 200))
    code, body = _request(
        "GET",
        "/api/logs",
        params={
            "host": host,
            "source": source,
            "level_min": level_min,
            "grep": grep,
            "since_min": int(since_min),
            "limit": capped,
        },
    )
    if code != 200:
        return json.dumps({"error": f"HTTP {code}", "body": body})
    return json.dumps(body)


@mcp.tool()
def list_recent_jobs(
    kind: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> str:
    """List recent gpu_jobs from the local LLM queue.

    Args:
      kind: 'generate' | 'summarise' | 'embed' | None (all)
      status: 'queued' | 'running' | 'paused' | 'cancelling' | 'cancelled' | 'done' | 'failed' | None
      limit: max rows (default 20, capped at 100)

    Use this before submit_llm_job if you want to see what's currently in flight.
    """
    capped = max(1, min(int(limit), 100))
    code, body = _request("GET", "/api/jobs", params={"status": status, "limit": capped})
    if code != 200:
        return json.dumps({"error": f"HTTP {code}", "body": body})
    if kind and body and "jobs" in body:
        # API doesn't filter by kind server-side; do it here
        body["jobs"] = [j for j in body["jobs"] if j.get("kind") == kind]
    return json.dumps(body)


@mcp.tool()
def get_job(job_id: int) -> str:
    """Fetch one gpu_jobs row by id, including result (response/thinking/summary)."""
    code, body = _request("GET", f"/api/jobs/{int(job_id)}")
    if code != 200:
        return json.dumps({"error": f"HTTP {code}", "body": body})
    return json.dumps(body)


@mcp.tool()
def submit_llm_job(
    prompt: str,
    model: str = "qwen3:8b",
    kind: str = "generate",
    project: str | None = None,
    timeout_sec: int = 300,
    poll_sec: float = 1.5,
) -> str:
    """Submit a job to the local LLM queue on win10 and BLOCK until completion.

    The job is gaming-aware — if a game is detected on win10, the job pauses
    and resumes when GPU is idle. Sub-1s cancel responsiveness.

    Args:
      prompt: the prompt text
      model: 'qwen3:8b' (default, reasoning) / 'nomic-embed-text' / etc.
              Call models_loaded() first to see what's resident in VRAM.
      kind: 'generate' for one-shot prompt (default)
            'summarise' for chunked summarisation (different payload shape)
            'embed' for vectorisation
      project: optional slug to tag the job with (shows in Projects drill page)
      timeout_sec: max wait in seconds before we cancel (default 300 = 5 min)
      poll_sec: poll interval (default 1.5s — matches the chat UI's cadence)

    Returns JSON:
      { job_id, status: 'done'|'failed'|'cancelled'|'timeout',
        response (str|null, for generate),
        thinking (str|null, for reasoning models — qwen3 emits these before response),
        summary  (str|null, for summarise),
        duration_sec, error }

    Tip: for long generations, the 5-min default is usually enough. For batch
    summarisation over many chunks, pass timeout_sec=900 or more.
    """
    payload: dict = {"model": model, "prompt": prompt}
    if project:
        payload["project"] = project

    code, body = _request(
        "POST",
        "/api/jobs",
        body={"kind": kind, "payload": payload, "priority": 10},
    )
    if code not in (200, 201) or not body or "job" not in body:
        return json.dumps({"error": f"submit failed HTTP {code}", "body": body})

    job_id = int(body["job"]["id"])
    started = time.monotonic()

    while time.monotonic() - started < timeout_sec:
        time.sleep(max(0.25, float(poll_sec)))
        code, body = _request("GET", f"/api/jobs/{job_id}")
        if code != 200 or not body or "job" not in body:
            continue  # transient — keep polling
        job = body["job"]
        status = job.get("status")
        if status in ("done", "failed", "cancelled"):
            result = job.get("result") or {}
            return json.dumps(
                {
                    "job_id": job_id,
                    "status": status,
                    "response": result.get("response"),
                    "thinking": result.get("thinking"),
                    "summary": result.get("summary"),
                    "duration_sec": int(time.monotonic() - started),
                    "error": job.get("last_error"),
                }
            )

    # timeout — cancel and report
    _request("POST", f"/api/jobs/{job_id}/cancel")
    return json.dumps(
        {
            "job_id": job_id,
            "status": "timeout",
            "error": f"exceeded {timeout_sec}s, cancelled",
        }
    )


@mcp.tool()
def cancel_job(job_id: int) -> str:
    """Cancel a queued or running job. 409 if the job is already terminal."""
    code, body = _request("POST", f"/api/jobs/{int(job_id)}/cancel")
    if code == 409:
        return json.dumps({"error": "job not cancellable (already terminal)", "body": body})
    if code != 200:
        return json.dumps({"error": f"HTTP {code}", "body": body})
    return json.dumps(body)


@mcp.tool()
def list_projects(status: str | None = None) -> str:
    """List vault-derived projects (synced from Obsidian planner every 60s).

    Args:
      status: 'hot' | 'warm' | 'dormant' | 'stalled' | None (all)

    Returns the full project rows including now_md, next_md, etc. Useful for
    grounding answers like "what's hot this week?" or "what's stalled?".
    """
    code, body = _request("GET", "/api/projects", params={"status": status})
    if code != 200:
        return json.dumps({"error": f"HTTP {code}", "body": body})
    return json.dumps(body)


@mcp.tool()
def get_project(slug: str) -> str:
    """Fetch a single project's full state by slug.

    Useful for "what's next on guitar-crm?" or "what are the pain points on stano?".
    Returns now_md / next_md / later_md / pain_md as raw markdown (Now/Next/Later
    items rendered as `- [ ]` / `- [x]` lines).
    """
    code, body = _request("GET", f"/api/projects/{urllib.parse.quote(slug, safe='')}")
    if code == 404:
        return json.dumps({"error": f"no project with slug={slug!r}"})
    if code != 200:
        return json.dumps({"error": f"HTTP {code}", "body": body})
    return json.dumps(body)


@mcp.tool()
def get_host_metrics(host: str | None = None) -> str:
    """Latest metric sample(s) for hosts.

    Args:
      host: 'elitedesk' | 'win10' | 'rpi' | None (one row per host that has emitted)

    Returns rows with cpu_pct, mem_pct, gpu_pct, gpu_temp_c, plus a `data` jsonb
    holding top_cpu[], top_mem[], gpu_models_loaded[]. The attribution in `data`
    is the differentiator from a plain time-series tool — use it to answer
    "what's eating the gpu right now?".
    """
    code, body = _request("GET", "/api/metrics", params={"host": host, "latest": 1})
    if code != 200:
        return json.dumps({"error": f"HTTP {code}", "body": body})
    return json.dumps(body)


@mcp.tool()
def models_loaded() -> str:
    """List models currently resident in win10's VRAM.

    Helpful before submit_llm_job — picking a model that's already loaded means
    zero cold-start; picking one that isn't will trigger Ollama to load it on
    first request (~5–30s depending on size).
    """
    code, body = _request("GET", "/api/metrics", params={"host": "win10", "latest": 1})
    if code != 200:
        return json.dumps({"error": f"HTTP {code}", "body": body})
    rows = (body or {}).get("rows") or []
    if not rows:
        return json.dumps({"models": [], "note": "no recent win10 metrics — watcher may be down"})
    data = rows[0].get("data") or {}
    raw_models = data.get("gpu_models_loaded") or []
    models = [
        {
            "name": m.get("name") or m.get("model"),
            "vram_mb": m.get("vram_mb") or m.get("vram"),
        }
        for m in raw_models
    ]
    return json.dumps(
        {
            "models": models,
            "gpu_pct": rows[0].get("gpu_pct"),
            "gpu_mem_pct": rows[0].get("gpu_mem_pct"),
            "gpu_temp_c": rows[0].get("gpu_temp_c"),
            "ts": rows[0].get("ts"),
        }
    )


# ── eval board tools ─────────────────────────────────────────────
#
# The Evals board (eval_tasks table, Evals tab in the viewer) manages the
# lifecycle of local-LLM eval tasks: idea → building → testing → active →
# paused → retired. The board is AUTHORITATIVE — the 6-hourly eval tick
# runs only tasks whose stage is 'testing' or 'active'. Creating a card
# does NOT create task files on disk (that stays manual / Claude-assisted
# on elitedesk under ~/llm-eval); `has_files` shows whether eval-tick has
# seen the task's directory.

EVAL_STAGES = ("idea", "building", "testing", "active", "paused", "retired")


def _resolve_eval_task(task: str) -> tuple[dict | None, str | None]:
    """Find a board card by name or numeric id. Returns (card, error)."""
    code, body = _request("GET", "/api/eval_tasks")
    if code != 200 or not body:
        return None, f"HTTP {code}"
    cards = body.get("tasks") or []
    key = task.strip()
    if key.isdigit():
        hit = next((t for t in cards if t.get("id") == int(key)), None)
    else:
        hit = next((t for t in cards if t.get("name") == key), None)
    if not hit:
        known = ", ".join(t.get("name", "?") for t in cards)
        return None, f"no eval task matching {task!r} (known: {known})"
    return hit, None


@mcp.tool()
def list_eval_tasks(stage: str | None = None, kind: str | None = None) -> str:
    """List the Evals board: eval-task cards with lifecycle stage + result stats.

    Stages: idea | building | testing | active | paused | retired.
    Only 'testing' and 'active' run in the 6-hourly eval tick — the board
    gates the tick, so this is the source of truth for the benchmark suite.

    Args:
      stage: filter to one stage (None = whole board)
      kind: 'python' (pytest sandbox tasks) | 'strummy' (guitar-crm
            reconstruction tasks) | None (all)

    Returns JSON: { tasks: [{id, name, kind, stage, notes, timeout_s,
      has_files, n_runs, n_passed, avg_iterations, last_passed, last_model,
      last_scored_at, ...}] }. has_files=false on a testing/active card
    means eval-tick can't find its directory — it will be skipped in
    practice and needs files created under ~/llm-eval on elitedesk.
    """
    code, body = _request("GET", "/api/eval_tasks")
    if code != 200 or not body:
        return json.dumps({"error": f"HTTP {code}", "body": body})
    cards = body.get("tasks") or []
    if stage:
        cards = [t for t in cards if t.get("stage") == stage]
    if kind:
        cards = [t for t in cards if t.get("kind") == kind]
    return json.dumps({"tasks": cards})


@mcp.tool()
def create_eval_task(name: str, kind: str = "python", notes: str | None = None) -> str:
    """Add a new eval-task idea card to the Evals board (stage='idea').

    This records intent only — no files are created. To make the task
    runnable: write its files on elitedesk (~/llm-eval/tasks/<name>/ with
    PROMPT.md + solution.py + test_solution.py for python; strummy tasks
    use PROMPT.md + stub.txt + meta.env under strummy/tasks-strummy/),
    then move the card to 'testing' with set_eval_task_stage.

    Args:
      name: dir-safe id, lowercase (^[a-z0-9][a-z0-9_-]{0,63}$), e.g.
            'lru-cache' or 'chord-transpose'
      kind: 'python' | 'strummy'
      notes: what the task should prove, edge cases to cover, etc.
    """
    code, body = _request("POST", "/api/eval_tasks", body={"name": name, "kind": kind, "notes": notes})
    if code == 409:
        return json.dumps({"error": f"eval task {name!r} already exists"})
    if code not in (200, 201):
        return json.dumps({"error": f"HTTP {code}", "body": body})
    return json.dumps(body)


@mcp.tool()
def set_eval_task_stage(task: str, stage: str) -> str:
    """Move an eval-task card to a new lifecycle stage.

    THIS CONTROLS WHAT RUNS: 'testing' and 'active' are in the 6-hourly
    rotation; 'paused'/'retired' remove the task from runs without touching
    its files. Typical flows: idea → building (files being written) →
    testing (first results, provisional) → active (steady benchmark);
    active → paused (temporarily out); anything → retired.

    Args:
      task: card name (e.g. 'rle-encode') or numeric id
      stage: idea | building | testing | active | paused | retired
    """
    if stage not in EVAL_STAGES:
        return json.dumps({"error": f"invalid stage {stage!r} (valid: {', '.join(EVAL_STAGES)})"})
    card, err = _resolve_eval_task(task)
    if err:
        return json.dumps({"error": err})
    code, body = _request("POST", f"/api/eval_tasks/{card['id']}/stage", body={"stage": stage})
    if code != 200:
        return json.dumps({"error": f"HTTP {code}", "body": body})
    return json.dumps(body)


@mcp.tool()
def update_eval_task(task: str, notes: str | None = None, timeout_s: int | None = None) -> str:
    """Edit an eval-task card's notes and/or per-task timeout override.

    Args:
      task: card name or numeric id
      notes: replaces the card's notes (pass '' to clear); None = leave as-is
      timeout_s: per-task runner timeout in seconds (1..3600); overrides the
                 global TASK_TIMEOUT (600s) for this task only. None = leave
                 as-is. Long reconstruction tasks (e.g. the 66-assertion
                 'notes' module) may need 900+.
    """
    card, err = _resolve_eval_task(task)
    if err:
        return json.dumps({"error": err})
    patch: dict = {}
    if notes is not None:
        patch["notes"] = notes
    if timeout_s is not None:
        patch["timeout_s"] = int(timeout_s)
    if not patch:
        return json.dumps({"error": "nothing to update — pass notes and/or timeout_s"})
    code, body = _request("POST", f"/api/eval_tasks/{card['id']}/update", body=patch)
    if code != 200:
        return json.dumps({"error": f"HTTP {code}", "body": body})
    return json.dumps(body)


@mcp.tool()
def get_eval_task_scores(task: str, limit: int = 15) -> str:
    """Recent per-run results for one eval task (newest first).

    Args:
      task: card name or numeric id
      limit: max rows (default 15, capped at 30)

    Returns JSON: { task: {name, stage, kind}, scores: [{run_id, model,
      passed, iterations, tok_per_s, latency_ms, scored_at}] }. Use this to
    answer "is qwen3:8b getting better at X?" or to decide whether a
    'testing' card has earned 'active'.
    """
    card, err = _resolve_eval_task(task)
    if err:
        return json.dumps({"error": err})
    code, body = _request("GET", f"/api/eval_tasks/{card['id']}/scores")
    if code != 200 or not body:
        return json.dumps({"error": f"HTTP {code}", "body": body})
    capped = max(1, min(int(limit), 30))
    return json.dumps(
        {
            "task": {"name": card["name"], "stage": card["stage"], "kind": card["kind"]},
            "scores": (body.get("scores") or [])[:capped],
        }
    )


if __name__ == "__main__":
    mcp.run()
