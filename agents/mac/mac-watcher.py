#!/usr/bin/env python3
"""mac-watcher — what runs on the Mac: CPU, GPU, network, and who started it.

Sibling of rpi-watcher / win10-watcher for the laptop. Every METRIC_INTERVAL s:
  * host sample (psutil) + Apple GPU (ioreg) → POST /api/metrics as host 'mac',
    data: top_cpu / top_mem / top_net (per process, with the Claude session that
    started it), ollama (loaded models), claude_live (running sessions);
  * notable processes (mac_procs.Tracker: background jobs left by Claude
    sessions, CPU hogs, heavy downloads) → host_logs "proc start" / "proc stop";
  * a "right now" snapshot → POST /api/activity/now.
Delivery, local archive and the offline spool: mac_ship.py. No sudo needed.

Env (launchd passes them through agents/mac/run.sh):
  INGEST_URL            LAN ingest, default http://192.168.1.75:64421/api/ingest
  INGEST_FALLBACK_URL   off-LAN (Tailscale address of elitedesk, set in ~/.config/home-ops/mac.env);
                        unset = the LAN URL, i.e. away from home samples wait in the spool
  INGEST_TOKEN          shared secret (Keychain item home-ops-ingest)
  HOST_NAME             default 'mac'
  METRIC_INTERVAL       seconds, default 30
  METRIC_TOP_N          default 10
  MAC_STATE_DIR         default ~/.local/state/home-ops/mac
  SHIP                  '0' = archive + spool only, default '1'
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))
sys.path.insert(0, str(_here.parent))
import psutil  # noqa: E402
from _common import Shutdown  # noqa: E402
from mac_procs import Tracker, registry, session_of  # noqa: E402
from mac_sample import NetCounter, gpu, ollama_models  # noqa: E402
from mac_ship import Shipper  # noqa: E402
from redact import redact  # noqa: E402

HOST_NAME = os.environ.get('HOST_NAME', 'mac')
INTERVAL = float(os.environ.get('METRIC_INTERVAL', '30'))
TOP_N = int(os.environ.get('METRIC_TOP_N', '10'))
REGISTRY = Path('~/.claude/sessions').expanduser()
ATTRS = ['pid', 'ppid', 'name', 'cpu_percent', 'memory_info', 'create_time', 'cpu_times', 'cmdline']


def read_procs() -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for p in psutil.process_iter(ATTRS, ad_value=None):
        i = p.info
        times = i.get('cpu_times')
        out[i['pid']] = {
            'name': i.get('name') or '?', 'ppid': i.get('ppid') or 0, 'cpu_pct': i.get('cpu_percent') or 0.0,
            'rss_mb': (i['memory_info'].rss // 2**20) if i.get('memory_info') else 0,
            'started': i.get('create_time'), 'cpu_s': (times.user + times.system) if times else None,
            'cmd': redact(' '.join(i.get('cmdline') or []))[:300],
        }
    return out


def tops(procs: dict[int, dict[str, Any]], net: dict[int, tuple[str, int, int]],
         reg: dict[int, dict[str, str]]) -> dict[str, list[dict[str, Any]]]:
    def entry(pid: int, **kv: Any) -> dict[str, Any]:
        sid = session_of(pid, procs, reg)
        return {'name': procs.get(pid, {}).get('name') or net.get(pid, ('?',))[0], 'pid': pid, **kv,
                **({'session': sid} if sid else {})}
    by_cpu = sorted((p for p in procs.items() if p[1]['cpu_pct'] > 0), key=lambda x: -x[1]['cpu_pct'])
    by_mem = sorted(procs.items(), key=lambda x: -x[1]['rss_mb'])
    by_net = sorted(net.items(), key=lambda x: -(x[1][1] + x[1][2]))
    return {
        'top_cpu': [entry(pid, pct=round(p['cpu_pct'], 1)) for pid, p in by_cpu[:TOP_N]],
        'top_mem': [entry(pid, rss_mb=p['rss_mb']) for pid, p in by_mem[:TOP_N]],
        'top_net': [entry(pid, rx=rx, tx=tx) for pid, (_, rx, tx) in by_net[:TOP_N]],
    }


def proc_event(rec: dict[str, Any], ts: str) -> dict[str, Any]:
    who = f' · sesja {rec["session_name"] or rec["session_id"][:8]}' if rec.get('session_id') else ''
    msg = f'proc {rec["event"]}: {rec["name"]} ({rec["reason"]}){who} — {rec["cmd"][:160]}'
    return {'host': HOST_NAME, 'source': 'agent:mac-watcher', 'level': 'info', 'message': msg, 'data': rec, 'ts': ts}


def sample(net: NetCounter, tracker: Tracker,
           last: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    now, ts = time.time(), time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    procs, reg, deltas = read_procs(), registry(REGISTRY), net.deltas()
    mem, g, counters = psutil.virtual_memory(), gpu(), psutil.net_io_counters()
    elapsed = max(now - last['at'], 0.001)
    rx = max(counters.bytes_recv - last['counters'].bytes_recv, 0) / elapsed
    tx = max(counters.bytes_sent - last['counters'].bytes_sent, 0) / elapsed
    last.update(at=now, counters=counters)
    live = [{'pid': pid, **r} for pid, r in reg.items() if pid in procs]
    data: dict[str, Any] = {**tops(procs, deltas, reg), 'interval_s': INTERVAL, 'claude_live': live,
                            'ollama': ollama_models(), 'gpu_renderer_pct': g.get('renderer_pct'),
                            'gpu_mem_mb': (g.get('mem_bytes') or 0) // 2**20}
    metric = {
        'host': HOST_NAME, 'ts': ts, 'cpu_pct': round(psutil.cpu_percent(interval=None), 1),
        'cpu_load_1': round(os.getloadavg()[0], 2), 'mem_pct': round(mem.percent, 1),
        'mem_used_mb': (mem.total - mem.available) // 2**20, 'mem_total_mb': mem.total // 2**20,
        'swap_pct': round(psutil.swap_memory().percent, 1), 'disk_pct': round(psutil.disk_usage('/').percent, 1),
        'net_rx_kbps': round(rx / 1024, 1), 'net_tx_kbps': round(tx / 1024, 1),
        'gpu_pct': g.get('gpu_pct'),
        'gpu_mem_pct': round((g.get('mem_bytes') or 0) / mem.total * 100, 1) if g else None,
        'data': data,
    }
    events = [proc_event(r, ts) for r in tracker.update(procs, reg, deltas, now, INTERVAL)]
    snapshot = {'taken_at': ts, 'cpu_pct': metric['cpu_pct'], 'load_1': metric['cpu_load_1'],
                'sessions': live, 'background': list(tracker.live.values()), 'owners': data['top_cpu'][:5]}
    return metric, events, snapshot


def main() -> None:
    shutdown = Shutdown()
    shutdown.install()
    lan_url = os.environ.get('INGEST_URL', 'http://192.168.1.75:64421/api/ingest')
    shipper = Shipper(host=HOST_NAME, token=os.environ.get('INGEST_TOKEN', ''), lan_url=lan_url,
                      fallback_url=os.environ.get('INGEST_FALLBACK_URL') or lan_url,
                      state_dir=Path(os.environ.get('MAC_STATE_DIR', '~/.local/state/home-ops/mac')).expanduser(),
                      ship=os.environ.get('SHIP', '1') != '0')
    net, tracker = NetCounter(), Tracker()
    psutil.cpu_percent(interval=None)
    net.deltas()
    read_procs()  # primes per-process cpu_percent
    last = {'at': time.time(), 'counters': psutil.net_io_counters()}
    print(f'mac-watcher up: interval={INTERVAL}s ship={shipper.ship}', file=sys.stderr)
    while not shutdown.wait(INTERVAL):
        try:
            shipper.deliver(*sample(net, tracker, last))
        except (psutil.Error, OSError) as e:
            print(f'sample failed: {e}', file=sys.stderr)
    print('mac-watcher down (signal)', file=sys.stderr)


if __name__ == '__main__':
    main()
