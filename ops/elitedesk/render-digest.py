#!/usr/bin/env python3
"""render-digest.py — turn the /api/digest JSON model into the email HTML.

Reads the model on stdin, writes HTML on stdout. Pure: no network, no
database, so `daily-digest.sh` can pipe `curl … | render-digest.py` and the
unit tests can feed fixtures. Optional extras (legacy digest.d/*.txt cards)
arrive inside the model under "extras": [{name, text}].

Layout (top to bottom, each section only when it has content):
  verdict · needs you (decisions) · needs attention (problems, unhealthy
  hosts) · hosts · sites · today · routines (cards) · overnight · extras
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from digest_html import (BAD, GOOD, INK2, INK3, STATUS_COLOR, WARN, WARSAW, button, document, e, link,  # noqa: E402
                         quiet, row, section, strong, when)

NO_RE = {'no', 'reject', 'skip', 'decline'}


def sec_decisions(m: dict, now: datetime) -> str:
    rows = []
    for d in m.get('decisions', []):
        btns = ''.join(button(d['links'].get(o['key'], '#'), o['label'], o['key'] in NO_RE) for o in d.get('options', []))
        ctx = f" · {link(d['context_url'], 'context')}" if d.get('context_url') else ''
        sub = f"{e(d['routine'])} · expires {when(d['expires_at'], now)}{ctx}<br>{btns}"
        rows.append(row(INK2, e(d['question']), sub))
    return section('Needs you', ''.join(rows)) if rows else ''


def sec_attention(m: dict, now: datetime) -> str:
    rows = []
    for p in m.get('problems', []):
        since = when(p.get('first_seen'), now)
        more = p.get('n_patterns', 1) - 1
        kinds = f' · {more} other message{"s" if more != 1 else ""}' if more > 0 else ''
        rows.append(row(BAD if p.get('level') == 'fatal' else WARN,
                        e((p.get('sample') or p['pattern']).strip()[:120]),
                        f"{e(p['source'])} on {e(p['host'])} · {p['n_24h']}× in 24 h{kinds} · since {since}"))
    for h in m.get('hosts', []):
        if h['status'] == 'bad':
            rows.append(row(BAD, f"{e(h['host'])} stopped reporting", f"last sample {when(h['last_metric_ts'], now)}"))
        elif h['status'] == 'warn':
            rows.append(row(WARN, f"{e(h['host'])} disk is {int(h['disk_pct'])}% full", 'Free space before it hits 100%.'))
    if not rows:
        return ''
    muted = m.get('muted_problems') or 0
    foot = quiet(f'{muted} known-noise pattern{"s" if muted != 1 else ""} hidden.') if muted else ''
    return section('Needs attention', ''.join(rows) + foot)


def sec_hosts(m: dict, now: datetime) -> str:
    rows = []
    for h in m.get('hosts', []):
        if h['status'] == 'off':
            continue  # summarised in one line below
        if h['status'] == 'bad':
            right = f"silent since {when(h['last_metric_ts'], now)}"
        else:
            right = f"cpu {int(h['cpu_pct'] or 0)}% · mem {int(h['mem_pct'] or 0)}% · disk {int(h['disk_pct'] or 0)}%"
        rows.append(row(STATUS_COLOR[h['status']], e(h['host']), None, right))
    off = [h['host'] for h in m.get('hosts', []) if h['status'] == 'off']
    if off:
        rows.append(row(STATUS_COLOR['off'], 'Logs only, no metrics', e(', '.join(off))))
    return section('Hosts', ''.join(rows)) if rows else ''


def sec_sites(m: dict, now: datetime) -> str:
    rows = [row(BAD if s['level'] == 'error' else GOOD, e(s['message'][:100]),
                f"{e(s['source'][4:])} · {when(s['ts'], now)}") for s in m.get('sites', [])]
    return section('Your sites', ''.join(rows)) if rows else ''


def sec_today(m: dict) -> str:
    if not m.get('focus') and not m.get('next'):
        return ''
    focus = (f'<p style="font-size:18px;font-weight:600;margin:0 0 10px;letter-spacing:-.01em">{e(m["focus"])}</p>'
             if m.get('focus') else '')
    nxt = quiet('Then: ' + ' · '.join(e(t) for t in m['next'])) if m.get('next') else ''
    return section('Today', focus + nxt)


def card_sub(c: dict, now: datetime) -> str:
    bits = []
    for it in (c.get('items') or [])[:5]:
        bits.append(link(it['url'], it['text']) if it.get('url') else e(it['text']))
    met = c.get('metric') or {}
    if met.get('label') is not None:
        delta = met.get('delta')
        better = delta is not None and ((delta < 0) if met.get('lower_is_better') else (delta > 0))
        arrow = '' if delta in (None, 0) else (f' <span style="color:{GOOD if better else BAD}">'
                                               f'{"+" if delta > 0 else ""}{delta}{e(met.get("unit") or "")}</span>')
        bits.append(f"{e(met['label'])} {strong(e(met['value']))}{e(met.get('unit') or '')}{arrow}")
    runs = c.get('runs_7d', 0)
    trend = f"{runs} run{'s' if runs != 1 else ''} this week" + (f", {c['runs_prev_7d']} last" if c.get('runs_prev_7d') else '')
    bits.append(f'<span style="color:{INK3}">{when(c["ran_at"], now)} · {trend}</span>')
    return '<br>'.join(bits)


def sec_routines(m: dict, now: datetime) -> str:
    rows = []
    acc = {a['routine']: a for a in m.get('acceptance', [])}
    for c in m.get('cards', []):
        if not c.get('is_fresh'):
            rows.append(row(INK3, f"{e(c['routine'])} did not run", f"last card {when(c['ran_at'], now)}"))
            continue
        title = f"{e(c['routine'])}: {e(c['headline'])}"
        sub = card_sub(c, now)
        a = acc.get(c['routine'])
        if a and a['answered']:
            sub += f'<br><span style="color:{INK3}">you accepted {a["accepted"]} of {a["answered"]} proposals in 30 days</span>'
        rows.append(row(STATUS_COLOR.get(c['status'], GOOD), title, sub))
    return section('Routines', ''.join(rows)) if rows else ''


def sec_extras(m: dict) -> str:
    out = []
    if m.get('narrative'):
        out.append(section('Overnight', f'<pre style="margin:0;font:inherit;font-size:14px;color:{INK2};'
                                        f'white-space:pre-wrap;line-height:1.5">{e(m["narrative"])}</pre>'))
    for x in m.get('extras', []):
        out.append(section(x['name'], f'<pre style="margin:0;font:inherit;font-size:13px;color:{INK2};'
                                      f'white-space:pre-wrap;line-height:1.45">{e(x["text"])}</pre>'))
    return ''.join(out)


def lede_for(m: dict) -> str:
    n_dec, n_prob = len(m.get('decisions', [])), len(m.get('problems', []))
    off = [h['host'] for h in m.get('hosts', []) if h['status'] == 'off']
    fresh = sum(1 for c in m.get('cards', []) if c.get('is_fresh'))
    parts = []
    if fresh:
        parts.append(f'{fresh} routine{"s" if fresh != 1 else ""} reported in.')
    if n_prob:
        parts.append(f'{n_prob} recurring problem{"s" if n_prob != 1 else ""} below.')
    if off:
        parts.append(f"{len(off)} host name{'s' if len(off) != 1 else ''} send logs but no metrics.")
    if n_dec:
        parts.append('Tap a button to answer; nothing happens until you confirm.')
    return e(' '.join(parts)) or 'Nothing to report.'


def render(m: dict, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(WARSAW)
    mode = m.get('mode', 'morning').capitalize()
    sections = [sec_decisions(m, now), sec_attention(m, now), sec_hosts(m, now), sec_sites(m, now),
                sec_today(m), sec_routines(m, now), sec_extras(m)]
    board = m.get('board_url')
    footer = (f'daily-digest · {mode.lower()}' + (f' · {link(board, "Open the console →")}' if board else ''))
    return document(f'Home-ops · {mode}', local.strftime('%a %-d %b · %H:%M'), m.get('verdict', ''),
                    lede_for(m), [s for s in sections if s], footer)


if __name__ == '__main__':
    sys.stdout.write(render(json.load(sys.stdin)))
