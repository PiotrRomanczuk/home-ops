#!/usr/bin/env python3
"""gpu_worker.py — keeps the Mac's GPU busy with a fixed job list while Piotr is away.

Every 30 s it reads the Mac (machine.py) and acts on the current job's shards (procs.py):
- battery, heat (thermalState >= 2) or memory pressure >= 2 → stop the shards (TERM; the jobs resume later);
- Piotr at the Mac, a local-LLM task borrowing the GPU (STATE/gpu/borrow from runner.py), a song2logic
  run started elsewhere, or a dark wake → pause them (SIGSTOP), nothing is lost;
- otherwise resume paused shards and start missing ones (AC, thermalState 0, memory pressure normal).
A shard exiting 0 is done; all shards done → the next job (Ollama models unloaded first if the job asks).
A shard failing MAX_FAILS times ends its job. Page data: STATE/gpu/status.json; events: STATE/gpu/log.jsonl.

Usage: gpu_worker.py [jobs.json] (default: the root-owned /usr/local/etc/mac-worker/gpu-jobs.json).
Env: SPRINT_STATE (~/.local/state/home-ops/sprint), GPU_IDLE_MIN (10). """
from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

import gpu_jobs as gj
import gpu_pause
import gpu_report
import machine
import procs

GPU = Path(os.environ.get('SPRINT_STATE', '~/.local/state/home-ops/sprint')).expanduser() / 'gpu'
JOBS = Path(sys.argv[1] if len(sys.argv) > 1 else '/usr/local/etc/mac-worker/gpu-jobs.json')
IDLE_MIN = float(os.environ.get('GPU_IDLE_MIN', '10'))
TICK_S, RETRY_S = int(os.environ.get('GPU_TICK_S', '30')), 600
shards: dict[int, dict[str, Any]] = {}  # shard number → {'proc', 'paused', 'job', 'stopping'}
retry_at: dict[str, float] = {}  # '<job>.<shard>' → earliest restart after a failure
running = True


def log(event: str, **data: Any) -> None:
    gpu_report.log(GPU, event, **data)


def collect(by_name: dict[str, dict[str, Any]], progress: gj.Progress) -> set[str]:
    """Record the shards that exited (each against the job it belongs to); return those jobs' names."""
    ended = set()
    for n, sh in list(shards.items()):
        rc = sh['proc'].poll()
        if rc is None:
            continue
        job = by_name[sh['job']]
        del shards[n]
        ended.add(job['name'])
        (GPU / 'pids' / f'{job["name"]}.{n}.json').unlink(missing_ok=True)
        if rc == 0:
            progress.mark_done(job, n)
            log('shard-done', job=job['name'], shard=n)
        elif not sh.get('stopping'):
            fails = progress.fail(job, n)
            retry_at[f'{job["name"]}.{n}'] = time.time() + RETRY_S
            log('shard-failed', job=job['name'], shard=n, rc=rc, fails=fails)
    return ended


def reap(by_name: dict[str, dict[str, Any]], progress: gj.Progress) -> None:
    ended = collect(by_name, progress)
    for name in {sh['job'] for sh in shards.values()}:
        if progress.job_finished(by_name[name]):  # given up (a shard hit MAX_FAILS): its other shards go too
            stop_shards('zadanie porzucone', name)
            ended |= collect(by_name, progress)
    for name in sorted(ended):
        job = by_name[name]
        if progress.job_finished(job) and all(sh['job'] != name for sh in shards.values()):
            log('job-done', job=name)
            if job.get('unload_ollama'):
                log('ollama-unloaded', models=gj.unload_ollama())


def stop_shards(reason: str, job: str | None = None) -> None:
    chosen = {n: sh for n, sh in shards.items() if job in (None, sh['job'])}
    for sh in chosen.values():
        sh['stopping'] = True
    procs.stop_all([sh['proc'].pid for sh in chosen.values()], [sh['proc'] for sh in chosen.values()])
    if chosen:
        log('stopped', reason=reason, shards=sorted(chosen))


def start_missing(job: dict[str, Any], progress: gj.Progress) -> None:
    for n in range(1, job['shards'] + 1):
        if n in shards or progress.shard_done(job, n) or time.time() < retry_at.get(f'{job["name"]}.{n}', 0):
            continue
        with (GPU / 'logs' / f'{job["name"]}.{n}.log').open('ab') as log_file:  # the child keeps its own copy
            proc = procs.start(gj.argv_for(job, n), job['cwd'], {**os.environ, **job['env']},
                               GPU / 'pids' / f'{job["name"]}.{n}.json', log_file)
        shards[n] = {'proc': proc, 'paused': False, 'job': job['name']}
        log('started', job=job['name'], shard=n, pid=proc.pid)


def tick(jobs: list[dict[str, Any]], progress: gj.Progress) -> None:
    reap({j['name']: j for j in jobs}, progress)  # before current(): a finished job's shards must be gone first
    job = progress.current(jobs)
    if job is None:
        return write_status(None, 'wszystko zrobione', None, jobs, progress)
    s = machine.snapshot(own_pgids=[sh['proc'].pid for sh in shards.values()])
    stop, hold = machine.must_stop(s), gpu_pause.hold_reason(s, GPU, IDLE_MIN)
    if stop:
        stop_shards(stop)
    elif hold:
        gpu_pause.pause(shards, True, log)
    else:
        gpu_pause.pause(shards, False, log)
        if machine.can_start(s):
            start_missing(job, progress)
    reason = stop or hold or (None if machine.can_start(s) else 'czeka na warunki')
    write_status(job, reason, s, jobs, progress)


def write_status(job: dict[str, Any] | None, reason: str | None, s: dict[str, Any] | None,
                 jobs: list[dict[str, Any]], progress: gj.Progress) -> None:
    done = sum(progress.job_finished(j) for j in jobs)
    gpu_report.status(GPU, job and job['name'], reason, s, done, len(jobs), shards)


def main() -> None:
    for sub in ('pids', 'logs'):
        (GPU / sub).mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, lambda *_: globals().update(running=False))
    jobs, progress = gj.load(JOBS), gj.Progress(GPU / 'progress.json')
    leftovers = procs.cleanup_orphans(GPU / 'pids')
    log('start', jobs=[j['name'] for j in jobs], orphans_stopped=leftovers)
    while running:
        tick(jobs, progress)
        for _ in range(TICK_S):
            if not running:
                break
            time.sleep(1)
    stop_shards('nadzorca zatrzymany')
    log('exit')


if __name__ == '__main__':
    main()
