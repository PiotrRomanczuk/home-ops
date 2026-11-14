"""gmail_llm.py — Claude proposes *rules* (sender → category + keep|archive); a human accepts them.

Headers only, batches of senders, categories as a JSON Schema enum with example senders and the
owner's guide (gmail_llm_guide.py). Headless `claude -p` on the Max subscription, trimmed to ~1k
tokens of overhead (no tools, MCP, user settings). ADR: docs/adr/2026-11-13-gmail-llm-rule-proposals.md
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

CLAUDE_BIN = os.environ.get('CLAUDE_BIN', 'claude')
MODEL = os.environ.get('GMAIL_LLM_MODEL', 'sonnet')  # daily proposals; Piotr 2026-11-14: opus ≈ sonnet, sonnet cheaper
GUIDE_MODEL = os.environ.get('GMAIL_LLM_GUIDE_MODEL', 'fable')  # writes the category guide once (gmail_llm_guide.py)
TIMEOUT = int(os.environ.get('GMAIL_LLM_TIMEOUT', '300'))
PROMPT_VERSION = 'v3-guide'
BATCH, MAX_SUBJECTS, PER_LABEL_EXAMPLES = 20, 6, 4
BUILTIN = ('Ludzie', 'Promocje', 'Newslettery', 'Powiadomienia', 'Społecznościowe', 'Inne/Do-przejrzenia')
REVIEW = 'Inne/Do-przejrzenia'
FREEMAIL = {'gmail.com', 'googlemail.com', 'wp.pl', 'o2.pl', 'onet.pl', 'onet.eu', 'interia.pl', 'op.pl',
            'gazeta.pl', 'outlook.com', 'hotmail.com', 'live.com', 'yahoo.com', 'icloud.com', 'me.com', 'tlen.pl'}

SYSTEM = """You sort the senders of one person's Gmail (Polish owner, Polish and English mail) into
his own categories. For EVERY sender in the list return one proposal:
- "label": the category that fits ALL mail from this sender, from the listed categories only.
  Follow the owner's taxonomy as shown by the example senders of each category. Prefer the most
  specific fitting category ("Parent/Child" over "Parent"). "Inne/Do-przejrzenia" when unsure.
- "inbox": "keep" if mail from this sender may need the owner's attention or reply (people,
  clients, students, offices and courts, debt collectors, banks asking for action, security
  alerts, account problems); "archive" if it is only worth filing (newsletters, promotions,
  routine notifications, receipts, invoices, shipping updates).
