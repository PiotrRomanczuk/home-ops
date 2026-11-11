"""Tests for vault_processes — BPMN process notes behind the "Mapa" tab.

Run:
    python3 -m unittest discover -s agents/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'elitedesk'))
import vault_processes as vpr  # noqa: E402

BPMN = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="D">
  <bpmn:process id="P"><bpmn:laneSet id="LS">
    <bpmn:lane id="Lane_a" name="job-radar"/>
    <bpmn:lane id="Lane_b" name="vectordigital"/>
  </bpmn:laneSet></bpmn:process>
</bpmn:definitions>
"""

NOTE = """---
type: process
process: lead-pipeline
trigger: cron
schedule: "job-radar ops/run.sh"
projects: ["[[job-radar]]", "[[vectordigital]]"]
bpmn: lead-pipeline.bpmn
summary: "Leady"
---

# Leady VD i oferty
"""


class ProcessNotesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dir = self.root / '2-Obszary' / 'mapy' / 'procesy'
        self.dir.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name: str, text: str) -> Path:
        p = self.dir / name
        p.write_text(text, encoding='utf-8')
        return p

    def test_full_record(self):
        self.write('lead-pipeline.bpmn', BPMN)
        rec = vpr.parse_process_file(self.write('lead-pipeline.md', NOTE), self.root)
        self.assertEqual(rec['slug'], 'lead-pipeline')
        self.assertEqual(rec['title'], 'Leady VD i oferty')
        self.assertEqual(rec['projects'], ['job-radar', 'vectordigital'])
        self.assertEqual(rec['lanes'], ['job-radar', 'vectordigital'])
        self.assertEqual(rec['warnings'], [])
        self.assertEqual(len(rec['bpmn_hash']), 64)
        self.assertEqual(rec['path'], '2-Obszary/mapy/procesy/lead-pipeline.md')
        self.assertEqual(rec['bpmn_path'], '2-Obszary/mapy/procesy/lead-pipeline.bpmn')

    def test_lane_mismatch_is_a_warning(self):
        self.write('lead-pipeline.bpmn', BPMN.replace('vectordigital', 'natalia-cv'))
        rec = vpr.parse_process_file(self.write('lead-pipeline.md', NOTE), self.root)
        self.assertIn('lanes missing from projects: natalia-cv', rec['warnings'])
        self.assertIn('projects without a lane: vectordigital', rec['warnings'])

    def test_missing_and_broken_diagram(self):
        rec = vpr.parse_process_file(self.write('lead-pipeline.md', NOTE), self.root)
        self.assertEqual(rec['warnings'], ['missing diagram lead-pipeline.bpmn'])
        self.assertIsNone(rec['bpmn_xml'])
        self.write('lead-pipeline.bpmn', '<bpmn:definitions')
        rec = vpr.parse_process_file(self.dir / 'lead-pipeline.md', self.root)
        self.assertTrue(rec['warnings'][0].startswith('diagram lead-pipeline.bpmn is not valid XML'))

    def test_bpmn_name_cannot_escape_folder(self):
        (self.root / 'secret.bpmn').write_text(BPMN)
        rec = vpr.parse_process_file(self.write('x.md', NOTE.replace('lead-pipeline.bpmn', '../../../secret.bpmn')), self.root)
        self.assertEqual(rec['warnings'], ['missing diagram secret.bpmn'])

    def test_project_note_is_not_a_process(self):
        p = self.write('strummy.md', '---\ntype: project\nstatus: hot\n---\n# Strummy\n')
        self.assertIsNone(vpr.parse_process_file(p, self.root))

    def test_find_processes_dedupes_slugs(self):
        self.write('lead-pipeline.bpmn', BPMN)
        self.write('lead-pipeline.md', NOTE)
        self.write('copy.md', NOTE)
        self.write('strummy.md', '---\ntype: project\nstatus: hot\n---\n')
        records, problems = vpr.find_processes(self.root, ['2-Obszary', 'missing-dir'])
        self.assertEqual([r['slug'] for r in records], ['lead-pipeline'])
        self.assertEqual(len(problems), 1)
        self.assertIn('duplicate process slug "lead-pipeline"', problems[0])


if __name__ == '__main__':
    unittest.main()
