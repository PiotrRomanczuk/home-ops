"""gmail_llm_daily.py — the LLM steps of gmail-daily (and a CLI to run them by hand).

  consume  answers from "Dziś" → accept/reject proposals (accepted = new gmail.rule row)
  propose  senders whose mail only lands in weak buckets (no rule) → Claude (batches) → gmail.rule_proposal
  ask      keep at most MAX_OPEN proposal questions open on "Dziś"
  archive  inbox mail matched by a rule with inbox='archive', never protected mail → archive (journaled)
Nothing here trashes mail. Pure helpers (digests, archive selection) are unit-tested.
"""
from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict

import gmail_classify
import gmail_llm

WEAK = {'none', 'tab', 'unsub'}
MAX_PROPOSE, MAX_OPEN, MAX_SUBJECTS = 40, 3, 20
REF = 'gmail-proposal:'
OPTIONS = [{'key': 'tak', 'label': 'Tak', 'consequence': 'reguła + etykieta (+ archiwizacja, jeśli zaproponowana)'},
           {'key': 'tak-zostaw', 'label': 'Tak, ale w skrzynce', 'consequence': 'reguła + etykieta, bez archiwizacji'},
           {'key': 'nie', 'label': 'Nie', 'consequence': 'bez reguły; nadawca nie wróci z pytaniem'}]


def model_labels(cfg: dict) -> list[str]:
    """Categories the model may choose: every rule and subrule label plus the built-in buckets."""
    return gmail_llm.labels_from([r.label for r in cfg['rules']] + [r.label for _, r in cfg.get('subrules', ())])


def _tab(labels: str) -> str:
    for key, name in (('PROMOTIONS', 'promotions'), ('SOCIAL', 'social'), ('UPDATES', 'updates'), ('FORUMS', 'forums')):
        if f'CATEGORY_{key}' in (labels or ''):
            return name
    return 'primary'


def _digest(sender: str, rows: list) -> dict:
    return {'sender': sender, 'name': rows[0]['from_name'] or '', 'domain': rows[0]['from_domain'] or '',
            'n': len(rows), 'unsub_share': round(sum(bool(r['has_unsub']) for r in rows) / len(rows), 2),
            'tab': Counter(_tab(r['labels']) for r in rows).most_common(1)[0][0],
            'subjects': [r['subject'] or '' for r in rows[:MAX_SUBJECTS]]}


def sender_digests(db: sqlite3.Connection, cfg: dict, trash: set[str], skip: set[str]) -> tuple[list[dict], list[dict]]:
    """(weak, labelled) sender digests in one pass over the inventory.

    weak     — every message of the sender has a weak reason (no rule): what Claude is asked about
    labelled — every message filed by rules under one label: the example senders shown per category
    """
    db.row_factory = sqlite3.Row
    people = gmail_classify.correspondents(db, cfg['me'])
    groups: dict[str, list] = defaultdict(list)
    for r in db.execute('SELECT * FROM messages ORDER BY internal_ms DESC'):
        if r['id'] not in trash and r['from_addr'] and r['from_addr'] not in cfg['me']:
            groups[r['from_addr']].append(r)
    weak, labelled = [], []
    for sender, rows in groups.items():
        verdicts = {gmail_classify.classify(r, cfg, people) for r in rows}
        if all(reason in WEAK for _, reason in verdicts) and sender not in skip:
            weak.append(_digest(sender, rows))
        elif len(verdicts) == 1 and next(iter(verdicts))[1] == 'rule':
            labelled.append({**_digest(sender, rows), 'label': next(iter(verdicts))[0]})
    return sorted(weak, key=lambda s: (-s['n'], s['sender'])), labelled


def propose(digests: list[dict], labels: list[str], labelled: list[dict], log=print,
            limit: int = MAX_PROPOSE) -> tuple[list[tuple], bool]:
    """(proposal rows, reachable). Batches of gmail_llm.BATCH; stops at the first failed call — try tomorrow."""
    import gmail_llm_db
    rows: list[tuple] = []
    todo = digests[:limit]
    shots = gmail_llm.examples(labelled, set())
    for start in range(0, len(todo), gmail_llm.BATCH):
        batch = todo[start:start + gmail_llm.BATCH]
        try:
            proposals, response = gmail_llm.propose_batch(batch, labels, shots)
        except gmail_llm.ClaudeError as exc:
            log(f'claude failed ({exc}); {len(rows)} proposals this run')
            return rows, False
        items = {i.get('sender'): i for i in response['structured_output'].get('proposals', []) if isinstance(i, dict)}
        meta = {k: response.get(k) for k in ('session_id', 'total_cost_usd', 'duration_ms', 'usage', 'modelUsage')}
        for s, p in zip(batch, proposals):
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
    """Top up open proposal questions on "Dziś" to MAX_OPEN (biggest senders first)."""
    import gmail_llm_db
    open_refs = {r for r in reporter.open_refs() if r.startswith(REF)}
    asked = 0
    for p in gmail_llm_db.proposed():
        if len(open_refs) + asked >= MAX_OPEN:
            break
        if f'{REF}{p["id"]}' in open_refs or p.get('decision_id'):
            continue
        q, detail = question(p)
        d = reporter.ask(q, options=OPTIONS, ref=f'{REF}{p["id"]}', detail=detail, expires_hours=168)
        gmail_llm_db.set_decision(p['id'], d['id'])
        asked += 1
    log(f'asked {asked} new questions')
    return asked


def archive_ids(db: sqlite3.Connection, cfg: dict, inbox: set[str]) -> list[str]:
    """Inbox messages whose first matching rule says inbox='archive' — protected mail never."""
    db.row_factory = sqlite3.Row
    out = []
    for r in db.execute('SELECT * FROM messages'):
        if r['id'] not in inbox:
            continue
        rule = next((x for x in cfg['rules'] if x.hits(r['from_addr'] or '', r['subject'] or '')), None)
        if rule and rule.inbox == 'archive' and not gmail_classify.is_protected(rule.label, r['subject'], r['labels'], cfg):
            out.append(r['id'])
    return sorted(out)
