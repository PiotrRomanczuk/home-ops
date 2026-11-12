"""Tests for storage_md — the parser behind storage_places (vault place notes).

Run:
    python3 -m unittest discover -s agents/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load():
    path = REPO_ROOT / 'agents' / 'elitedesk' / 'storage_md.py'
    spec = importlib.util.spec_from_file_location('storage_md', path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sm = _load()

NOTE = (
    '---\n'
    'type: miejsce\n'
    'id: 8\n'
    'nazwa: "Google Drive"\n'
    'gdzie: "Google Drive"\n'
    'sciezka:\n'
    'rola: "dokumenty, wideo, \\"offsite\\" backupów NAS"\n'
    'stan: aktywne\n'
    'porzadek: problem\n'
    'backup: problem\n'
    'sprawdzone: 2026-11-12\n'
    'test_odtworzenia:\n'
    "sprawdzenie: 'rclone about gdrive:'\n"
    'problem: "176 luźnych plików"\n'
    'updated: 2026-11-12\n'
    '---\n\n# 08 · Google Drive\n'
)


class ParsePlaceTest(unittest.TestCase):
    def test_reads_typed_fields(self) -> None:
        rec = sm.parse_place(NOTE, '2-Obszary/mapy/miejsca/08-google-drive.md')
        self.assertEqual(rec['id'], 8)
        self.assertEqual(rec['nazwa'], 'Google Drive')
        self.assertEqual(rec['rola'], 'dokumenty, wideo, "offsite" backupów NAS')
        self.assertEqual(rec['sprawdzenie'], 'rclone about gdrive:')
        self.assertEqual(rec['sprawdzone'], '2026-11-12')
        self.assertEqual(rec['updated_at'], '2026-11-12')
        self.assertEqual(rec['note_path'], '2-Obszary/mapy/miejsca/08-google-drive.md')

    def test_empty_values_become_none(self) -> None:
        rec = sm.parse_place(NOTE, 'x.md')
        self.assertIsNone(rec['sciezka'])
        self.assertIsNone(rec['test_odtworzenia'])

    def test_skips_notes_that_are_not_places(self) -> None:
        self.assertIsNone(sm.parse_place(NOTE.replace('type: miejsce', 'type: project'), 'x.md'))
        self.assertIsNone(sm.parse_place('# bez frontmattera\n', 'x.md'))

    def test_keeps_invalid_status_for_the_server_to_reject(self) -> None:
        rec = sm.parse_place(NOTE.replace('porzadek: problem', 'porzadek: 🟢'), 'x.md')
        self.assertEqual(rec['porzadek'], '🟢')


class ParsePlacesTest(unittest.TestCase):
    def test_walks_the_register_folder_in_name_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / sm.PLACES_DIR
            folder.mkdir(parents=True)
            (folder / '74-onedrive.md').write_text(NOTE.replace('id: 8', 'id: 74'), encoding='utf-8')
            (folder / '08-google-drive.md').write_text(NOTE, encoding='utf-8')
            (folder / 'README.md').write_text('# opis folderu\n', encoding='utf-8')
            places = sm.parse_places(root)
        self.assertEqual([p['id'] for p in places], [8, 74])
        self.assertEqual(places[0]['note_path'], '2-Obszary/mapy/miejsca/08-google-drive.md')

    def test_missing_folder_is_an_empty_register(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(sm.parse_places(Path(tmp)), [])


if __name__ == '__main__':
    unittest.main()
