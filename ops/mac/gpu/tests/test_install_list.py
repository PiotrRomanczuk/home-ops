"""Test that install-gpu.sh copies every module the GPU supervisor imports from its own directory.

A module missing from the list makes the installed gpu_worker.py die with ImportError at start (launchd
then restarts it in a loop) — a regression that already happened once when gpu_pause.py was split out.

Run:
    python3 -m unittest discover -s ops/mac/gpu/tests -p 'test_*.py' -v
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

GPU = Path(__file__).resolve().parent.parent


def installed_modules() -> set[str]:
    script = (GPU / 'install-gpu.sh').read_text().replace('\\\n', ' ')
    code_install = next(line for line in script.splitlines() if line.startswith('install -o') and '$LIB/' in line)
    return set(re.findall(r'"\$HERE/(\w+)\.py"', code_install))


def local_imports(module: str, seen: set[str]) -> set[str]:
    """Modules of ops/mac/gpu that `module` imports, directly or through another local module."""
    for node in ast.walk(ast.parse((GPU / f'{module}.py').read_text())):
        names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
            [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
        for name in names:
            top = name.split('.')[0]
            if top not in seen and (GPU / f'{top}.py').exists():
                seen.add(top)
                local_imports(top, seen)
    return seen


class InstallListTest(unittest.TestCase):
    def test_install_covers_every_module_the_supervisor_imports(self) -> None:
        needed = local_imports('gpu_worker', {'gpu_worker'})
        self.assertGreater(len(needed), 1)
        self.assertEqual(sorted(needed - installed_modules()), [], 'install-gpu.sh does not copy these modules')

    def test_install_checks_the_import_from_the_target_directory(self) -> None:
        script = (GPU / 'install-gpu.sh').read_text()
        self.assertRegex(script, r"(?m)^/usr/bin/python3 (-B )?-c '[^']*import gpu_worker' \"\$LIB\"$")
        self.assertLess(script.index('import gpu_worker'), script.index('if [ "${1:-}" ]'))  # right after the copy


if __name__ == '__main__':
    unittest.main()
