"""Every subprocess call with env= in tests/ goes through ``child_env``.

A child that imports onnxruntime directly, or that gets a stripped env, does
not pass through src/preached/__init__.py, so ORT telemetry is on unless the
env carries ORT_DISABLE_TELEMETRY=1. ``tests/subproc_env.py`` builds such an
env. This module scans the source of tests/ (AST, nothing is run) and fails
on a subprocess.run/Popen/call/check_call/check_output whose env= value does
not trace back to ``child_env``. scripts/ is held to the same rule by a
plain "names the variable" check, because those scripts run standalone.

An env= value passes when it is
- a call to ``child_env``, or to a function in the same file that calls it;
- a name or attribute assigned in the same file, where every assignment passes;
- built in a function that names ORT_DISABLE_TELEMETRY itself (the telemetry
  tests set or drop it on purpose).
"""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CALLS = {"run", "Popen", "call", "check_call", "check_output"}
FLAG = "ORT_DISABLE_TELEMETRY"
HELPER = "child_env"


def _subprocess_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            names.update(a.asname or a.name for a in node.names if a.name in CALLS)
    return names


def _is_subprocess_call(node: ast.Call, bare: set[str]) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr in CALLS and isinstance(func.value, ast.Name) and func.value.id == "subprocess"
    return isinstance(func, ast.Name) and func.id in bare


def _target_key(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _assignments(scope: ast.AST) -> dict[str, list[ast.AST]]:
    assigned: dict[str, list[ast.AST]] = {}
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            key = _target_key(target)
            if key:
                assigned.setdefault(key, []).append(value)
    return assigned


class _Module:
    def __init__(self, tree: ast.AST) -> None:
        self.attributes = _assignments(tree)  # every assignment in the file, for self.x
        self.functions: dict[str, ast.AST] = {
            n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def ok(self, expr: ast.AST, scope: ast.AST, seen: frozenset[str] = frozenset()) -> bool:
        """``scope`` is the function holding ``expr``; a bare name is looked up there only."""
        if isinstance(expr, ast.Constant) and expr.value is None:
            return True  # env=None inherits the parent's env, which has the flag set
        if isinstance(expr, ast.Call):
            key = _target_key(expr.func)
            if key == HELPER:
                return True
            if key in self.functions and key not in seen:
                func = self.functions[key]
                return self.function_ok(func, seen | {key})
            return False
        key = _target_key(expr)
        if key is None or key in seen:
            return False
        table = self.attributes if isinstance(expr, ast.Attribute) else _assignments(scope)
        values = table.get(key)
        return bool(values) and all(self.ok(value, scope, seen | {key}) for value in values)

    def function_ok(self, func: ast.AST, seen: frozenset[str]) -> bool:
        return any(
            (isinstance(n, ast.Call) and _target_key(n.func) == HELPER)
            or (isinstance(n, ast.Return) and n.value is not None and self.ok(n.value, func, seen))
            for n in ast.walk(func)
        )


def _enclosing_functions(tree: ast.AST) -> dict[int, ast.AST]:
    """Map id(call node) to its innermost enclosing function."""
    found: dict[int, ast.AST] = {}

    def visit(node: ast.AST, func: ast.AST | None) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func = node
        if isinstance(node, ast.Call) and func is not None:
            found[id(node)] = func
        for child in ast.iter_child_nodes(node):
            visit(child, func)

    visit(tree, None)
    return found


def _names_flag(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Constant) and n.value == FLAG for n in ast.walk(node))


def offenders(source: str, name: str = "<test>") -> list[str]:
    """``file:line`` of each subprocess call whose env= may lack the flag."""
    tree = ast.parse(source, name)
    bare = _subprocess_names(tree)
    module = _Module(tree)
    enclosing = _enclosing_functions(tree)
    bad = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _is_subprocess_call(node, bare)):
            continue
        for keyword in node.keywords:
            if keyword.arg != "env":
                continue
            func = enclosing.get(id(node))
            scope = func if func is not None else tree
            if module.ok(keyword.value, scope) or (func is not None and _names_flag(func)):
                continue
            bad.append(f"{name}:{node.lineno}")
    return bad


