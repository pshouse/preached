"""No test may leave a bare ``.venv`` in the worktree.

A dangling link to ``ROOT/.venv`` made ``uv run`` create a bare one there
(no numpy), and later deploy and shutdown tests then picked its interpreter.
"""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKTREE_VENV = ROOT / ".venv"
EXISTED_AT_IMPORT = WORKTREE_VENV.exists() or WORKTREE_VENV.is_symlink()

# ROOT / ".venv" or ROOT.joinpath(".venv"), in either quote style.
_POINTS_AT_WORKTREE_VENV = re.compile(r"""ROOT\s*(?:/|\.joinpath\()\s*["']\.venv["']""")


class WorktreeVenvTests(unittest.TestCase):
    def test_no_test_names_the_worktree_venv(self) -> None:
        offenders = []
        for path in sorted((ROOT / "tests").glob("*.py")):
            if path.name == Path(__file__).name:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if _POINTS_AT_WORKTREE_VENV.search(line):
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
        self.assertEqual(offenders, [], "tests must use sys.executable / sys.prefix or a temp venv")

    def test_the_suite_has_not_created_a_worktree_venv(self) -> None:
        # Sorts after test_deploy, test_onnx_pin_repro and test_shutdown.
        created = (WORKTREE_VENV.exists() or WORKTREE_VENV.is_symlink()) and not EXISTED_AT_IMPORT
        self.assertFalse(created, f"a test created {WORKTREE_VENV}")


if __name__ == "__main__":
    unittest.main()
