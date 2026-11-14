"""gmail_llm_eval / gmail_llm_report / gmail_review: sampling, scoring, terminal review."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gmail_llm_eval as ev  # noqa: E402
import gmail_llm_report as rep  # noqa: E402
import gmail_review  # noqa: E402


def sender(addr, category, reasons=('rule',), n_cat=1, sub=None, n_sub=0):
    return {'sender': addr, 'category': category, 'reasons': list(reasons), 'n_categories': n_cat,
            'subcategory': sub, 'n_subcategories': n_sub}


class SampleTest(unittest.TestCase):
    def test_gold_is_single_rule_senders_with_subcategory_preferred(self):
        self.assertEqual(ev.gold_label(sender('a@x', 'Zakupy', sub='Zakupy/Sklepy', n_sub=1)), 'Zakupy/Sklepy')
        self.assertIsNone(ev.gold_label(sender('a@x', 'Zakupy', reasons=('rule', 'tab'))))
        self.assertIsNone(ev.gold_label(sender('a@x', 'Zakupy', n_cat=2)))

    def test_sample_caps_per_label_and_adds_weak(self):
        rows = [sender(f'z{i}@x', 'Zakupy') for i in range(20)] + [sender('u@x', 'Urzędy')]
        rows += [sender(f'w{i}@x', 'Promocje', reasons=('tab',)) for i in range(5)]
        picked = ev.sample(rows, per_label=15, weak=3, seed=1)
        self.assertEqual(Counter(g for k, _, g in picked if k == 'gold'), Counter({'Zakupy': 15, 'Urzędy': 1}))
        self.assertEqual(sum(k == 'weak' for k, _, _ in picked), 3)
        self.assertEqual(picked, ev.sample(rows, per_label=15, weak=3, seed=1))  # reproducible


class ReportTest(unittest.TestCase):
    def test_exact_branch_and_top_level_agreement(self):
        def r(gold, label, conf=0.9, kind='gold'):
            return {'model': 'm', 'set': kind, 'sender': 'x', 'gold': gold, 'response': {'latency_s': 2.0},
                    'proposal': {'label': label, 'inbox': 'keep', 'confidence': conf, 'valid': True}}
        rows = [r('Zakupy', 'Zakupy'), r('Zakupy', 'Zakupy/Sklepy'), r('Dom/Zdrowie', 'Dom'),
                r('Urzędy', 'Prawne', conf=0.5), r(None, 'Promocje', kind='weak')]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'results.jsonl'
            path.write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in rows) + '\n')
            text = rep.summary(path)
        self.assertIn('exact 1/4 (25%)', text)
        self.assertIn('same branch 3/4 (75%)', text)
        self.assertIn('Urzędy → Prawne: 1', text)
        self.assertIn('Weak senders (1): Promocje 1', text)


class FakeStore:
    def __init__(self, proposals):
        self._p, self.accepted, self.rejected = proposals, [], []

    def proposed(self):
        return self._p

    def accept(self, *args):
        self.accepted.append(args)

    def reject(self, *args):
        self.rejected.append(args)


class ReviewTest(unittest.TestCase):
    def test_accept_change_toggle_reject_and_quit(self):
        props = [{'id': i, 'sender': f's{i}@x.pl', 'sender_key': f'@x{i}.pl', 'label': 'Zakupy', 'inbox': 'archive',
                  'model': 'm', 'confidence': 0.8, 'reason': '', 'sample': {'n': 2, 'subjects': ['a']}} for i in (1, 2, 3, 4)]
        store, out = FakeStore(props), []
        feed = iter(['t', 'z', '2', 'a', 't', 'n', 'q'])
        done = gmail_review.review(store, ['Urzędy', 'Zakupy/Sklepy'], ask=lambda _p: next(feed), out=out.append)
        self.assertEqual(store.accepted, [(1, 'Zakupy', 'archive', 'terminal'), (2, 'Zakupy/Sklepy', 'keep', 'terminal')])
        self.assertEqual(store.rejected, [(3, 'terminal')])
        self.assertEqual(done, Counter({'accepted': 2, 'rejected': 1}))
        self.assertTrue(any('[4/4]' in line for line in out))


if __name__ == '__main__':
    unittest.main()
