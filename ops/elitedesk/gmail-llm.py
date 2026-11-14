#!/usr/bin/env python3
"""gmail-llm.py — run the LLM steps of gmail-daily by hand, without touching Gmail.

  guide                         (re)write the category guide with GUIDE_MODEL (Fable) → gmail.config
  propose [--limit N] [--dry]   weak senders → Claude → gmail.rule_proposal (--dry: print only)
  archive                       what the archive step would move out of the inbox (never acts)
  ask | consume                 top up / act on the "Dziś" questions (needs INGEST_URL/TOKEN)
Trash and inbox come from gmail.message_state, so this works on a test database
(DB=gmail_test) and while the Gmail token is dead.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault('GMAIL_RULES', 'db')
import gmail_classify  # noqa: E402
import gmail_inventory  # noqa: E402
import gmail_llm_daily  # noqa: E402
import gmail_llm_db  # noqa: E402
from seo_db import psql_json  # noqa: E402


def state_ids(column: str) -> set[str]:
    return {r['message_id'] for r in psql_json(f'SELECT message_id FROM gmail.message_state WHERE {column}')}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('step', choices=['guide', 'propose', 'archive', 'ask', 'consume'])
    ap.add_argument('--limit', type=int, default=gmail_llm_daily.MAX_PROPOSE)
    ap.add_argument('--dry', action='store_true', help='propose: print proposals, write nothing')
    args = ap.parse_args()
    cfg = gmail_classify.load_rules(Path(os.environ['GMAIL_RULES']))
    db = gmail_inventory.connect()
    if args.step == 'guide':
        import gmail_llm_guide
        _, labelled = gmail_llm_daily.sender_digests(db, cfg, state_ids('in_trash'), set())
        gmail_llm_guide.ensure_guide(gmail_llm_daily.model_labels(cfg), labelled, max_age_days=0)
    elif args.step == 'propose':
        weak, labelled = gmail_llm_daily.sender_digests(db, cfg, state_ids('in_trash'), gmail_llm_db.known_senders())
        print(f'{len(weak)} senders without a rule or proposal ({len(labelled)} rule-filed as examples); '
              f'asking Claude about {min(args.limit, len(weak))}')
        rows, _ = gmail_llm_daily.propose(weak, gmail_llm_daily.model_labels(cfg), labelled, limit=args.limit,
                                          guide=gmail_llm_db.load_guide()[0])
        print(f'{len(rows)} proposals' + (' (dry run, not stored)' if args.dry else f', stored {gmail_llm_db.insert_proposals(rows)}'))
    elif args.step == 'archive':
        ids = gmail_llm_daily.archive_ids(db, cfg, state_ids('in_inbox AND NOT in_trash'))
        print(f'{len(ids)} inbox messages would be archived (dry run — gmail-daily does it)')
    else:
        from agents.routine_report import Reporter
        reporter = Reporter.from_env('gmail-daily')
        (gmail_llm_daily.ask if args.step == 'ask' else gmail_llm_daily.consume)(reporter)
    return 0


if __name__ == '__main__':
    sys.exit(main())
