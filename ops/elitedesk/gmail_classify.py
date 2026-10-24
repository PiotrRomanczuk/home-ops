"""gmail_classify.py — assign exactly one category label to every inventoried message.

Pure functions over inventory rows + gmail_rules.json; no Gmail calls here.
Order of precedence (first hit wins):
  1. explicit rules (sender address/domain, optional subject regex)
  2. own mail (from: me) → classified by its recipients, else Ludzie/Wysłane
  3. people Piotr has written to, or free-mail senders without List-Unsubscribe → Ludzie
  4. Gmail signals: Social tab → Społecznościowe; Promotions tab → Promocje;
     List-Unsubscribe / Forums → Newslettery; Updates tab → Powiadomienia
  5. everything else → Inne/Do-przejrzenia
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

# Real rules hold personal addresses/domains → private file outside the (public) repo.
RULES_PATH = Path(os.environ.get('GMAIL_RULES', Path.home() / '.config' / 'home-ops' / 'gmail-rules.json'))
EXAMPLE_RULES = Path(__file__).resolve().parent / 'gmail_rules.example.json'
FALLBACK = 'Inne/Do-przejrzenia'
# Local parts that are never a human, even on gmail.com or when Piotr once replied to them.
AUTOMATED = re.compile(r'^(no-?reply|noreply|do-?not-?reply|donotreply|mailer-daemon|postmaster|'
                       r'notifications?|notify|alerts?|info|newsletters?|marketing|news|promo|hello|'
                       r'team|support|admin|e-?mail|mail|updates?|service|automat|system|bounces?|'
                       r'jobs?|careers?|messages?|account|accounts|security|billing|invoice)([+.\-_]|$)')


@dataclass(frozen=True)
class Rule:
    label: str
    senders: tuple[str, ...] = ()   # 'addr@x.pl', '@x.pl' (exact domain) or 'x.pl' (domain + subdomains)
    subject: re.Pattern | None = None

    def hits(self, addr: str, subject: str) -> bool:
        if self.senders and not any(_sender_match(addr, s) for s in self.senders):
            return False
        return self.subject.search(subject or '') is not None if self.subject else bool(self.senders)


def _sender_match(addr: str, pattern: str) -> bool:
    if '@' in pattern and not pattern.startswith('@'):
        return addr == pattern
    domain = addr.rpartition('@')[2]
    if pattern.startswith('@'):
        return domain == pattern[1:]
    return domain == pattern or domain.endswith('.' + pattern)


def load_rules(path: Path = RULES_PATH) -> dict:
    raw = json.loads(path.read_text())
    rules = [Rule(r['label'], tuple(s.lower() for s in r.get('from', [])),
                  re.compile(r['subject'], re.I) if r.get('subject') else None)
             for r in raw['rules']]
    return {'rules': rules, 'me': set(raw['me']), 'freemail': set(raw['freemail'])}


def correspondents(db: sqlite3.Connection, me: set[str]) -> set[str]:
    """Every address Piotr has sent mail to (people he actually talks to)."""
    out: set[str] = set()
    marks = ','.join('?' * len(me))
    for (to_addrs,) in db.execute(f'SELECT to_addrs FROM messages WHERE from_addr IN ({marks})', tuple(me)):
        out.update(a for a in (to_addrs or '').split(',') if a and a not in me)
    return out


def classify(row: dict, cfg: dict, people: set[str]) -> tuple[str, str]:
    """(label, reason) for one inventory row."""
    addr, subject, labels = row['from_addr'] or '', row['subject'] or '', row['labels'] or ''
    for rule in cfg['rules']:
        if rule.hits(addr, subject):
            return rule.label, 'rule'
    if addr in cfg['me']:
        others = [a for a in (row['to_addrs'] or '').split(',') if a and a not in cfg['me']]
        for rcpt in others:
            for rule in cfg['rules']:
                if rule.senders and rule.hits(rcpt, ''):
                    return rule.label, 'rule:recipient'
        return ('Ludzie/Wysłane', 'me') if others else ('Inne/Do-siebie', 'me')
    unsub = bool(row['has_unsub'])
    human = not unsub and not AUTOMATED.match(addr.partition('@')[0])
    if human and (addr in people or addr.rpartition('@')[2] in cfg['freemail']):
        return 'Ludzie', 'person'
    if 'CATEGORY_SOCIAL' in labels:
        return 'Społecznościowe', 'tab'
    if 'CATEGORY_PROMOTIONS' in labels:
        return 'Promocje', 'tab'
    if unsub or 'CATEGORY_FORUMS' in labels:
        return 'Newslettery', 'unsub'
    if 'CATEGORY_UPDATES' in labels:
        return 'Powiadomienia', 'tab'
    return FALLBACK, 'none'


def classify_all(db: sqlite3.Connection, cfg: dict) -> dict[str, list[str]]:
    """label -> message ids, covering every row in the inventory."""
    db.row_factory = sqlite3.Row
    people = correspondents(db, cfg['me'])
    out: dict[str, list[str]] = defaultdict(list)
    for row in db.execute('SELECT * FROM messages'):
        out[classify(row, cfg, people)[0]].append(row['id'])
    return dict(out)


def report(db: sqlite3.Connection, cfg: dict, top: int = 8) -> str:
    """Markdown coverage report: per label count, reasons, top senders."""
    db.row_factory = sqlite3.Row
    people = correspondents(db, cfg['me'])
    counts: Counter = Counter()
    reasons: dict[str, Counter] = defaultdict(Counter)
    senders: dict[str, Counter] = defaultdict(Counter)
    for row in db.execute('SELECT from_addr, subject, labels, to_addrs, has_unsub FROM messages'):
        label, why = classify(row, cfg, people)
        counts[label] += 1
        reasons[label][why] += 1
        senders[label][row['from_addr']] += 1
    total = sum(counts.values()) or 1
    lines = [f'# Kategoryzacja — {total} wiadomości', '',
             '| Kategoria | Maili | % | Skąd | Top nadawcy |', '|---|---:|---:|---|---|']
    for label, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        why = ', '.join(f'{k} {v}' for k, v in reasons[label].most_common())
        tops = ', '.join(f'{a} ({c})' for a, c in senders[label].most_common(top))
        lines.append(f'| {label} | {n} | {100 * n / total:.1f} | {why} | {tops} |')
    return '\n'.join(lines)
