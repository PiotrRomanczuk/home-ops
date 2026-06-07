#!/usr/bin/env python3
"""home-ops GPU scheduler — runs on the Windows box that owns the dGPU.

Two long-lived threads:
  * gaming_detector — every 5 s, samples 3D-engine util + foreground exe.
    Maintains shared state `is_gaming`.
  * job_runner — claims jobs via /api/jobs/claim, dispatches by `kind` to
    handlers in jobs/*.py. Between handler chunks it checks `is_gaming` and
    pauses (re-queue + unload Ollama model) when it flips on.

Env:
  INGEST_URL          base /api/* URL (e.g. http://192.168.1.75:64421)
  INGEST_TOKEN        shared secret
  HOST_NAME           defaults to 'wfh'
  OLLAMA_URL          defaults to http://127.0.0.1:11434
  GAMES_FILE          defaults to C:\\ProgramData\\GpuScheduler\\games.txt
  GPU_THRESHOLD       3D engine util %, default 30
  GPU_WINDOW          rolling window seconds, default 30
  IDLE_DEBOUNCE       seconds of low-GPU + non-game before idle returns, default 60
  POLL_SECONDS        gaming detector poll interval, default 5
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any, Callable

try:
    import psutil  # type: ignore
except ImportError:
    print('psutil missing — install via `py -3 -m pip install psutil`', file=sys.stderr)
    sys.exit(1)


INGEST_URL = (os.environ.get('INGEST_URL', '') or '').rstrip('/')
INGEST_TOKEN = os.environ.get('INGEST_TOKEN', '')
HOST_NAME = os.environ.get('HOST_NAME', 'wfh')
OLLAMA_URL = (os.environ.get('OLLAMA_URL') or 'http://127.0.0.1:11434').rstrip('/')
GAMES_FILE = Path(os.environ.get('GAMES_FILE') or r'C:\ProgramData\GpuScheduler\games.txt')
GPU_THRESHOLD = float(os.environ.get('GPU_THRESHOLD', '30'))
GPU_WINDOW = float(os.environ.get('GPU_WINDOW', '30'))
IDLE_DEBOUNCE = float(os.environ.get('IDLE_DEBOUNCE', '60'))
POLL_SECONDS = float(os.environ.get('POLL_SECONDS', '5'))


if not INGEST_URL or not INGEST_TOKEN:
    print('INGEST_URL and INGEST_TOKEN required', file=sys.stderr)
    sys.exit(1)


# ── HTTP helpers ─────────────────────────────────────────────────────

def http(method: str, path: str, body: Any = None, timeout: float = 10) -> tuple[int, dict[str, Any] | None]:
    url = INGEST_URL + path if path.startswith('/') else INGEST_URL + '/' + path
    headers = {'X-Ingest-Token': INGEST_TOKEN, 'Content-Type': 'application/json'}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if not raw: return r.status, None
            return r.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read())
        except Exception: return e.code, None
    except urllib.error.URLError:
        return 0, None


def post_log(level: str, message: str, data: dict[str, Any] | None = None) -> None:
    body = {'host': HOST_NAME, 'source': 'gpu-scheduler', 'level': level, 'message': message}
    if data: body['data'] = data
    http('POST', '/api/ingest', body, timeout=5)


# ── gaming detector ───────────────────────────────────────────────────

class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.is_gaming = False
        self.last_reason: str | None = None
        self.gpu_samples: deque[tuple[float, float]] = deque()
        self.last_low_at: float = time.monotonic()
        self.foreground_exe: str | None = None
        self.games: set[str] = set()
        self.refresh_games()

    def refresh_games(self) -> None:
        try:
            text = GAMES_FILE.read_text(encoding='utf-8', errors='replace')
            self.games = {l.strip().lower() for l in text.splitlines() if l.strip() and not l.lstrip().startswith('#')}
        except FileNotFoundError:
            self.games = set()


state = State()


def gpu_util_3d() -> float:
    """Sum 3D-engine utilisation across all GPU instances. Returns 0 on error."""
    ps = (
        "$c = Get-Counter -ErrorAction SilentlyContinue "
        "'\\GPU Engine(*engtype_3D)\\Utilization Percentage';"
        "if ($c) { $s = ($c.CounterSamples | Measure-Object CookedValue -Sum).Sum; "
        "if ($s -eq $null) { 0 } else { '{0:N2}' -f $s } } else { 0 }"
    )
    try:
        out = subprocess.check_output(
            ['powershell', '-NoProfile', '-Command', ps],
            stderr=subprocess.DEVNULL, timeout=4,
        ).decode().strip()
        return float(out.replace(',', '.'))
    except Exception:
        return 0.0


def running_process_names() -> set[str]:
    """Set of lowercase .exe names of all currently running processes.

    We can't use GetForegroundWindow from a Windows service (Session 0
    isolation hides the user's desktop). Instead we enumerate processes —
    if a known game from games.txt is *running at all*, treat it as gaming.
    Services CAN see all processes across sessions, just not which window
    is focused.
    """
    names: set[str] = set()
    for p in psutil.process_iter(['name']):
        try:
            n = p.info.get('name')
            if n: names.add(n.lower())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return names


def detector_loop() -> None:
    last_games_mtime: float = 0.0
    last_fg_log: float = 0.0
    last_fg_logged: str | None = None
    while True:
        try:
            try:
                mtime = GAMES_FILE.stat().st_mtime
                if mtime != last_games_mtime:
                    state.refresh_games()
                    last_games_mtime = mtime
            except FileNotFoundError:
                pass

            util = gpu_util_3d()
            running = running_process_names()
            now = time.monotonic()
            with state.lock:
                state.gpu_samples.append((now, util))
                while state.gpu_samples and now - state.gpu_samples[0][0] > GPU_WINDOW:
                    state.gpu_samples.popleft()
                avg_util = sum(s for _, s in state.gpu_samples) / max(len(state.gpu_samples), 1)
                matching = sorted(state.games & running)
                fg = matching[0] if matching else None
                state.foreground_exe = fg

                # Gaming = any process matching games.txt is currently running.
                # High GPU alone is NOT a trigger because we *generate* high
                # GPU load ourselves (Ollama, embeddings, backfill). Windows
                # services can't see GetForegroundWindow (Session 0 isolation)
                # but they CAN enumerate processes, so we treat "game exe is
                # running" as good enough.
                is_game_exe = bool(matching)

                new_gaming = state.is_gaming
                reason: str | None = None
                if not state.is_gaming and is_game_exe:
                    new_gaming = True
                    reason = f'game-exe ({", ".join(matching)})'
                elif state.is_gaming:
                    if not is_game_exe:
                        if now - state.last_low_at >= IDLE_DEBOUNCE:
                            new_gaming = False
                            reason = 'idle-debounce-elapsed'
                    else:
                        state.last_low_at = now

                if not is_game_exe and not state.is_gaming:
                    state.last_low_at = now

                # Periodic foreground heartbeat so the user can discover the
                # right exe name to add to games.txt. Logs on change or every 60s.
                if (fg != last_fg_logged) or (now - last_fg_log > 60):
                    threading.Thread(target=post_log, args=(
                        'debug',
                        f'foreground={fg or "<none>"} gpu={avg_util:.0f}% gaming={state.is_gaming}',
                        {'foreground': fg, 'avg_gpu_util': round(avg_util, 1), 'is_gaming': state.is_gaming, 'games_loaded': len(state.games)},
                    ), daemon=True).start()
                    last_fg_log = now
                    last_fg_logged = fg

                if new_gaming != state.is_gaming:
                    state.is_gaming = new_gaming
                    state.last_reason = reason
                    threading.Thread(target=post_log, args=(
                        'info',
                        f'gaming detected → workload paused' if new_gaming else 'idle returned → resuming workload',
                        {'reason': reason, 'avg_gpu_util': round(avg_util, 1), 'foreground': fg, 'window_s': GPU_WINDOW},
                    ), daemon=True).start()
                    if new_gaming:
                        threading.Thread(target=unload_ollama_models, daemon=True).start()
        except Exception as e:
            print(f'detector error: {e}', file=sys.stderr)
        time.sleep(POLL_SECONDS)


def unload_ollama_models() -> None:
    """Tell Ollama to drop every currently-loaded model from VRAM."""
    try:
        with urllib.request.urlopen(OLLAMA_URL + '/api/ps', timeout=4) as r:
            ps = json.loads(r.read())
    except Exception:
        return
    for m in (ps.get('models') or []):
        body = json.dumps({'model': m.get('name'), 'keep_alive': 0}).encode()
        req = urllib.request.Request(OLLAMA_URL + '/api/generate', data=body, method='POST',
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=5):
                pass
        except Exception:
            pass


# ── job runner ────────────────────────────────────────────────────────

JOBS_DIR = Path(__file__).resolve().parent / 'jobs'


def load_handler(kind: str) -> Callable[[dict[str, Any], threading.Event], dict[str, Any]] | None:
    path = JOBS_DIR / f'{kind}.py'
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(f'jobs.{kind}', path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, 'run', None)


def claim_one() -> dict[str, Any] | None:
    status, body = http('POST', '/api/jobs/claim', {'worker_host': HOST_NAME})
    if status == 204 or body is None:
        return None
    if status >= 400:
        return None
    return body.get('job')


def complete(job_id: int, result: Any) -> None:
    http('POST', f'/api/jobs/{job_id}/complete', {'result': result})


def fail(job_id: int, error: str) -> None:
    http('POST', f'/api/jobs/{job_id}/fail', {'error': error})


def pause(job_id: int) -> None:
    http('POST', f'/api/jobs/{job_id}/pause', {})


def runner_loop() -> None:
    while True:
        if state.is_gaming:
            time.sleep(5)
            continue
        job = claim_one()
        if not job:
            time.sleep(5)
            continue
        job_id = job['id']
        kind = job['kind']
        post_log('info', f'running job {job_id} ({kind})', {'job_id': job_id, 'kind': kind})

        handler = load_handler(kind)
        if not handler:
            fail(job_id, f'no handler for kind={kind}')
            post_log('error', f'no handler for kind={kind}', {'job_id': job_id})
            continue

        cancel = threading.Event()
        # Mutable container so watchers can record which one tripped first.
        # 'gaming' → /pause (requeue when GPU frees). 'user' → /complete
        # (server transitions cancelling → cancelled, keeps any partial result).
        cancel_reason: dict[str, str] = {}

        def watch_for_gaming() -> None:
            while not cancel.is_set():
                if state.is_gaming:
                    cancel_reason.setdefault('why', 'gaming')
                    cancel.set(); return
                time.sleep(0.5)

        def watch_for_user_cancel() -> None:
            # Poll status; if server flipped us to 'cancelling' (Q11), trip cancel.
            while not cancel.is_set():
                time.sleep(3)
                status, body = http('GET', f'/api/jobs/{job_id}')
                if status == 200 and body:
                    st = (body.get('job') or {}).get('status')
                    if st == 'cancelling':
                        cancel_reason.setdefault('why', 'user')
                        cancel.set(); return

        watcher_g = threading.Thread(target=watch_for_gaming, daemon=True)
        watcher_u = threading.Thread(target=watch_for_user_cancel, daemon=True)
        watcher_g.start()
        watcher_u.start()
        try:
            result = handler(job, cancel)
            if cancel.is_set():
                why = cancel_reason.get('why', 'gaming')
                if why == 'user':
                    complete(job_id, result)
                    post_log('info', f'job {job_id} cancelled (user)', {'job_id': job_id})
                else:
                    pause(job_id)
                    post_log('warn', f'job {job_id} paused (gaming detected)', {'job_id': job_id})
            else:
                complete(job_id, result)
                post_log('info', f'job {job_id} done', {'job_id': job_id})
        except Exception:
            tb = traceback.format_exc(limit=4)
            fail(job_id, tb)
            post_log('error', f'job {job_id} failed', {'job_id': job_id, 'traceback': tb[-2000:]})
        finally:
            cancel.set()


# ── main ──────────────────────────────────────────────────────────────

def main() -> None:
    GAMES_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not GAMES_FILE.exists():
        GAMES_FILE.write_text(
            '# One process executable name per line (lowercase). '
            'Comments allowed.\n# e.g.\n# csgo.exe\n# eldenring.exe\n', encoding='utf-8',
        )
    post_log('info', 'gpu-scheduler starting', {
        'gpu_threshold_pct': GPU_THRESHOLD,
        'gpu_window_s': GPU_WINDOW,
        'idle_debounce_s': IDLE_DEBOUNCE,
        'poll_s': POLL_SECONDS,
        'games_loaded': len(state.games),
    })

    t1 = threading.Thread(target=detector_loop, daemon=True, name='detector')
    t1.start()
    t2 = threading.Thread(target=runner_loop, daemon=True, name='runner')
    t2.start()
    while True:
        time.sleep(60)


if __name__ == '__main__':
    main()
