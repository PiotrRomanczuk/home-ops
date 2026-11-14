#!/usr/bin/env python3
"""gmail_llm_eval.py — how well does Claude re-derive the existing rules?

Offline, on a sender-level export of gmail_test (no mailbox access):
  gold  — senders whose every message was labelled by one rule (the rule's label is the answer;
          the model never sees the rules)
  weak  — senders that only land in the Promotions/Updates tabs, List-Unsubscribe or nowhere
          (no answer; these are tomorrow's backlog, judged by a human)
Appends one JSON line per (model, sender) and the full CLI response per batch, so a run can resume.
Usage: gmail_llm_eval.py --dir ~/.local/state/home-ops/gmail/llm-eval --models sonnet opus
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gmail_llm  # noqa: E402

WEAK_REASONS = {'none', 'tab', 'unsub'}


def gold_label(s: dict) -> str | None:
    """The rules' answer for a sender, or None when the sender is not a clean single-rule case."""
    if s.get('reasons') != ['rule'] or s.get('n_categories') != 1 or (s.get('n_subcategories') or 0) > 1:
        return None
    return s.get('subcategory') or s['category']


def sample(senders: list[dict], per_label: int, weak: int, seed: int) -> list[tuple[str, dict, str | None]]:
    rnd = random.Random(seed)
    by_label: dict[str, list[dict]] = defaultdict(list)
    for s in senders:
        g = gold_label(s)
        if g:
            by_label[g].append(s)
    picked: list[tuple[str, dict, str | None]] = []
    for label in sorted(by_label):
        group = sorted(by_label[label], key=lambda s: s['sender'])
        picked += [('gold', s, label) for s in rnd.sample(group, min(per_label, len(group)))]
    weak_pool = sorted((s for s in senders if s.get('reasons') and set(s['reasons']) <= WEAK_REASONS),
                       key=lambda s: s['sender'])
    picked += [('weak', s, None) for s in rnd.sample(weak_pool, min(weak, len(weak_pool)))]
    return picked


def done_keys(out: Path) -> set[tuple[str, str]]:
    if not out.exists():
        return set()
    return {(r['model'], r['sender']) for r in gmail_llm.read_jsonl(out)}


def run(base: Path, models: list[str], per_label: int, weak: int, seed: int) -> Path:
    senders = gmail_llm.read_jsonl(base / 'senders-2026-11-13.jsonl')
    rule_labels = [r['label'] for r in gmail_llm.read_jsonl(base / 'rules-labels-2026-11-13.jsonl')]
    labels = gmail_llm.labels_from(rule_labels)
    picked = sample(senders, per_label, weak, seed)
    random.Random(seed).shuffle(picked)  # a batch must not be 20 senders of one category
    pool = [{**s, 'label': gold_label(s)} for s in senders if gold_label(s)]
    out = base / f'results-{gmail_llm.PROMPT_VERSION}.jsonl'
    batches = base / f'batches-{gmail_llm.PROMPT_VERSION}.jsonl'
    done = done_keys(out)
    print(f'{len(picked)} senders ({sum(p[0] == "gold" for p in picked)} gold) × {len(models)} models, '
          f'{len(labels)} labels, {len(done)} already done', flush=True)
    with out.open('a') as fh, batches.open('a') as bh:
        for model in models:
            todo = [p for p in picked if (model, p[1]['sender']) not in done]
            for start in range(0, len(todo), gmail_llm.BATCH):
                chunk = todo[start:start + gmail_llm.BATCH]
                # examples never come from a domain that is being classified in this batch
                shots = gmail_llm.examples(pool, {gmail_llm.domain(s['sender']) for _, s, _ in chunk})
                try:
                    proposals, response = gmail_llm.propose_batch([s for _, s, _ in chunk], labels, shots, model=model)
                except gmail_llm.ClaudeError as exc:
                    print(f'{model} batch {start}: {exc}', flush=True)
                    continue
                batch_id = f'{model}:{start}'
                bh.write(json.dumps({'batch': batch_id, 'senders': [s['sender'] for _, s, _ in chunk],
                                     'response': response}, ensure_ascii=False) + '\n')
                share = {'batch': batch_id, 'latency_s': round(response.get('duration_ms', 0) / 1000 / len(chunk), 2),
                         'cost_usd': round((response.get('total_cost_usd') or 0) / len(chunk), 5)}
                for (kind, s, gold), proposal in zip(chunk, proposals):
                    fh.write(json.dumps({'model': model, 'prompt_version': gmail_llm.PROMPT_VERSION, 'set': kind,
                                         'sender': s['sender'], 'gold': gold, 'proposal': proposal.to_json(),
                                         'response': share}, ensure_ascii=False) + '\n')
                fh.flush()
                bh.flush()
                print(f'{model}: {start + len(chunk)}/{len(todo)} · ${response.get("total_cost_usd") or 0:.3f}', flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--dir', type=Path, required=True)
    ap.add_argument('--models', nargs='+', default=[gmail_llm.MODEL])
    ap.add_argument('--per-label', type=int, default=15)
    ap.add_argument('--weak', type=int, default=150)
    ap.add_argument('--seed', type=int, default=13)
    args = ap.parse_args()
    out = run(args.dir.expanduser(), args.models, args.per_label, args.weak, args.seed)
    import gmail_llm_report
    (out.parent / f'summary-{gmail_llm.PROMPT_VERSION}.md').write_text(gmail_llm_report.summary(out))
    print(f'done → {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
