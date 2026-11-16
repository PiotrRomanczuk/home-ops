"""gmail_llm_daily.py — the LLM steps of gmail-daily (and a CLI to run them by hand).

  consume  answers from "Dziś" → accept/reject proposals (accepted = new gmail.rule row)
  propose  senders whose mail only lands in weak buckets (no rule) → Claude (batches) → gmail.rule_proposal
  ask      keep at most MAX_OPEN proposal questions open on "Dziś"
  archive  inbox mail matched by a rule with inbox='archive', never protected mail → archive (journaled)
Nothing here trashes mail. Pure helpers (digests, archive selection) are unit-tested.
"""
from __future__ import annotations

import sqlite3

import gmail_classify
import gmail_llm
from gmail_llm_digest import sender_digests  # noqa: F401  (re-exported for callers and tests)

MAX_PROPOSE, MAX_OPEN = 40, 3
REF = 'gmail-proposal:'
OPTIONS = [{'key': 'tak', 'label': 'Tak', 'consequence': 'reguła + etykieta (+ archiwizacja, jeśli zaproponowana)'},
           {'key': 'tak-zostaw', 'label': 'Tak, ale w skrzynce', 'consequence': 'reguła + etykieta, bez archiwizacji'},
           {'key': 'nie', 'label': 'Nie', 'consequence': 'bez reguły; nadawca nie wróci z pytaniem'}]


def model_labels(cfg: dict) -> list[str]:
    """Categories the model may choose: every rule and subrule label plus the built-in buckets."""
    return gmail_llm.labels_from([r.label for r in cfg['rules']] + [r.label for _, r in cfg.get('subrules', ())])


def propose(digests: list[dict], labels: list[str], labelled: list[dict], log=print,
            limit: int = MAX_PROPOSE, guide: str = '', freemail: set[str] | None = None) -> tuple[list[tuple], bool]:
    """(proposal rows, reachable). Batches of gmail_llm.BATCH; stops at the first failed call — try tomorrow.

    `freemail` = cfg['freemail'] (the owner's free-mail domains, never a domain rule). A proposal the model
    did not answer properly (`valid` False) is not stored, so the sender comes back tomorrow.
    """
    import gmail_llm_db
    rows: list[tuple] = []
    todo = digests[:limit]
    shots = gmail_llm.examples(labelled, set())
    blocked = (freemail or set()) | gmail_llm.FREEMAIL
    for start in range(0, len(todo), gmail_llm.BATCH):
        batch = todo[start:start + gmail_llm.BATCH]
        try:
            proposals, response = gmail_llm.propose_batch(batch, labels, shots, guide=guide, freemail=blocked)
        except gmail_llm.ClaudeError as exc:
            log(f'claude failed ({exc}); {len(rows)} proposals this run')
            return rows, False
        items = {i.get('sender'): i for i in response['structured_output'].get('proposals', []) if isinstance(i, dict)}
        meta = {k: response.get(k) for k in ('session_id', 'total_cost_usd', 'duration_ms', 'usage', 'modelUsage')}
        for s, p in zip(batch, proposals):
            if not p.valid:
                log(f'no usable answer for {s["sender"]}; asking again tomorrow')
                continue
            rows.append(gmail_llm_db.proposal_row(p.to_json(), s, {'item': items.get(s['sender']), 'batch': meta},
                                                  gmail_llm.MODEL, gmail_llm.PROMPT_VERSION))
            log(f'proposal: {s["sender"]} → {p.label} / {p.inbox} ({p.confidence:.2f})')
    return rows, True


def consume(reporter, log=print) -> int:
    """Act on answered "Dziś" questions about proposals, then mark them consumed."""
    import gmail_llm_db
    open_by_id = {str(p['id']): p for p in gmail_llm_db.proposed()}
    done = 0
    for d in reporter.answers():
        ref = str(d.get('ref') or '')
        if not ref.startswith(REF):
            continue
        p = open_by_id.get(ref[len(REF):])
        if p and d.get('answer') in ('tak', 'tak-zostaw'):
            inbox = p['inbox'] if d['answer'] == 'tak' else 'keep'
            gmail_llm_db.accept(p['id'], p['label'], inbox, 'dzis')
        elif p and d.get('answer') == 'nie':
            gmail_llm_db.reject(p['id'], 'dzis')
        reporter.consume(d['id'])
        done += 1
    log(f'consumed {done} answers')
    return done


def question(p: dict) -> tuple[str, str]:
    sample = p.get('sample') or {}
    subjects = [s for s in sample.get('subjects', []) if s][:2]
    where = 'do archiwum' if p['inbox'] == 'archive' else 'zostaje w skrzynce'
    q = f"Gmail: {p['sender_key']} ({sample.get('n', '?')} maili) → {p['label']}, {where}?"
    detail = f"Model {p['model']} ({p['confidence']:.2f}): {p.get('reason') or ''}\nPrzykłady: " + ' · '.join(subjects)
    return q, detail


def ask(reporter, log=print) -> int:
    """Top up open proposal questions on "Dziś" to MAX_OPEN (biggest senders first); an expired one is asked again."""
    import gmail_llm_db
    open_refs = {r for r in reporter.open_refs() if r.startswith(REF)}
    asked = 0
    for p in gmail_llm_db.proposed():
        if len(open_refs) + asked >= MAX_OPEN:
            break
        if f'{REF}{p["id"]}' in open_refs:  # decision_id alone proves nothing: the question may have expired
            continue
        q, detail = question(p)
        d = reporter.ask(q, options=OPTIONS, ref=f'{REF}{p["id"]}', detail=detail, expires_hours=168)
        gmail_llm_db.set_decision(p['id'], d['id'])
        asked += 1
    log(f'asked {asked} new questions')
    return asked


def archive_ids(db: sqlite3.Connection, cfg: dict, inbox: set[str]) -> list[str]:
    """Inbox messages whose first matching rule says inbox='archive'.

    Never protected mail and never mail from a correspondent (an address the owner has written to),
    even when a hand-made '@domain' rule would match it.
    """
    db.row_factory = sqlite3.Row
    people = gmail_classify.correspondents(db, cfg['me'])
    out = []
    for r in db.execute('SELECT * FROM messages'):
        if r['id'] not in inbox or r['from_addr'] in people:
            continue
        rule = next((x for x in cfg['rules'] if x.hits(r['from_addr'] or '', r['subject'] or '')), None)
        if rule and rule.inbox == 'archive' and not gmail_classify.is_protected(rule.label, r['subject'], r['labels'], cfg):
            out.append(r['id'])
    return sorted(out)
