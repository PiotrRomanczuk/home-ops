"""Every stdlib module an agent uses as `name.attr` must be imported.

Regression guard: d3a272b dropped `import json` from elitedesk-watcher.py, so
each journald follower thread died with NameError on its first line and the
watched units silently stopped shipping logs.

Run:
    python3 -m unittest discover -s agents/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
STDLIB = {'json', 'os', 're', 'subprocess', 'sys', 'time', 'queue', 'threading', 'signal', 'socket'}


def missing_imports(source: str) -> set[str]:
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update((a.asname or a.name).split('.')[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.update(a.asname or a.name for a in node.names)
    used = {n.value.id for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in STDLIB}
    return used - imported


class AgentImportsTest(unittest.TestCase):
    def test_every_agent_imports_what_it_uses(self) -> None:
        files = sorted((REPO_ROOT / 'agents').rglob('*.py'))
        self.assertTrue(files)
        for path in files:
            if 'tests' in path.parts:
                continue
            with self.subTest(agent=str(path.relative_to(REPO_ROOT))):
                self.assertEqual(missing_imports(path.read_text()), set())

    def test_detects_a_missing_import(self) -> None:
        self.assertEqual(missing_imports('import os\nx = json.loads(os.getcwd())\n'), {'json'})


if __name__ == '__main__':
    unittest.main()