- "scope": "domain" if the whole domain sends one kind of mail, else "address".
- "confidence": 0 to 1, honest — lower it when the headers are ambiguous. "reason": one short Polish sentence."""


class ClaudeError(RuntimeError):
    pass


@dataclass
class Proposal:
    sender: str
    label: str
    inbox: str
    scope: str
    confidence: float
    reason: str
    valid: bool = True

    @property
    def sender_key(self) -> str:
        """What goes into gmail.rule.senders: the address, or '@domain' for an exact-domain rule."""
        return '@' + self.sender.rpartition('@')[2] if self.scope == 'domain' else self.sender

    def to_json(self) -> dict:
        return {**asdict(self), 'sender_key': self.sender_key}


def labels_from(rule_labels: list[str]) -> list[str]:
    """The enum the model chooses from: every rule/subrule label plus the built-in buckets."""
    return sorted(set(rule_labels) | set(BUILTIN))


def domain(sender: str) -> str:
    return sender.rpartition('@')[2]


def examples(labelled: list[dict], exclude_domains: set[str], per_label: int = PER_LABEL_EXAMPLES) -> dict[str, list[str]]:
    """label → a few 'sender — subject' lines from senders the rules already file (never from excluded domains)."""
    out: dict[str, list[str]] = {}
    for s in sorted(labelled, key=lambda x: (-int(x.get('n') or 0), x['sender'])):
        lines = out.setdefault(s['label'], [])
        if len(lines) < per_label and domain(s['sender']) not in exclude_domains:
            subject = next((x for x in s.get('subjects') or [] if x), '')
            lines.append(f"{s['sender']} — {subject[:80]}")
    return out


def render(batch: list[dict], labels: list[str], shots: dict[str, list[str]]) -> str:
    cats = [f"- {label}" + (': e.g. ' + '; '.join(shots[label]) if shots.get(label) else '') for label in labels]
    senders = []
    for s in batch:
        subjects = list(dict.fromkeys(x for x in s.get('subjects') or [] if x))[:MAX_SUBJECTS]
        senders.append({'sender': s['sender'], 'name': s.get('name') or '', 'messages': s.get('n'),
                        'unsubscribe_share': s.get('unsub_share'), 'gmail_tab': s.get('tab'),
                        'subjects': [x[:140] for x in subjects]})
    return ('Categories (with example senders already filed there):\n' + '\n'.join(cats)
            + '\n\nSenders to classify (JSON):\n' + json.dumps(senders, ensure_ascii=False, indent=1))


def schema(labels: list[str], senders: list[str]) -> dict:
    item = {'type': 'object', 'required': ['sender', 'label', 'inbox', 'scope', 'confidence', 'reason'],
            'properties': {'sender': {'type': 'string', 'enum': senders},
                           'label': {'type': 'string', 'enum': labels},
                           'inbox': {'type': 'string', 'enum': ['keep', 'archive']},
                           'scope': {'type': 'string', 'enum': ['address', 'domain']},
                           'confidence': {'type': 'number'}, 'reason': {'type': 'string'}}}
    return {'type': 'object', 'required': ['proposals'], 'properties': {'proposals': {'type': 'array', 'items': item}}}


def parse(raw: dict | None, sender: str, labels: list[str]) -> Proposal:
    """Validate one item of the answer; anything off-schema becomes a low-confidence review proposal."""
    try:
        label, inbox, scope = raw['label'], raw['inbox'], raw['scope']  # type: ignore[index]
        conf = min(max(float(raw.get('confidence', 0)), 0.0), 1.0)  # type: ignore[union-attr]
    except (KeyError, TypeError, ValueError):
        return Proposal(sender, REVIEW, 'keep', 'address', 0.0, 'brak odpowiedzi dla nadawcy', valid=False)
    if label not in labels or inbox not in ('keep', 'archive') or scope not in ('address', 'domain'):
        return Proposal(sender, REVIEW, 'keep', 'address', 0.0, f'spoza schematu: {label!r}', valid=False)
    if scope == 'domain' and domain(sender) in FREEMAIL:
        scope = 'address'  # never a rule for all of gmail.com
    return Proposal(sender, label, inbox, scope, conf, str(raw.get('reason', ''))[:300])  # type: ignore[union-attr]


def system_prompt(guide: str = '') -> str:
    """SYSTEM, plus the owner's category guide (written by GUIDE_MODEL) when there is one."""
    return SYSTEM + (f"\n\nThe owner's category guide — follow it:\n{guide}" if guide else '')


def claude(prompt: str, fmt: dict, model: str = MODEL, runner=subprocess.run, system: str = SYSTEM,
           timeout: int = TIMEOUT) -> dict:
    """One headless call; returns the CLI's JSON (structured_output, usage, total_cost_usd …)."""
    cmd = [CLAUDE_BIN, '-p', '--output-format', 'json', '--model', model, '--tools', '', '--strict-mcp-config',
           '--setting-sources', '', '--no-session-persistence', '--system-prompt', system,
           '--json-schema', json.dumps(fmt, ensure_ascii=False)]
    try:
        r = runner(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ClaudeError(str(exc)) from exc
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError as exc:
        raise ClaudeError(f'exit {r.returncode}: {(r.stderr or r.stdout)[:300]}') from exc
    if out.get('is_error') or not isinstance(out.get('structured_output'), dict):
        raise ClaudeError(f"claude: {out.get('subtype')} {str(out.get('result'))[:300]}")
    return out


def propose_batch(batch: list[dict], labels: list[str], shots: dict[str, list[str]], model: str = MODEL,
                  runner=subprocess.run, guide: str = '') -> tuple[list[Proposal], dict]:
    """Up to BATCH senders → one Proposal each (missing answers become review) + the full CLI response."""
    senders = [s['sender'] for s in batch]
    response = claude(render(batch, labels, shots), schema(labels, senders), model, runner, system_prompt(guide))
    by_sender = {i.get('sender'): i for i in response['structured_output'].get('proposals', []) if isinstance(i, dict)}
    return [parse(by_sender.get(s), s, labels) for s in senders], response
