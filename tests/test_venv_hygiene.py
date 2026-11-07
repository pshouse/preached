"""No test may leave a bare ``.venv`` in the worktree.

A dangling link to ``ROOT/.venv`` made ``uv run`` create a bare one there
(no numpy), and later deploy and shutdown tests then picked its interpreter.
"""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKTREE_VENV = ROOT / ".venv"
EXISTED_AT_IMPORT = WORKTREE_VENV.exists() or WORKTREE_VENV.is_symlink()

def worktree_venv_lines(source: str) -> list[int]:
    """Line numbers of ``ROOT / ".venv"`` and ``ROOT.joinpath(".venv")`` in code.

    Parsed, so comments, docstrings and other strings that merely mention the
    expression do not count, and either quote style matches.
    """
    def is_venv(node: ast.AST) -> bool:
        return isinstance(node, ast.Constant) and node.value == ".venv"

    def is_root(node: ast.AST) -> bool:
        return isinstance(node, ast.Name) and node.id == "ROOT"

    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and is_root(node.left) and is_venv(node.right):
            lines.append(node.lineno)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "joinpath"
            and is_root(node.func.value)
            and node.args
            and is_venv(node.args[0])
        ):
            lines.append(node.lineno)
    return sorted(lines)


class WorktreeVenvTests(unittest.TestCase):
    def test_no_test_names_the_worktree_venv(self) -> None:
        offenders = []
        for path in sorted((ROOT / "tests").glob("*.py")):
            if path.name == Path(__file__).name:
                continue
            source = path.read_text(encoding="utf-8")
            lines = source.splitlines()
            for number in worktree_venv_lines(source):
                offenders.append(f"{path.name}:{number}: {lines[number - 1].strip()}")
        self.assertEqual(offenders, [], "tests must use sys.executable / sys.prefix or a temp venv")

    def test_the_detector_sees_every_spelling(self) -> None:
        for source in (
            'p = ROOT / ".venv" / "bin" / "python"\n',
            "p = ROOT / '.venv'\n",
            'p = ROOT.joinpath(".venv")\n',
            "p = ROOT.joinpath('.venv', 'bin')\n",
        ):
            with self.subTest(source=source):
                self.assertEqual(worktree_venv_lines(source), [1])

    def test_the_detector_ignores_comments_and_strings(self) -> None:
        source = (
            '# never use ROOT / ".venv" here\n'
            'text = "ROOT / \'.venv\' and ROOT.joinpath(\'.venv\')"\n'
            '"""docstring: ROOT.joinpath(".venv")"""\n'
            'ok = Path(sys.prefix) / ".venv"\n'
            'tmp = root / ".venv"\n'
        )
        self.assertEqual(worktree_venv_lines(source), [])

    def test_the_suite_has_not_created_a_worktree_venv(self) -> None:
        # Sorts after test_deploy, test_onnx_pin_repro and test_shutdown.
        created = (WORKTREE_VENV.exists() or WORKTREE_VENV.is_symlink()) and not EXISTED_AT_IMPORT
        self.assertFalse(created, f"a test created {WORKTREE_VENV}")


if __name__ == "__main__":
    unittest.main()
