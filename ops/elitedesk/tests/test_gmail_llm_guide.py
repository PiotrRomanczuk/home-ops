"""gmail_llm_guide: the guide prompt, leak check, refresh policy; the guide in Sonnet's system prompt."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gmail_llm  # noqa: E402
import gmail_llm_guide as guide  # noqa: E402

LABELS = ['Finanse/Faktury', 'Zakupy', 'Uczniowie']
LABELLED = [{'sender': f'f{i}@faktury{i}.pl', 'label': 'Finanse/Faktury', 'n': i, 'tab': 'updates',
             'subjects': ['Faktura VAT', 'Faktura VAT', 'Przypomnienie']} for i in range(20)]
LABELLED += [{'sender': 'sklep@shop.pl', 'label': 'Zakupy', 'n': 3, 'tab': 'promotions', 'subjects': ['Zamówienie']}]


def cli(payload):
    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), '')
    return run


class GuidePromptTest(unittest.TestCase):
    def test_every_category_listed_in_order_capped_and_deduped(self):
        text = guide.guide_prompt(LABELS, LABELLED)
        self.assertLess(text.index('## Finanse/Faktury'), text.index('## Zakupy'))
        self.assertEqual(text.count('@faktury'), guide.PER_LABEL)
        self.assertIn('f19@faktury19.pl', text)  # biggest senders first
        self.assertIn('Faktura VAT | Przypomnienie', text)
        self.assertIn('## Uczniowie\n- (no examples)', text)

    def test_leaks_finds_addresses_and_domains(self):
        found = guide.leaks('Invoices from faktury3.pl or f1@faktury1.pl go to Finanse.', LABELLED)
        self.assertEqual(found, ['f1@faktury1.pl', 'faktury1.pl', 'faktury3.pl'])
        self.assertEqual(guide.leaks('Shops and marketplaces go to Zakupy.', LABELLED), [])

    def test_write_guide_uses_the_guide_model_and_schema(self):
        seen = []

        def run(cmd, **kw):
            seen.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, json.dumps({'structured_output': {'guide': '## Zakupy\nShops.'}}), '')
        text, _ = guide.write_guide(LABELS, LABELLED, model='fable', runner=run)
        self.assertEqual(text, '## Zakupy\nShops.')
        self.assertEqual(seen[0][seen[0].index('--model') + 1], 'fable')
        self.assertIn('NEVER mention a sender', seen[0][seen[0].index('--system-prompt') + 1])
        with self.assertRaises(gmail_llm.ClaudeError):
            guide.write_guide(LABELS, LABELLED, runner=cli({'structured_output': {'guide': ' '}}))


class GuideInPromptTest(unittest.TestCase):
    def test_sonnet_gets_the_guide_in_its_system_prompt(self):
        self.assertEqual(gmail_llm.system_prompt(''), gmail_llm.SYSTEM)
        seen = []

        def run(cmd, **kw):
            seen.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, json.dumps({'structured_output': {'proposals': []}}), '')
        gmail_llm.propose_batch([{'sender': 'a@b.pl'}], LABELS, {}, runner=run, guide='## Zakupy\nShops.')
        system = seen[0][seen[0].index('--system-prompt') + 1]
        self.assertTrue(system.startswith(gmail_llm.SYSTEM) and system.endswith('## Zakupy\nShops.'))
        self.assertEqual(seen[0][seen[0].index('--model') + 1], gmail_llm.MODEL)


class EnsureGuideTest(unittest.TestCase):
    def ensure(self, stored, write=None):
        writer = mock.patch.object(guide, 'write_guide', side_effect=write or [('fresh guide', {'total_cost_usd': 0.4})])
        with mock.patch('gmail_llm_db.load_guide', return_value=stored), writer as w, \
             mock.patch('gmail_llm_db.save_guide') as save:
            return guide.ensure_guide(LABELS, LABELLED, log=lambda *_: None), w, save

    def test_recent_guide_is_reused(self):
        text, w, save = self.ensure(('old guide', datetime.now(timezone.utc) - timedelta(days=3)))
        self.assertEqual(text, 'old guide')
        w.assert_not_called()
        save.assert_not_called()

    def test_missing_or_stale_guide_is_rewritten_and_stored(self):
        for stored in (('', None), ('old guide', datetime.now(timezone.utc) - timedelta(days=40))):
            text, w, save = self.ensure(stored)
            self.assertEqual(text, 'fresh guide')
            save.assert_called_once_with('fresh guide', gmail_llm.GUIDE_MODEL)

    def test_failed_rewrite_keeps_the_old_guide(self):
        stale = ('old guide', datetime.now(timezone.utc) - timedelta(days=40))
        text, _, save = self.ensure(stale, write=gmail_llm.ClaudeError('limit'))
        self.assertEqual(text, 'old guide')
        save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
