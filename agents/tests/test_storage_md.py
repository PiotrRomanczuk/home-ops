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

    def test_reads_notes_with_bom_and_crlf(self) -> None:
        rec = sm.parse_place('\ufeff' + NOTE.replace('\n', '\r\n'), 'x.md')
        self.assertEqual(rec['id'], 8)
        self.assertEqual(rec['porzadek'], 'problem')
        self.assertEqual(rec['sprawdzenie'], 'rclone about gdrive:')

    def test_cuts_a_trailing_comment_from_bare_values_only(self) -> None:
        note = NOTE.replace('backup: problem', 'backup: ok # sprawdzić', 1).replace(
            'problem: "176', 'gdzie: C# dysk\nproblem: "176')
        rec = sm.parse_place(note, 'x.md')
        self.assertEqual(rec['backup'], 'ok')
        self.assertEqual(rec['gdzie'], 'C# dysk')

    def test_a_value_that_is_only_a_comment_is_empty(self) -> None:
        rec = sm.parse_place(NOTE.replace('test_odtworzenia:', 'test_odtworzenia: # jeszcze nie'), 'x.md')
        self.assertIsNone(rec['test_odtworzenia'])


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

    def _parse(self, files: dict[str, bytes]) -> list[dict]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / sm.PLACES_DIR
            folder.mkdir(parents=True)
            for name, data in files.items():
                (folder / name).write_bytes(data)
            return sm.parse_places(root)

    def _only(self, name: str, data: bytes) -> dict:
        places = self._parse({name: data, 'README.md': b'# opis\n'})
        self.assertEqual(len(places), 1)
        return places[0]

    def test_unreadable_note_becomes_a_stub_with_its_id(self) -> None:
        rec = self._only('12-x.md', NOTE.encode() + b'\xff')
        self.assertEqual((rec['id'], rec['nazwa']), (12, None))
        self.assertIn('unreadable', rec['unparsed'])

    def test_frontmatter_closed_at_end_of_file_still_parses(self) -> None:
        rec = self._only('08-x.md', b'---\ntype: miejsce\nid: 8\nnazwa: A\n---')
        self.assertEqual((rec['id'], rec['nazwa']), (8, 'A'))
        self.assertNotIn('unparsed', rec)

    def test_wrong_type_becomes_a_stub(self) -> None:
        rec = self._only('08-x.md', NOTE.replace('type: miejsce', 'type: Miejsce').encode())
        self.assertEqual((rec['id'], rec['nazwa']), (8, None))
        self.assertIn('unparsed', rec)

    def test_note_without_frontmatter_becomes_a_stub(self) -> None:
        rec = self._only('09-x.md', b'# pusta notatka\n')
        self.assertEqual((rec['id'], rec['unparsed']), (9, 'no frontmatter'))

    def test_quoted_id_becomes_int(self) -> None:
        rec = self._only('04-x.md', NOTE.replace('id: 8', 'id: "4"').encode())
        self.assertEqual(rec['id'], 4)

    def test_missing_id_comes_from_the_file_prefix(self) -> None:
        rec = self._only('05-x.md', NOTE.replace('id: 8\n', '').encode())
        self.assertEqual((rec['id'], rec['nazwa']), (5, 'Google Drive'))

    def test_files_without_a_number_prefix_are_skipped(self) -> None:
        self.assertEqual(self._parse({'README.md': NOTE.encode(), 'szablon.md': b'x'}), [])

    def test_missing_folder_is_an_empty_register(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(sm.parse_places(Path(tmp)), [])


if __name__ == '__main__':
    unittest.main()
