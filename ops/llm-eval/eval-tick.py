#!/usr/bin/env python3
"""eval-tick — one evaluation run of the local-LLM stack (RX 7700 XT via wfh).

Fired every 6h by llm-eval.timer on elitedesk. Each tick:
  1. GRADE the previous tick's soft jobs (done gpu_jobs tagged eval_run_id,
     not yet in eval_scores) with `claude -p` as judge.
  2. Open a new eval_runs row, rotating the focus model.
  3. CODING: run every task in TASKS_DIR through run-coding-task.sh
     (aider loop-to-green in a Docker sandbox); insert objective scores.
  4. SOFT: submit one reasoning `generate` + one log-summarise `summarise`
     job to gpu_jobs, tagged for grading on the NEXT tick.

Env (via ~/.config/home-ops/llm-eval.env):
  OLLAMA_URL     default http://192.168.1.10:11434 (wfh on LAN)
  API_URL        default http://localhost:64421
  INGEST_TOKEN   required — /api/jobs auth + self-logging
  MODELS         csv, default gemma3:1b,qwen3:8b,qwen3:14b,gemma3:12b
  EVAL_HOME      default ~/llm-eval
  TASK_TIMEOUT   per coding task seconds, default 600
  JUDGE_CAP      max jobs graded per tick, default 12
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://192.168.1.10:11434')
API_URL = os.environ.get('API_URL', 'http://localhost:64421').rstrip('/')
INGEST_TOKEN = os.environ['INGEST_TOKEN']
MODELS = [m.strip() for m in os.environ.get(
    'MODELS', 'gemma3:1b,qwen3:8b,qwen3:14b,gemma3:12b').split(',') if m.strip()]
EVAL_HOME = Path(os.environ.get('EVAL_HOME', str(Path.home() / 'llm-eval')))
TASK_TIMEOUT = int(os.environ.get('TASK_TIMEOUT', '600'))
JUDGE_CAP = int(os.environ.get('JUDGE_CAP', '12'))

REASONING_BANK = [
    ('A bat and a ball cost 1.10 in total. The bat costs 1.00 more than the ball. '
     'How much does the ball cost? Answer with just the amount.', '0.05'),
    ('I have 3 boxes. Box A holds twice as many apples as box B. Box C holds 4 fewer '
     'than box A. Together they hold 46. How many apples are in box B? Answer with just the number.', '10'),
    ('If it takes 5 machines 5 minutes to make 5 widgets, how long does it take 100 '
     'machines to make 100 widgets? Answer with just the number of minutes.', '5'),
]


def q(s: str) -> str:
    return s.replace("'", "''")


def psql(sql: str) -> str:
    r = subprocess.run(
        ['docker', 'exec', '-i', 'home-ops-postgres-1',
         'psql', '-U', 'postgres', '-d', 'home_ops', '-tA', '-v', 'ON_ERROR_STOP=1'],
        input=sql, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f'psql failed: {r.stderr[:400]}')
    return r.stdout.strip()


def api(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    req = urllib.request.Request(
        API_URL + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={'Content-Type': 'application/json', 'X-Ingest-Token': INGEST_TOKEN})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def log(level: str, message: str, data: dict[str, Any] | None = None) -> None:
    print(f'[{level}] {message}', file=sys.stderr)
    try:
        api('POST', '/api/ingest', {
            'host': 'elitedesk', 'source': 'app:llm-eval',
            'level': level, 'message': message, 'data': data or {}})
    except OSError:
        pass


def judge(prompt: str) -> dict[str, Any] | None:
    """Grade with claude -p; expects strict JSON back."""
    try:
        r = subprocess.run(['claude', '-p', prompt], capture_output=True, text=True, timeout=180)
        raw = r.stdout.strip()
        start, end = raw.find('{'), raw.rfind('}')
        if start < 0 or end <= start:
            return None
        v = json.loads(raw[start:end + 1])
        if not (isinstance(v.get('score'), (int, float)) and v.get('verdict') in
                ('usable', 'marginal', 'unusable')):
            return None
        return v
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None


def grade_pending() -> int:
    rows = psql(f"""
        SELECT row_to_json(j) FROM (
          SELECT id, kind, payload, result FROM gpu_jobs
          WHERE status = 'done' AND payload ? 'eval_run_id'
            AND NOT EXISTS (SELECT 1 FROM eval_scores e WHERE e.gpu_job_id = gpu_jobs.id)
          ORDER BY id LIMIT {JUDGE_CAP}
        ) j""")
    graded = 0
    for line in [ln for ln in rows.splitlines() if ln]:
        job = json.loads(line)
        p, res = job['payload'], job.get('result') or {}
        answer = (res.get('response') or '').strip()
        task_kind = p.get('task_kind', 'reasoning')
        expected = p.get('eval_expected')
        jp = (
            'You are grading a local LLM\'s answer. Return ONLY strict JSON: '
            '{"score": <0..1>, "verdict": "usable"|"marginal"|"unusable", "rationale": "<one sentence>"}.\n'
            f'Task kind: {task_kind}\n'
            + (f'Expected answer: {expected}\n' if expected else '')
            + f'Prompt given to the model:\n{p.get("prompt", "(summarise task)")[:1500]}\n'
            + f'Model answer:\n{answer[:3000] or "(empty)"}'
        )
        v = judge(jp)
        if v is None:
            log('warn', f'judge failed for gpu_job {job["id"]}')
            continue
        tok_s = 'NULL'
        if res.get('eval_count') and res.get('total_duration_ns'):
            tok_s = f"{res['eval_count'] / (res['total_duration_ns'] / 1e9):.1f}"
        psql(f"""
            INSERT INTO eval_scores (run_id, gpu_job_id, task_kind, model, score, verdict, tok_per_s, rationale)
            VALUES ({int(p['eval_run_id'])}, {int(job['id'])}, '{q(task_kind)}',
                    '{q(p.get('model', '?'))}', {min(max(float(v['score']), 0), 1):.2f},
                    '{q(v['verdict'])}', {tok_s}, '{q(str(v.get('rationale', ''))[:500])}')
            ON CONFLICT DO NOTHING""")
        graded += 1
    return graded


def run_coding(run_id: int, model: str) -> int:
    runner = EVAL_HOME / 'run-coding-task.sh'
    done = 0
    for task_dir in sorted((EVAL_HOME / 'tasks').iterdir()):
        if not (task_dir / 'PROMPT.md').exists():
            continue
        try:
            r = subprocess.run(
                [str(runner), str(task_dir), model],
                capture_output=True, text=True, timeout=TASK_TIMEOUT + 120,
                env={**os.environ, 'OLLAMA_URL': OLLAMA_URL, 'TASK_TIMEOUT': str(TASK_TIMEOUT)})
            out = json.loads(r.stdout.strip().splitlines()[-1])
        except (subprocess.TimeoutExpired, json.JSONDecodeError, IndexError, OSError) as e:
            log('error', f'coding task {task_dir.name} runner failed: {e}')
            continue
        wall = max(int(out.get('wall_s', 0)), 1)
        tok_s = f"{out.get('tok_recv', 0) / wall:.1f}" if out.get('tok_recv') else 'NULL'
        psql(f"""
            INSERT INTO eval_scores (run_id, task_kind, model, passed, iterations, tok_per_s, latency_ms, rationale)
            VALUES ({run_id}, 'coding', '{q(model)}', {'true' if out.get('passed') else 'false'},
                    {int(out.get('test_runs', 0))}, {tok_s}, {wall * 1000}, '{q(task_dir.name)}')""")
        log('info', f"coding {task_dir.name} model={model} passed={out.get('passed')} "
                    f"runs={out.get('test_runs')} wall={wall}s")
        done += 1
    return done


def submit_soft(run_id: int, model: str) -> None:
    qn, expected = REASONING_BANK[run_id % len(REASONING_BANK)]
    api('POST', '/api/jobs', {'kind': 'generate', 'priority': 5, 'payload': {
        'model': model, 'prompt': qn,
        'eval_run_id': run_id, 'task_kind': 'reasoning', 'eval_expected': expected}})

    chunk = psql("""
        SELECT string_agg(to_char(ts, 'HH24:MI') || ' [' || level || '] ' || host || ' ' ||
               left(message, 200), E'\n' ORDER BY ts)
        FROM (SELECT ts, level, host, message FROM host_logs
              WHERE level IN ('warn','error','fatal') AND ts > now() - interval '24 hours'
              ORDER BY ts DESC LIMIT 60) w""")
    if chunk:
        api('POST', '/api/jobs', {'kind': 'summarise', 'priority': 5, 'payload': {
            'model': model, 'chunks': [chunk], 'lang': 'en',
            'prompt': 'Summarise these warn/error log events. Group by failure mode. Be terse.',
            'eval_run_id': run_id, 'task_kind': 'summarise'}})


def main() -> None:
    t0 = time.monotonic()
    graded = grade_pending()
    last = psql('SELECT coalesce(max(id), 0) FROM eval_runs')
    model = MODELS[int(last) % len(MODELS)]
    run_id = int(psql(
        f"INSERT INTO eval_runs (model_focus, note) VALUES ('{q(model)}', 'tick') RETURNING id"))
    log('info', f'eval tick start: run={run_id} focus={model} graded_prev={graded}')
    coded = run_coding(run_id, model)
    submit_soft(run_id, model)
    log('info', f'eval tick done: run={run_id} coding={coded} '
                f'wall={int(time.monotonic() - t0)}s', {'job_id': run_id})


if __name__ == '__main__':
    main()
