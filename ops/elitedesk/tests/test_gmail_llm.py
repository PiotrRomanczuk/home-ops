"""gmail_llm: examples, prompt, schema, validation of Claude's answer, the headless call (mocked)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gmail_llm  # noqa: E402
import gmail_llm_report  # noqa: E402

LABELS = gmail_llm.labels_from(['Zakupy', 'Zakupy/Sklepy', 'Urzędy', 'Finanse/Faktury'])
SENDER = {'sender': 'sklep@allegro.pl', 'name': 'Allegro', 'n': 12, 'unsub_share': 0.5, 'tab': 'updates',
          'subjects': ['Twoje zamówienie', 'Twoje zamówienie', '', 'Paczka w drodze']}


def item(**kw) -> dict:
    return {'sender': 'sklep@allegro.pl', 'label': 'Zakupy', 'inbox': 'archive', 'scope': 'domain',
            'confidence': 0.9, 'reason': 'sklep', **kw}


def fake_cli(payload: dict, code: int = 0, seen: list | None = None):
    def run(cmd, **kw):
        if seen is not None:
            seen.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, code, json.dumps(payload), '')
    return run


class ParseTest(unittest.TestCase):
    def test_valid_domain_rule(self):
        p = gmail_llm.parse(item(), 'sklep@allegro.pl', LABELS)
        self.assertEqual((p.label, p.inbox, p.sender_key, p.valid), ('Zakupy', 'archive', '@allegro.pl', True))

    def test_label_outside_the_enum_goes_to_review(self):
        p = gmail_llm.parse(item(label='Nowa/Kategoria'), 'sklep@allegro.pl', LABELS)
        self.assertEqual((p.label, p.valid, p.confidence), (gmail_llm.REVIEW, False, 0.0))

    def test_missing_or_broken_items_go_to_review(self):
        self.assertFalse(gmail_llm.parse(None, 'a@b.pl', LABELS).valid)
        self.assertFalse(gmail_llm.parse(item(inbox='trash'), 'a@b.pl', LABELS).valid)

    def test_freemail_never_gets_a_domain_rule(self):
        p = gmail_llm.parse(item(), 'jan.kowalski@gmail.com', LABELS)
        self.assertEqual((p.scope, p.sender_key), ('address', 'jan.kowalski@gmail.com'))

    def test_confidence_is_clamped(self):
        self.assertEqual(gmail_llm.parse(item(confidence=4), 'a@b.pl', LABELS).confidence, 1.0)


class PromptTest(unittest.TestCase):
    def test_examples_skip_excluded_domains_and_cap_per_label(self):
        labelled = [{'sender': f'a{i}@shop{i}.pl', 'label': 'Zakupy', 'n': i, 'subjects': ['', f'Zamówienie {i}']}
                    for i in range(6)] + [{'sender': 'x@urzad.gov.pl', 'label': 'Urzędy', 'n': 1, 'subjects': []}]
        shots = gmail_llm.examples(labelled, {'shop5.pl'}, per_label=2)
        self.assertEqual(shots['Zakupy'], ['a4@shop4.pl — Zamówienie 4', 'a3@shop3.pl — Zamówienie 3'])
        self.assertEqual(shots['Urzędy'], ['x@urzad.gov.pl — '])

    def test_render_lists_categories_with_examples_and_dedupes_subjects(self):
        text = gmail_llm.render([SENDER], LABELS, {'Zakupy': ['a@shop.pl — Zamówienie']})
        self.assertIn('- Zakupy: e.g. a@shop.pl — Zamówienie', text)
        self.assertIn('- Urzędy\n', text)
        self.assertEqual(text.count('Twoje zamówienie'), 1)

    def test_schema_pins_senders_and_labels(self):
        s = gmail_llm.schema(LABELS, ['a@b.pl'])['properties']['proposals']['items']['properties']
        self.assertEqual((s['sender']['enum'], s['label']['enum']), (['a@b.pl'], LABELS))
        self.assertIn(gmail_llm.REVIEW, LABELS)


class ClaudeCallTest(unittest.TestCase):
    def test_batch_runs_trimmed_headless_claude(self):
        seen: list = []
        out = {'structured_output': {'proposals': [item()]}, 'total_cost_usd': 0.01, 'is_error': False}
        other = dict(SENDER, sender='ktos@firma.pl')
        proposals, response = gmail_llm.propose_batch([SENDER, other], LABELS, {}, model='sonnet',
                                                      runner=fake_cli(out, seen=seen))
        cmd = seen[0][0]
        for flag in ('--strict-mcp-config', '--no-session-persistence', '--json-schema', '--system-prompt'):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index('--tools') + 1], '')
        self.assertEqual(cmd[cmd.index('--setting-sources') + 1], '')
        self.assertIn('sklep@allegro.pl', seen[0][1]['input'])
        self.assertEqual([p.label for p in proposals], ['Zakupy', gmail_llm.REVIEW])  # missing answer → review
        self.assertEqual(response['total_cost_usd'], 0.01)

    def test_failures_raise_claude_error(self):
        for runner in (fake_cli({'is_error': True, 'subtype': 'error_max_turns'}),
                       lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, 'not json', 'boom')):
            with self.assertRaises(gmail_llm.ClaudeError):
                gmail_llm.claude('x', {}, runner=runner)

        def missing(cmd, **kw):
            raise FileNotFoundError('claude')
        with self.assertRaises(gmail_llm.ClaudeError):
            gmail_llm.claude('x', {}, runner=missing)

    def test_read_jsonl_survives_unicode_line_separators(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'x.jsonl'
            path.write_text(json.dumps({'s': 'a b'}, ensure_ascii=False) + '\n\n' + json.dumps({'s': 'c'}) + '\n')
            self.assertEqual([r['s'] for r in gmail_llm_report.read_jsonl(path)], ['a b', 'c'])


if __name__ == '__main__':
    unittest.main()
