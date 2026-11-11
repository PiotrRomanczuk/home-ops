"""Tests for process_writes — BPMN saves from the Mapa tab vs the vault copy.

Run:
    python3 -m unittest discover -s agents/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'elitedesk'))
import process_writes as pw  # noqa: E402

XML = ('<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="D">'
       '<bpmn:process id="P"/></bpmn:definitions>')
CURRENT = {'slug': 'pr-flow', 'bpmn_hash': 'a' * 64, 'bpmn_path': '2-Obszary/mapy/procesy/pr-flow.bpmn'}


def write(**over):
    return {'id': 7, 'slug': 'pr-flow', 'base_hash': 'a' * 64, 'bpmn_xml': XML, **over}


class CheckWriteTest(unittest.TestCase):
    def test_matching_hash_and_valid_bpmn_applies(self):
        self.assertEqual(pw.check_write(write(), CURRENT), ('apply', None))

    def test_changed_vault_copy_is_a_conflict(self):
        verdict, reason = pw.check_write(write(base_hash='b' * 64), CURRENT)
        self.assertEqual(verdict, 'conflict')
        self.assertIn('reload', reason)

    def test_unknown_process_and_bad_xml_fail(self):
        self.assertEqual(pw.check_write(write(), None)[0], 'failed')
        self.assertTrue(pw.check_write(write(bpmn_xml='<bpmn:definitions'), CURRENT)[1].startswith('not valid XML'))
        self.assertIn('not bpmn:definitions', pw.check_write(write(bpmn_xml='<html/>'), CURRENT)[1])
        self.assertEqual(pw.check_write(write(bpmn_xml=None), CURRENT), ('failed', 'bpmn_xml missing'))

    def test_invalid_xml_fails_before_the_hash_check(self):
        # A broken diagram is reported as broken even when the vault also moved on.
        self.assertEqual(pw.check_write(write(bpmn_xml='nope', base_hash='b' * 64), CURRENT)[0], 'failed')

    def test_commit_message_names_process_and_write(self):
        self.assertEqual(pw.commit_message(write()), 'procesy: pr-flow edytowany w Mapie (home-ops, zapis #7)')


if __name__ == '__main__':
    unittest.main()
