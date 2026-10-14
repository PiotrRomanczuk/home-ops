"""routine_report.py — how a routine reports to the digest and asks Piotr.

Two verbs, one per contract (migrations 020 + 021):

  card      end of every run: one headline, ≤5 items, one metric
  decision  before anything irreversible or public: file a question, stop,
            read the answer next run

Usable as a library from Python routines:

    from agents.routine_report import Reporter
    r = Reporter.from_env('seo-analyse')
    r.card('Traffic flat, 2 hypotheses added', items=[('H3: district pages', url)],
           metric={'label': 'clicks 7d', 'value': 12, 'delta': 3})
    for d in r.answers():             # answered, not yet acted on
        if d['answer'] == 'yes': merge(d['ref'])
        r.consume(d['id'])

and as a CLI from bash routines (exit 0 on success, JSON on stdout):

    python3 -m agents.routine_report card seo-analyse "Traffic flat" \\
        --item "H3: district pages|https://…" --metric "clicks 7d=12" --delta 3
    python3 -m agents.routine_report ask seo-improve "Merge PR #52?" \\
        --ref 52 --context https://github.com/…/pull/52 --option yes:Merge --option no:Skip
    python3 -m agents.routine_report answers seo-improve

Env: INGEST_URL + INGEST_TOKEN, same as every agent.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable


class Reporter:
    def __init__(self, routine: str, base: str, token: str, timeout: float = 10.0) -> None:
        self.routine = routine
        self.base = base.rstrip('/')
        self.token = token
        self.timeout = timeout

    @classmethod
    def from_env(cls, routine: str) -> 'Reporter':
        url = (os.environ.get('INGEST_URL') or '').rstrip('/')
        token = os.environ.get('INGEST_TOKEN', '')
        if not url or not token:
            raise SystemExit('INGEST_URL and INGEST_TOKEN required')
        return cls(routine, url[: -len('/api/ingest')] if url.endswith('/api/ingest') else url, token)

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            'X-Ingest-Token': self.token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors='replace')[:300]
            raise RuntimeError(f'{method} {path} → HTTP {e.code}: {detail}') from None

    def card(self, headline: str, *, status: str = 'ok', slug: str | None = None,
             items: Iterable[tuple[str, str | None]] = (), metric: dict[str, Any] | None = None,
             fresh_hours: int = 26) -> dict[str, Any]:
        body: dict[str, Any] = {
            'routine': self.routine, 'headline': headline[:200], 'status': status, 'fresh_hours': fresh_hours,
            'items': [{'text': t[:160], **({'url': u} if u else {})} for t, u in list(items)[:5]],
        }
        if slug:
            body['slug'] = slug
        if metric:
            body['metric'] = metric
        return self._call('POST', '/api/cards', body)['card']

    def ask(self, question: str, *, options: list[dict[str, str]] | None = None, ref: str | None = None,
            slug: str | None = None, context_url: str | None = None, detail: str | None = None,
            expires_hours: int = 72, parent_id: int | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {'routine': self.routine, 'question': question[:300], 'expires_hours': expires_hours}
        for k, v in (('options', options), ('ref', ref), ('slug', slug), ('context_url', context_url),
                     ('detail', detail), ('parent_id', parent_id)):
            if v is not None:
                body[k] = v
        return self._call('POST', '/api/decisions', body)['decision']

    def open_refs(self) -> set[str]:
        """refs this routine already asked about and that still wait — so a
        daily run does not file the same question twice."""
        q = urllib.parse.urlencode({'state': 'open', 'routine': self.routine, 'limit': 200})
        return {d['ref'] for d in self._call('GET', f'/api/decisions?{q}')['decisions'] if d.get('ref')}

    def answers(self) -> list[dict[str, Any]]:
        """Answered decisions this routine has not acted on yet."""
        q = urllib.parse.urlencode({'state': 'answered', 'routine': self.routine, 'limit': 200})
        return [d for d in self._call('GET', f'/api/decisions?{q}')['decisions'] if not d.get('consumed_at')]

    def consume(self, decision_id: int | str) -> None:
        self._call('POST', f'/api/decisions/{int(decision_id)}/consume', {})


def _parse_option(s: str) -> dict[str, str]:
    key, _, label = s.partition(':')
    return {'key': key, 'label': label or key}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog='routine_report')
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('card')
    c.add_argument('routine'); c.add_argument('headline')
    c.add_argument('--status', default='ok', choices=['ok', 'warn', 'fail', 'skipped'])
    c.add_argument('--slug'); c.add_argument('--item', action='append', default=[], help='text or text|url')
    c.add_argument('--metric', help='label=value'); c.add_argument('--delta', type=float)
    c.add_argument('--lower-is-better', action='store_true'); c.add_argument('--fresh-hours', type=int, default=26)
    a = sub.add_parser('ask')
    a.add_argument('routine'); a.add_argument('question')
    a.add_argument('--option', action='append', help='key[:label], repeat; default yes/no')
    a.add_argument('--ref'); a.add_argument('--slug'); a.add_argument('--context'); a.add_argument('--detail')
    a.add_argument('--expires-hours', type=int, default=72)
    a.add_argument('--skip-if-open', action='store_true', help='do nothing if --ref is already waiting')
    w = sub.add_parser('answers'); w.add_argument('routine')
    k = sub.add_parser('consume'); k.add_argument('routine'); k.add_argument('id', type=int)
    ns = ap.parse_args(argv)
    r = Reporter.from_env(ns.routine)

    if ns.cmd == 'card':
        metric = None
        if ns.metric:
            label, _, value = ns.metric.partition('=')
            num: Any = float(value) if value.replace('.', '', 1).lstrip('-').isdigit() else value
            metric = {'label': label, 'value': int(num) if isinstance(num, float) and num.is_integer() else num}
            if ns.delta is not None:
                metric['delta'] = int(ns.delta) if ns.delta.is_integer() else ns.delta
            if ns.lower_is_better:
                metric['lower_is_better'] = True
        items = [(i.partition('|')[0], i.partition('|')[2] or None) for i in ns.item]
        out: Any = r.card(ns.headline, status=ns.status, slug=ns.slug, items=items, metric=metric,
                          fresh_hours=ns.fresh_hours)
    elif ns.cmd == 'ask':
        if ns.skip_if_open and ns.ref and ns.ref in r.open_refs():
            out = {'skipped': True, 'reason': f'ref {ns.ref} already waiting'}
        else:
            opts = [_parse_option(o) for o in ns.option] if ns.option else None
            out = r.ask(ns.question, options=opts, ref=ns.ref, slug=ns.slug, context_url=ns.context,
                        detail=ns.detail, expires_hours=ns.expires_hours)
    elif ns.cmd == 'answers':
        out = r.answers()
    else:
        r.consume(ns.id)
        out = {'consumed': ns.id}
    json.dump(out, sys.stdout, ensure_ascii=False)
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
