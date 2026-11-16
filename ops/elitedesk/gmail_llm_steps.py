"""gmail_llm_steps.py — the model steps of gmail-daily, fenced off from the mail run.

`llm_steps`: proposals for uncovered senders → questions on "Dziś" → archive per accepted inbox policy.
`fenced`: run an optional step so that its failure is logged, never raised.
"""
from __future__ import annotations

from pathlib import Path

import gmail_apply
import gmail_labels
import gmail_llm_daily
from gmail_api import Gmail


def llm_steps(gmail: Gmail, db, cfg: dict, trash: set[str], reporter, journal: Path, log=print) -> tuple[int, int]:
    """Claude proposals for uncovered senders, questions on "Dziś", archive per accepted inbox policy."""
    import gmail_llm_db
    import gmail_llm_guide
    weak, labelled = gmail_llm_daily.sender_digests(db, cfg, trash, gmail_llm_db.known_senders())
    labels = gmail_llm_daily.model_labels(cfg)
    guide = gmail_llm_guide.ensure_guide(labels, labelled, log=log) if weak else ''
    rows, _reachable = gmail_llm_daily.propose(weak, labels, labelled, log, guide=guide, freemail=cfg['freemail'])
    gmail_llm_db.insert_proposals(rows)
    if reporter:
        gmail_llm_daily.ask(reporter, log)
    ids = gmail_llm_daily.archive_ids(db, cfg, set(gmail.iter_ids('in:inbox')))
    if ids:
        gmail_apply.move(gmail, 'archive', ids, set(ids), journal, note='rule inbox=archive', log=log,
                         protected=gmail_labels.protected_ids(db, cfg))
    return len(rows), len(ids)


def fenced(step: str, fn, default, log=print):
    """Run an optional step: any failure (Dziś down, psql, migration 031 missing) is logged, not raised."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 — the mail run must not depend on the model or on "Dziś"
        log(f'{step} skipped: {e}')
        return default
