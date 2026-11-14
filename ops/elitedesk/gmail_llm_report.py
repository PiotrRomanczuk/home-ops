"""gmail_llm_report.py — turn gmail_llm_eval results (JSONL) into a markdown summary.

Three levels of agreement with the rules: exact label, same branch (the model picked
the label's parent or child), same top-level category. Plus confidence calibration,
latency, inbox policy and what the model does with the weak (no-rule) senders.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path


def same_branch(pred: str, gold: str) -> bool:
    return pred == gold or pred.startswith(gold + '/') or gold.startswith(pred + '/')


def top(label: str) -> str:
    return label.split('/', 1)[0]


def _pct(hits: int, total: int) -> str:
    return f'{hits}/{total} ({hits / total:.0%})' if total else '—'


def model_section(model: str, rows: list[dict]) -> list[str]:
    gold = [r for r in rows if r['set'] == 'gold']
    weak = [r for r in rows if r['set'] == 'weak']
    pred = {id(r): r['proposal']['label'] for r in rows}
    exact = sum(pred[id(r)] == r['gold'] for r in gold)
    branch = sum(same_branch(pred[id(r)], r['gold']) for r in gold)
    toplvl = sum(top(pred[id(r)]) == top(r['gold']) for r in gold)
    sure = [r for r in gold if r['proposal']['confidence'] >= 0.85]
    lat = sorted(r['response'].get('latency_s', 0) for r in rows)
    out = [f'## {model}', '',
           f'- gold: {len(gold)} senders · **exact {_pct(exact, len(gold))}** · same branch {_pct(branch, len(gold))}'
           f' · same top level {_pct(toplvl, len(gold))}',
           f'- confidence ≥ 0.85: {len(sure)} senders, same branch {_pct(sum(same_branch(pred[id(r)], r["gold"]) for r in sure), len(sure))}',
           f'- invalid answers: {sum(not r["proposal"]["valid"] for r in rows)}',
           f'- latency per sender: median {lat[len(lat) // 2] if lat else 0:.1f} s, p90 {lat[int(len(lat) * 0.9)] if lat else 0:.1f} s',
           f'- inbox policy (all): {dict(Counter(r["proposal"]["inbox"] for r in rows))}', '',
           '| rule label | n | exact | same branch | most common answer |', '|---|---:|---:|---:|---|']
    by_gold: dict[str, list[dict]] = defaultdict(list)
    for r in gold:
        by_gold[r['gold']].append(r)
    for label, group in sorted(by_gold.items()):
        answers = Counter(pred[id(r)] for r in group).most_common(1)[0][0]
        out.append(f'| {label} | {len(group)} | {sum(pred[id(r)] == label for r in group)} '
                   f'| {sum(same_branch(pred[id(r)], label) for r in group)} | {answers} |')
    confusion = Counter((r['gold'], pred[id(r)]) for r in gold if not same_branch(pred[id(r)], r['gold']))
    out += ['', 'Most common misses (rule → model):', '']
    out += [f'- {g} → {p}: {n}' for (g, p), n in confusion.most_common(12)]
    out += ['', f'Weak senders ({len(weak)}): ' + ', '.join(f'{label} {n}' for label, n in
                                                          Counter(pred[id(r)] for r in weak).most_common(15)), '']
    return out


def summary(results: Path) -> str:
    import gmail_llm
    rows = gmail_llm.read_jsonl(results)
    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_model[r['model']].append(r)
    lines = [f'# Gmail LLM evaluation — {results.name}', '']
    for model in sorted(by_model):
        lines += model_section(model, by_model[model])
    return '\n'.join(lines) + '\n'
