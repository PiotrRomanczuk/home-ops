"""digest_html.py — email-safe HTML primitives for the digest.

Mail clients ignore <style> blocks and most CSS, so every element carries
inline styles. One light palette, system font, generous spacing: the email
should read like a short note, not a terminal. render-digest.py composes
sections from these; nothing here touches data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo

WARSAW = ZoneInfo('Europe/Warsaw')
FONT = "-apple-system,BlinkMacSystemFont,'SF Pro Text','Helvetica Neue',Helvetica,Arial,sans-serif"
INK, INK2, INK3, LINE = '#1d1d1f', '#6e6e73', '#aeaeb2', '#e5e5ea'
GOOD, WARN, BAD, LINK = '#34c759', '#ff9f0a', '#ff3b30', '#0066cc'
STATUS_COLOR = {'ok': GOOD, 'warn': WARN, 'bad': BAD, 'fail': BAD, 'off': INK3, 'skipped': INK3}


def e(s: object) -> str:
    return escape('' if s is None else str(s), quote=True)


def parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace('Z', '+00:00'))
    except ValueError:
        return None


def when(ts: str | None, now: datetime) -> str:
    """'3 min ago' / 'yesterday 22:48' / 'since 13 Sep' — whatever reads best."""
    d = parse_ts(ts)
    if d is None:
        return 'never'
    delta = now - d
    s = int(delta.total_seconds())
    if s < -90:  # a deadline: 'in 5 h', 'Fri 07:00'
        ahead = -s
        if ahead < 3600:
            return f'in {ahead // 60} min'
        if ahead < 86400:
            return f'in {ahead // 3600} h'
        return d.astimezone(WARSAW).strftime('%a %H:%M')
    if s < 90:
        return 'just now'
    if s < 3600:
        return f'{s // 60} min ago'
    local = d.astimezone(WARSAW)
    if delta.days < 1:
        return f'{s // 3600} h ago'
    if delta.days == 1:
        return f"yesterday {local.strftime('%H:%M')}"
    if delta.days < 7:
        return local.strftime('%a %H:%M')
    return local.strftime('%-d %b')


def dot(color: str) -> str:
    return (f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;'
            f'background:{color};margin-right:12px;vertical-align:1px"></span>')


def section(title: str, body: str) -> str:
    return (f'<div style="padding:22px 0;border-top:1px solid {LINE}">'
            f'<div style="font-size:13px;font-weight:600;color:{INK2};text-transform:uppercase;'
            f'letter-spacing:.05em;margin-bottom:10px">{e(title)}</div>{body}</div>')


def row(color: str, title: str, sub: str | None = None, right: str | None = None) -> str:
    right_html = (f'<td align="right" valign="top" style="font-size:14px;color:{INK2};white-space:nowrap;'
                  f'padding-left:12px;font-variant-numeric:tabular-nums">{right}</td>') if right else ''
    sub_html = f'<div style="font-size:14px;color:{INK2};margin-top:2px;line-height:1.4">{sub}</div>' if sub else ''
    return (f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:12px"><tr>'
            f'<td valign="top" style="width:22px">{dot(color)}</td>'
            f'<td valign="top" style="font-size:16px;font-weight:500;color:{INK};line-height:1.35">{title}{sub_html}</td>'
            f'{right_html}</tr></table>')


def quiet(text: str) -> str:
    return f'<p style="font-size:14px;color:{INK2};margin:0 0 8px;line-height:1.5">{text}</p>'


def strong(text: str) -> str:
    return f'<b style="color:{INK};font-weight:500">{text}</b>'


def link(url: str, text: str) -> str:
    return f'<a href="{e(url)}" style="color:{LINK};text-decoration:none">{e(text)}</a>'


def button(url: str, text: str, danger: bool = False) -> str:
    bg = BAD if danger else INK
    return (f'<a href="{e(url)}" style="display:inline-block;background:{bg};color:#fff;font-size:14px;'
            f'font-weight:600;padding:9px 16px;border-radius:10px;text-decoration:none;margin:6px 8px 0 0">{e(text)}</a>')


def document(eyebrow_left: str, eyebrow_right: str, headline: str, lede: str, sections: list[str], footer: str) -> str:
    body = ''.join(sections)
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(headline)}</title></head>'
            f'<body style="margin:0;background:#f5f5f7;padding:24px 12px;font-family:{FONT};color:{INK};'
            f'-webkit-font-smoothing:antialiased">'
            f'<div style="max-width:560px;margin:0 auto;background:#fff;border-radius:18px;padding:32px 28px 24px">'
            f'<div style="font-size:12px;color:{INK2};letter-spacing:.04em;text-transform:uppercase">'
            f'<span>{e(eyebrow_left)}</span><span style="float:right">{e(eyebrow_right)}</span></div>'
            f'<h1 style="font-size:28px;line-height:1.15;font-weight:600;letter-spacing:-.02em;margin:14px 0 8px">{e(headline)}</h1>'
            f'<p style="font-size:16px;color:{INK2};margin:0 0 26px;line-height:1.45">{lede}</p>'
            f'{body}'
            f'<div style="padding-top:20px;border-top:1px solid {LINE};font-size:12px;color:{INK3}">{footer}</div>'
            f'</div></body></html>')