class SourceScanTests(unittest.TestCase):
    def test_every_test_subprocess_env_carries_the_flag(self) -> None:
        bad = []
        for path in sorted((ROOT / "tests").glob("*.py")):
            if path.name == Path(__file__).name:
                continue
            bad += offenders(path.read_text(encoding="utf-8"), f"tests/{path.name}")
        self.assertEqual(bad, [], "subprocess env= must come from tests/subproc_env.child_env")

    def test_every_script_subprocess_env_names_the_flag(self) -> None:
        bad = []
        for path in sorted((ROOT / "scripts").glob("*.py")):
            text = path.read_text(encoding="utf-8")
            if offenders(text, f"scripts/{path.name}") and FLAG not in text:
                bad.append(f"scripts/{path.name}")
        self.assertEqual(bad, [], "scripts that spawn a child with env= must set ORT_DISABLE_TELEMETRY=1")


class DetectorTests(unittest.TestCase):
    """The scan itself: what it flags and what it lets through."""

    def flagged(self, source: str) -> int:
        return len(offenders(source))

    def test_flags_a_stripped_env(self) -> None:
        self.assertEqual(self.flagged("import subprocess, os\nsubprocess.run(['x'], env={'PATH': os.environ['PATH']})\n"), 1)

    def test_flags_a_copy_of_the_parent_env(self) -> None:
        self.assertEqual(self.flagged("import subprocess, os\nsubprocess.Popen(['x'], env={**os.environ, 'A': '1'})\n"), 1)

    def test_flags_a_name_bound_to_a_plain_dict(self) -> None:
        self.assertEqual(self.flagged("import subprocess\ndef f():\n    env = {'A': '1'}\n    subprocess.check_output(['x'], env=env)\n"), 1)

    def test_flags_a_bare_imported_call(self) -> None:
        self.assertEqual(self.flagged("from subprocess import run\nrun(['x'], env={})\n"), 1)

    def test_flags_when_any_assignment_is_plain(self) -> None:
        source = "import subprocess\ndef f(a):\n    env = child_env()\n    if a:\n        env = {}\n    subprocess.run(['x'], env=env)\n"
        self.assertEqual(self.flagged(source), 1)

    def test_passes_the_helper(self) -> None:
        self.assertEqual(self.flagged("import subprocess\nsubprocess.run(['x'], env=child_env(A='1'))\n"), 0)

    def test_passes_a_name_from_the_helper(self) -> None:
        self.assertEqual(self.flagged("import subprocess\ndef f():\n    env = child_env()\n    subprocess.run(['x'], env=env)\n"), 0)

    def test_passes_a_local_function_that_calls_the_helper(self) -> None:
        source = "import subprocess\nclass T:\n    def _env(self):\n        return child_env()\n    def t(self):\n        subprocess.run(['x'], env=self._env())\n"
        self.assertEqual(self.flagged(source), 0)

    def test_passes_a_function_that_names_the_flag(self) -> None:
        self.assertEqual(self.flagged("import subprocess\ndef f():\n    env = {'ORT_DISABLE_TELEMETRY': '0'}\n    subprocess.run(['x'], env=env)\n"), 0)

    def test_ignores_calls_without_env(self) -> None:
        self.assertEqual(self.flagged("import subprocess\nsubprocess.run(['x'])\n"), 0)


class HelperTests(unittest.TestCase):
    def test_child_env_always_sets_the_flag_and_scratch_dirs(self) -> None:
        import tempfile

        from_module = __import__("importlib").import_module("tests.subproc_env" if __package__ else "subproc_env")
        env = from_module.child_env({"ORT_DISABLE_TELEMETRY": "0", "HOME": "/real"}, ORT_DISABLE_TELEMETRY="0")
        self.assertEqual(env["ORT_DISABLE_TELEMETRY"], "1")
        temp = Path(tempfile.gettempdir()).resolve()
        for key in ("HOME", "XDG_CACHE_HOME"):
            path = Path(env[key])
            self.assertTrue(path.is_dir())
            self.assertIn(temp, path.resolve().parents)
        self.assertEqual(set(from_module.child_env()), {"PATH", "HOME", "XDG_CACHE_HOME", "ORT_DISABLE_TELEMETRY"})
        kept = from_module.child_env({"XDG_CACHE_HOME": "/placed"}, keep=("XDG_CACHE_HOME",))
        self.assertEqual(kept["XDG_CACHE_HOME"], "/placed")


if __name__ == "__main__":
    unittest.main()
