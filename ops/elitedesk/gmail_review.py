#!/usr/bin/env python3
"""gmail_review.py — review the model's rule proposals in the terminal, one sender at a time.

    ssh -t uwh 'cd ~/code/logs-stack && python3 ops/elitedesk/gmail_review.py'

t accept · z change category · a toggle keep/archive · n reject (sender never asked again)
p skip · q quit. Every answer is written at once: accept = a new gmail.rule row, which the
next gmail-daily run applies (labels, and archiving when the rule says so).
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

KEYS = '[t] zatwierdź  [z] zmień kategorię  [a] zostaw/archiwizuj  [n] odrzuć  [p] pomiń  [q] koniec'


def _where(inbox: str) -> str:
    return 'do archiwum' if inbox == 'archive' else 'zostaje w skrzynce'


def show(p: dict, idx: int, total: int, out) -> None:
    s = p.get('sample') or {}
    unsub = round(100 * float(s.get('unsub_share') or 0))
    out(f"\n[{idx}/{total}] {p['sender']}  ({s.get('n', '?')} maili, zakładka {s.get('tab', '?')}, "
        f"z linkiem wypisu {unsub}%)")
    for subject in [x for x in s.get('subjects', []) if x][:3]:
        out(f'   · {subject[:110]}')
    out(f"  Propozycja: {p['label']}, {_where(p['inbox'])}, reguła na {p['sender_key']}  "
        f"[{p['model']} {float(p['confidence']):.2f}]")
    if p.get('reason'):
        out(f"  Powód: {p['reason']}")


def pick_label(labels: list[str], ask, out) -> str | None:
    for n, label in enumerate(labels, 1):
        out(f'   {n:2}. {label}')
    picked = ask('  Numer kategorii (enter = anuluj): ').strip()
    return labels[int(picked) - 1] if picked.isdigit() and 1 <= int(picked) <= len(labels) else None


def review(store, labels: list[str], ask=input, out=print) -> Counter:
    """store: gmail_llm_db (proposed/accept/reject) or a test double with the same functions."""
    queue = store.proposed()
    done: Counter = Counter()
    if not queue:
        out('Brak propozycji do przejrzenia.')
    key = ''
    for idx, p in enumerate(queue, 1):
        label, inbox = p['label'], p['inbox']
        show(p, idx, len(queue), out)
        while True:
            key = ask(f'  {KEYS}\n  > ').strip().lower()[:1]
            if key == 't':
                store.accept(p['id'], label, inbox, 'terminal')
                done['accepted'] += 1
            elif key == 'n':
                store.reject(p['id'], 'terminal')
                done['rejected'] += 1
            elif key == 'z':
                label = pick_label(labels, ask, out) or label
                out(f'  → {label}, {_where(inbox)} (zatwierdź: t)')
                continue
            elif key == 'a':
                inbox = 'keep' if inbox == 'archive' else 'archive'
                out(f'  → {label}, {_where(inbox)} (zatwierdź: t)')
                continue
            elif key not in ('p', 'q'):
                continue
            break
        if key == 'q':
            break
    return done


def main() -> int:
    import os
    os.environ.setdefault('GMAIL_RULES', 'db')
    import gmail_classify
    import gmail_llm_daily
    import gmail_llm_db
    cfg = gmail_classify.load_rules(Path(os.environ['GMAIL_RULES']))
    done = review(gmail_llm_db, gmail_llm_daily.model_labels(cfg))
    print('Załatwione: ' + (', '.join(f'{k} {v}' for k, v in done.items()) or 'nic'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
