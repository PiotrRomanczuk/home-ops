#!/usr/bin/env python3
"""gmail_cleanup.py — CLI for the personal Gmail cleanup (p.romanczuk@gmail.com).

Order is deliberate: categorise every message first, delete nothing until the
categories are reviewed. Subcommands:
  auth                 one-time OAuth consent (browser)
  inventory [--api]    fetch metadata of every message into local SQLite (IMAP by default; --api = REST, slow)
  senders [-n N]       top senders table from the inventory
  classify             dry-run: category report (markdown) from the inventory, no Gmail writes
  apply                add the category labels in Gmail (labels only; journaled)
  undo JOURNAL         strip the labels a previous `apply` added
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gmail_apply  # noqa: E402
import gmail_auth  # noqa: E402
import gmail_classify  # noqa: E402
import gmail_imap  # noqa: E402
import gmail_inventory  # noqa: E402
from gmail_api import Gmail  # noqa: E402


def cmd_inventory(args: argparse.Namespace) -> None:
    db = gmail_inventory.connect()
    gmail = Gmail(gmail_auth.access_token)
    if args.api:
        gmail_inventory.sync(gmail, db, workers=args.workers, query=args.query)
    else:
        email = gmail.call('GET', '/profile')['emailAddress']
        gmail_imap.sync(gmail_imap.connect(email, gmail_auth.access_token()), db)
    total = db.execute('SELECT COUNT(*) FROM messages').fetchone()[0]
    print(f'inventory: {total} messages in {gmail_inventory.DB_PATH}')


def cmd_senders(args: argparse.Namespace) -> None:
    db = gmail_inventory.connect()
    print('count | unread | years | unsub% | sender | sample subject')
    for addr, _dom, n, unread, y0, y1, unsub, subj in gmail_inventory.senders(db, args.n):
        print(f'{n:6} | {unread:6} | {y0}-{y1} | {unsub:5.0f} | {addr} | {subj[:60]}')


def cmd_classify(args: argparse.Namespace) -> None:
    db = gmail_inventory.connect()
    md = gmail_classify.report(db, gmail_classify.load_rules(), top=args.top)
    out = gmail_inventory.STATE_DIR / 'classify-report.md'
    out.write_text(md + '\n')
    print(md)
    print(f'\n(saved to {out})')


def cmd_apply(args: argparse.Namespace) -> None:
    db = gmail_inventory.connect()
    mapping = gmail_classify.classify_all(db, gmail_classify.load_rules())
    journal = gmail_inventory.STATE_DIR / f'journal-{time.strftime("%Y%m%d-%H%M%S")}.jsonl'
    n = gmail_apply.apply_categories(Gmail(gmail_auth.access_token), mapping, journal)
    print(f'labelled {n} messages; journal: {journal}')


def cmd_undo(args: argparse.Namespace) -> None:
    n = gmail_apply.undo(Gmail(gmail_auth.access_token), Path(args.journal))
    print(f'removed labels from {n} messages')


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('auth').set_defaults(fn=lambda a: gmail_auth.authorize(a.port), port=8765)
    inv = sub.add_parser('inventory')
    inv.add_argument('--api', action='store_true', help='REST instead of IMAP (quota-bound, ~3 msg/s)')
    inv.add_argument('--workers', type=int, default=8)
    inv.add_argument('--query', default='', help='Gmail search to limit the pass (default: all)')
    inv.set_defaults(fn=cmd_inventory)
    snd = sub.add_parser('senders')
    snd.add_argument('-n', type=int, default=100)
    snd.set_defaults(fn=cmd_senders)
    cls = sub.add_parser('classify')
    cls.add_argument('--top', type=int, default=8)
    cls.set_defaults(fn=cmd_classify)
    sub.add_parser('apply').set_defaults(fn=cmd_apply)
    und = sub.add_parser('undo')
    und.add_argument('journal')
    und.set_defaults(fn=cmd_undo)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == '__main__':
    main()
