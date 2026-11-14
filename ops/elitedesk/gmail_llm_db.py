"""gmail_llm_db.py — gmail.rule_proposal (migration 031): store, list, accept, reject.

Accepting a proposal appends an ordinary gmail.rule row (end of the order, so it
only ever catches senders no earlier rule matched) and links it back. Writes go
through psql variables (seo_db.psql_exec), never string-built SQL values.
"""
from __future__ import annotations

import json

import gmail_db
from seo_db import psql_exec, psql_json

PROPOSAL_COLS = ('sender', 'sender_key', 'scope', 'label', 'inbox', 'confidence', 'reason', 'model',
                 'prompt_version', 'sample', 'response')

ACCEPT_SQL = """
WITH p AS (SELECT * FROM gmail.rule_proposal WHERE id = :'id' AND status = 'proposed'),
r AS (INSERT INTO gmail.rule (position, kind, label, senders, inbox, note)
      SELECT (SELECT COALESCE(max(position), 0) + 1 FROM gmail.rule WHERE kind = 'rule'), 'rule', :'label',
             ARRAY[p.sender_key], :'inbox', 'llm ' || p.model || ' ' || current_date FROM p
      RETURNING id)
UPDATE gmail.rule_proposal SET status = 'accepted', label = :'label', inbox = :'inbox',
       rule_id = (SELECT id FROM r), decided_via = :'via', decided_at = now()
WHERE id = :'id' AND status = 'proposed';
"""
REJECT_SQL = """UPDATE gmail.rule_proposal SET status = 'rejected', decided_via = :'via', decided_at = now()
WHERE id = :'id' AND status = 'proposed';"""
DECISION_SQL = "UPDATE gmail.rule_proposal SET decision_id = :'decision' WHERE id = :'id';"


def proposal_row(proposal: dict, sample: dict, response: dict, model: str, prompt_version: str) -> tuple:
    """gmail_llm.Proposal.to_json() + context → one gmail.rule_proposal row (PROPOSAL_COLS order)."""
    return (proposal['sender'], proposal['sender_key'], proposal['scope'], proposal['label'], proposal['inbox'],
            proposal['confidence'], proposal['reason'], model, prompt_version,
            json.dumps(sample, ensure_ascii=False), json.dumps(response, ensure_ascii=False))


def known_senders() -> set[str]:
    """Every sender already proposed (any status) — a rejected sender is not asked again."""
    return {r['sender'] for r in psql_json('SELECT sender FROM gmail.rule_proposal')}


def insert_proposals(rows: list[tuple]) -> int:
    if not rows:
        return 0
    cols = ', '.join(PROPOSAL_COLS)
    gmail_db.psql_script('CREATE TEMP TABLE stage (LIKE gmail.rule_proposal INCLUDING DEFAULTS) ON COMMIT DROP;\n'
                         + gmail_db.copy_block('stage', PROPOSAL_COLS, rows)
                         + f'INSERT INTO gmail.rule_proposal ({cols}) SELECT {cols} FROM stage '
                         'ON CONFLICT (sender) DO NOTHING;\n')
    return len(rows)


def proposed() -> list[dict]:
    """Open proposals, biggest senders first."""
    return psql_json("SELECT id, sender, sender_key, scope, label, inbox, confidence, reason, model, sample, "
                     "decision_id FROM gmail.rule_proposal WHERE status = 'proposed' "
                     "ORDER BY (sample->>'n')::int DESC NULLS LAST, id")


def accept(proposal_id: int, label: str, inbox: str, via: str) -> None:
    psql_exec(ACCEPT_SQL, {'id': str(proposal_id), 'label': label, 'inbox': inbox, 'via': via})


def reject(proposal_id: int, via: str) -> None:
    psql_exec(REJECT_SQL, {'id': str(proposal_id), 'via': via})


def set_decision(proposal_id: int, decision_id: int) -> None:
    psql_exec(DECISION_SQL, {'id': str(proposal_id), 'decision': str(decision_id)})
