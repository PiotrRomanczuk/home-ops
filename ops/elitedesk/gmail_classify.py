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
from collections import defaultdict
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
                       r'jobs?|careers?|messages?|account|accounts|security|billing|invoice|sklep|shop|store|orders?|'
                       r'zam[oó]wienia|rejestracja|registration|customerservice|customerhelp|webmaster|post|bok|'
                       r'contact|kontakt|replies?\d*|digest|calendar-notification)([+.\-_]|$)')


@dataclass(frozen=True)
class Rule:
    label: str
    senders: tuple[str, ...] = ()   # 'addr@x.pl', '@x.pl' (exact domain) or 'x.pl' (domain + subdomains)
    subject: re.Pattern | None = None
    automated_only: bool = False    # subject rule applies only to bot-like local parts (never to a person)

    def hits(self, addr: str, subject: str) -> bool:
        if self.senders and not any(_sender_match(addr, s) for s in self.senders):
            return False
        if self.automated_only and not (addr == '' or AUTOMATED.match(addr.partition('@')[0])):
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
    """Rules from the JSON file, or from Postgres (gmail.rules_json) when GMAIL_RULES=db."""
    if str(path) == 'db':
        import gmail_db
        return rules_from_dict(gmail_db.load_rules())
    return rules_from_dict(json.loads(path.read_text()))


def rules_from_dict(raw: dict) -> dict:
    """Compile the rules JSON shape (file or gmail.rules_json()) into regex-backed Rule objects."""
    rules = [Rule(r['label'], tuple(s.lower() for s in r.get('from', [])),
                  re.compile(r['subject'], re.I) if r.get('subject') else None,
                  bool(r.get('automated_only')))
             for r in raw['rules']]
    protect = raw.get('protect', {})
    subrules = [(r['parent'], Rule(r['label'], tuple(x.lower() for x in r.get('from', [])),
                                   re.compile(r['subject'], re.I) if r.get('subject') else None))
                for r in raw.get('subrules', [])]
    return {'rules': rules, 'subrules': subrules, 'me': set(raw['me']), 'freemail': set(raw['freemail']),
            'protect_labels': tuple(protect.get('labels', ())),
            'protect_subject': re.compile(protect['subject'], re.I) if protect.get('subject') else None}


def is_protected(label: str, subject: str, labels: str, cfg: dict) -> bool:
    """True when a message must never be trashed (starred, protected category, or document-like subject)."""
    if 'STARRED' in (labels or ''):
        return True
    if any(label == p or label.startswith(p + '/') for p in cfg.get('protect_labels', ())):
        return True
    rx = cfg.get('protect_subject')
    return bool(rx and rx.search(subject or ''))


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


def subcategory(label: str, row, cfg: dict) -> str | None:
    """Optional child label refining `label` (first matching subrule of that parent)."""
    addr, subject = row['from_addr'] or '', row['subject'] or ''
    for parent, rule in cfg.get('subrules', ()):
        if parent == label and rule.hits(addr, subject):
            return rule.label
    if label == 'Ludzie' and cfg.get('subrules'):
        return 'Ludzie/Znajomi' if addr.rpartition('@')[2] in cfg['freemail'] else 'Ludzie/Firmy'
    return None


def classify_all(db: sqlite3.Connection, cfg: dict, *, with_sub: bool = False) -> dict[str, list[str]]:
    """label -> message ids, covering every row. with_sub also maps child labels (a message then has parent + child)."""
    db.row_factory = sqlite3.Row
    people = correspondents(db, cfg['me'])
    out: dict[str, list[str]] = defaultdict(list)
    for row in db.execute('SELECT * FROM messages'):
        label = classify(row, cfg, people)[0]
        out[label].append(row['id'])
        child = subcategory(label, row, cfg) if with_sub else None
        if child:
            out[child].append(row['id'])
    return dict(out)
