"""gmail_llm_guide.py — the strongest model writes the owner's category guide once.

Fable (GUIDE_MODEL) reads the categories with senders and subjects the rules already
file there and writes a compact guide: what belongs in each category, how to tell
neighbouring categories apart, the default inbox policy. Sonnet (the daily MODEL)
then gets the guide in its system prompt. The guide names no senders or domains, so
it generalises and leaks nothing about the evaluation sample. In production it lives
in gmail.config (key llm_guide) — never in this public repo.
"""
from __future__ import annotations

import subprocess
from collections import defaultdict

import gmail_llm

GUIDE_TIMEOUT = 1200
PER_LABEL, SUBJECTS = 15, 3
GUIDE_SYSTEM = """You write a classification guide that a smaller model will follow when it sorts the
senders of one person's Gmail (Polish owner; Polish and English mail) into HIS categories.
You get every category with senders the owner's rules already file there and their subjects.
Write the guide in English, as compact Markdown (aim for 1500-2500 words):
1. One section per category, in the given order: what belongs there (kinds of senders and mail,
   not names), the default inbox policy ("keep" = may need attention or a reply, "archive" =
   only worth filing), and the most likely confusion with a neighbouring category and how to
   decide. Categories without examples: infer from the name and the rest of the taxonomy.
2. A short "Hard cases" section with general tie-break rules (e.g. invoices vs order updates,
   job boards vs recruiters vs employers, people vs companies, newsletters vs service mail).
NEVER mention a sender address, domain, brand or person's name — describe kinds of senders only.
Return the guide in the "guide" field."""
GUIDE_SCHEMA = {'type': 'object', 'required': ['guide'], 'properties': {'guide': {'type': 'string'}}}


def guide_prompt(labels: list[str], labelled: list[dict]) -> str:
    """Categories in order, each with up to PER_LABEL rule-filed senders (biggest first) and a few subjects."""
    by_label: dict[str, list[dict]] = defaultdict(list)
    for s in sorted(labelled, key=lambda x: (-int(x.get('n') or 0), x['sender'])):
        by_label[s['label']].append(s)
    out = []
    for label in labels:
        out.append(f'## {label}')
        for s in by_label.get(label, [])[:PER_LABEL]:
            subjects = ' | '.join(list(dict.fromkeys(x for x in s.get('subjects') or [] if x))[:SUBJECTS])
            out.append(f"- {s['sender']} ({s.get('name') or ''}, {s.get('n')} msgs, tab {s.get('tab')}): {subjects[:220]}")
        if not by_label.get(label):
            out.append('- (no examples)')
    return '\n'.join(out)


def write_guide(labels: list[str], labelled: list[dict], model: str = gmail_llm.GUIDE_MODEL,
                runner=subprocess.run) -> tuple[str, dict]:
    """(guide text, full CLI response). Raises gmail_llm.ClaudeError on failure."""
    response = gmail_llm.claude(guide_prompt(labels, labelled), GUIDE_SCHEMA, model, runner,
                                system=GUIDE_SYSTEM, timeout=GUIDE_TIMEOUT)
    guide = str(response['structured_output'].get('guide') or '').strip()
    if not guide:
        raise gmail_llm.ClaudeError('empty guide')
    return guide, response


def leaks(guide: str, senders: list[dict]) -> list[str]:
    """Sender addresses or domains that slipped into the guide (should be none)."""
    text = guide.lower()
    found = {s['sender'] for s in senders if s['sender'].lower() in text}
    found |= {d for d in {gmail_llm.domain(s['sender']).lower() for s in senders} if len(d) > 5 and d in text}
    return sorted(found)


def ensure_guide(labels: list[str], labelled: list[dict], max_age_days: int = 30, log=print) -> str:
    """The stored guide; (re)written by GUIDE_MODEL when missing or older than max_age_days.

    A failed write keeps the old guide (or none) — proposals still run, just without it.
    """
    from datetime import datetime, timezone

    import gmail_llm_db
    guide, created = gmail_llm_db.load_guide()
    if guide and created and (datetime.now(timezone.utc) - created).days < max_age_days:
        return guide
    try:
        fresh, response = write_guide(labels, labelled)
    except gmail_llm.ClaudeError as exc:
        log(f'guide not refreshed ({exc}); using {"the old one" if guide else "none"}')
        return guide
    gmail_llm_db.save_guide(fresh, gmail_llm.GUIDE_MODEL)
    log(f'guide written by {gmail_llm.GUIDE_MODEL}: {len(fresh.split())} words, ${response.get("total_cost_usd") or 0:.2f}')
    return fresh
