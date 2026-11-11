"""process_writes — BPMN saves from the Mapa tab, written back into the vault.

The browser posts the edited diagram plus the hash of the version it opened
(migration 030). Before planner-sync commits anything, `check_write` decides:

  apply     — the vault file still has that hash and the new XML parses
  conflict  — the file changed since it was opened (Obsidian edit, another
              save); the editor must reload, nothing is overwritten
  failed    — unknown process or XML that isn't a BPMN document

Pure: no git, no network. planner-sync does the commit + push.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

_DEFINITIONS = '{http://www.omg.org/spec/BPMN/20100524/MODEL}definitions'


def check_write(write: dict[str, Any], current: dict[str, Any] | None) -> tuple[str, str | None]:
    """(verdict, reason) for one queued write against the vault's current record."""
    if current is None:
        return 'failed', f'unknown process {write.get("slug")!r}'
    xml = write.get('bpmn_xml')
    if not isinstance(xml, str):
        return 'failed', 'bpmn_xml missing'
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        return 'failed', f'not valid XML: {e}'
    if root.tag != _DEFINITIONS:
        return 'failed', f'root element is {root.tag}, not bpmn:definitions'
    if current.get('bpmn_hash') != write.get('base_hash'):
        return 'conflict', 'diagram changed in the vault since it was opened — reload and redo the edit'
    return 'apply', None


def commit_message(write: dict[str, Any]) -> str:
    return f'procesy: {write.get("slug")} edytowany w Mapie (home-ops, zapis #{write.get("id")})'
