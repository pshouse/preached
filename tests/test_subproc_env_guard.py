"""Every child process with an env in tests/ and scripts/ is built by a known-good source.

A child that imports onnxruntime directly, or that gets a stripped env, does
not pass through src/preached/__init__.py, so ORT telemetry is on unless the
env carries ORT_DISABLE_TELEMETRY=1. ``tests/subproc_env.py`` builds such an
env. This module scans the source (AST, nothing is run) for calls that start a
child: ``subprocess.run/Popen/call/check_call/check_output``, the env-taking
``os.exec*e``/``os.spawn*e``/``os.posix_spawn[p]``, and
``asyncio.create_subprocess_exec/shell``, under any import alias.

In tests/, an env value passes when it is
- None (the child inherits the parent's env, which has the flag set);
- a call to ``child_env`` that really comes from ``subproc_env`` (an import, no
  local def, assignment or parameter of that name), or to a function in the same
  file whose every return passes (all same-named definitions must pass);
- a name or attribute assigned in the same file, where every assignment passes
  and nothing later touches the flag (``pop``, ``del``, ``update``, ``clear``,
  a store of another value, or a store under a non-constant key), also through
  an alias of the name.

In scripts/ (which run standalone and cannot import the helper) the call itself
must pass: a dict that sets ORT_DISABLE_TELEMETRY to "1" after any ``**``
spread, or a name that gets ``env["ORT_DISABLE_TELEMETRY"] = "1"`` after its
last assignment and before the call. A mention of the flag elsewhere in the
file (a comment, another function) does not count.

A call that hides its env (``**kwargs`` or ``*args``) is flagged. A test that
sets or drops the flag on purpose goes in ``ALLOW`` below, by (file, function)
with a reason; an entry that no longer matches a flagged call fails the scan.
"""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import ast
import unittest
from pathlib import Path

if __package__:
    from . import subproc_env
else:
    import subproc_env

ROOT = Path(__file__).resolve().parent.parent
FLAG = "ORT_DISABLE_TELEMETRY"
HELPER = "child_env"
HELPER_MODULES = {"subproc_env", "tests.subproc_env"}

SUBPROCESS_CALLS = {"run", "Popen", "call", "check_call", "check_output"}
SUBPROCESS_ENV_INDEX = 10  # Popen(args, bufsize, executable, stdin, stdout, stderr, preexec_fn, close_fds, shell, cwd, env)
ASYNCIO_CALLS = {"create_subprocess_exec", "create_subprocess_shell"}
OS_ENV_LAST = {"execle", "execlpe", "spawnle", "spawnlpe"}  # env is the last positional
OS_ENV_INDEX = {"execve": 2, "execvpe": 2, "spawnve": 3, "spawnvpe": 3, "posix_spawn": 2, "posix_spawnp": 2}
MODULE_CALLS = {"subprocess": SUBPROCESS_CALLS, "asyncio": ASYNCIO_CALLS, "os": OS_ENV_LAST | set(OS_ENV_INDEX)}

# (file, function) -> why its env may lack the flag. "Class.method" for methods.
ALLOW = {
    ("tests/test_child_home_guard.py", "RealModelChildHomeTests.test_guard_sees_a_telemetry_write"): (
        "red check: pops the flag on purpose to show the guard sees a telemetry write"
    ),
    ("tests/test_ort_telemetry_off.py", "OrtTelemetryTests._run"): (
        "builds the env by hand to set the flag to None, '0' or '1' and prove the src/preached default"
    ),
}


class _Calls:
    """Which names mean a watched module or a watched function in one file."""

    def __init__(self, tree: ast.AST) -> None:
        self.modules: dict[str, str] = {name: name for name in MODULE_CALLS}  # local name -> module
        self.functions: dict[str, tuple[str, str]] = {}  # local name -> (module, function)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in MODULE_CALLS:
                        self.modules[alias.asname or alias.name] = alias.name
            elif isinstance(node, ast.ImportFrom) and node.module in MODULE_CALLS and not node.level:
                for alias in node.names:
                    if alias.name == "*":
                        self.functions.update({n: (node.module, n) for n in MODULE_CALLS[node.module]})
                    elif alias.name in MODULE_CALLS[node.module]:
                        self.functions[alias.asname or alias.name] = (node.module, alias.name)
        for node in ast.walk(tree):  # run = subprocess.run
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Attribute):
                module = self._module_of(node.value.value)
                if module and node.value.attr in MODULE_CALLS[module]:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            self.functions[target.id] = (module, node.value.attr)

    def _module_of(self, node: ast.AST) -> str | None:
        return self.modules.get(node.id) if isinstance(node, ast.Name) else None

    def classify(self, call: ast.Call) -> tuple[str, str] | None:
        func = call.func
        if isinstance(func, ast.Attribute):
            module = self._module_of(func.value)
            if module and func.attr in MODULE_CALLS[module]:
                return module, func.attr
            return None
        if isinstance(func, ast.Name):
            return self.functions.get(func.id)
        return None

    @staticmethod
    def env_args(call: ast.Call, module: str, name: str) -> tuple[list[ast.AST], bool]:
        """The env expressions this call passes, and whether it may hide one (``**kw``, ``*args``)."""
        envs = [k.value for k in call.keywords if k.arg == "env"]
        args = call.args
        hidden = any(k.arg is None for k in call.keywords)
        starred = [i for i, a in enumerate(args) if isinstance(a, ast.Starred)]
        if module == "asyncio":
            index = None  # env is keyword-only; *args are the command's own arguments
        elif name in OS_ENV_LAST:
            index = len(args) - 1
        else:
            index = SUBPROCESS_ENV_INDEX if module == "subprocess" else OS_ENV_INDEX[name]
        if index is not None:
            if starred and (name in OS_ENV_LAST and starred[-1] == index or name not in OS_ENV_LAST and starred[0] <= index):
                hidden = True
            elif 0 <= index < len(args):
                envs.append(args[index])
        return envs, hidden and not envs


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


def _is_str(node: ast.AST | None, value: str | None = None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and (value is None or node.value == value)


def _helper_names(tree: ast.AST) -> tuple[set[str], set[str]]:
    """(names that are ``child_env``, names that are the ``subproc_env`` module), if really imported.

    Empty when the file also binds ``child_env`` any other way: a local def, class,
    assignment, loop or ``with`` target, parameter, except-name, or another import.
    """
    direct: set[str] = set()
    modules: set[str] = set()
    imported: set[int] = set()  # id() of alias nodes that are the real import
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            source = node.module or ""
            for alias in node.names:
                if source in HELPER_MODULES and alias.name == HELPER:
                    direct.add(alias.asname or alias.name)
                    imported.add(id(alias))
                elif alias.name == "subproc_env" and source in ("", "tests"):
                    modules.add(alias.asname or alias.name)
                    imported.add(id(alias))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in HELPER_MODULES and alias.asname:
                    modules.add(alias.asname)
                    imported.add(id(alias))
                elif alias.name == "subproc_env":
                    modules.add("subproc_env")
                    imported.add(id(alias))
    watched = direct | modules | {HELPER}
    for node in ast.walk(tree):
        bound: str | None = None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound = node.name
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound = node.id
        elif isinstance(node, ast.arg):
            bound = node.arg
        elif isinstance(node, ast.ExceptHandler):
            bound = node.name
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound = next((n for n in node.names if n in watched), None)
        elif isinstance(node, ast.alias) and id(node) not in imported:
            bound = (node.asname or node.name).split(".")[0]
        if bound in watched:
            return set(), set()
    return direct, modules


class _Module:
    def __init__(self, tree: ast.AST, scripts: bool = False) -> None:
        self.scripts = scripts
        self.attributes = _assignments(tree)  # every assignment in the file, for self.x
        self.functions: dict[str, list[ast.AST]] = {}
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions.setdefault(n.name, []).append(n)  # every definition, not just the last
        self.helper, self.helper_modules = _helper_names(tree)

    def is_helper_call(self, call: ast.Call) -> bool:
        func = call.func
        if isinstance(func, ast.Name):
            return func.id in self.helper
        return (
            isinstance(func, ast.Attribute)
            and func.attr == HELPER
            and isinstance(func.value, ast.Name)
            and func.value.id in self.helper_modules
        )

    def ok(self, expr: ast.AST, scope: ast.AST, seen: frozenset[str] = frozenset(), line: int = 0) -> bool:
        """``scope`` is the function holding ``expr``; a bare name is looked up there only."""
        if isinstance(expr, ast.Constant) and expr.value is None:
            return True  # env=None inherits the parent's env, which has the flag set
        if self.scripts and self.sets_flag(expr):
            return True
        if isinstance(expr, ast.Call):
            if not self.scripts and self.is_helper_call(expr):
                return True
            key = _target_key(expr.func)
            if key in self.functions and key not in seen:
                return all(self.function_ok(f, seen | {key}) for f in self.functions[key])
            return False
        key = _target_key(expr)
        if key is None or key in seen:
            return False
        is_attr = isinstance(expr, ast.Attribute)
        table = self.attributes if is_attr else _assignments(scope)
        values = table.get(key)
        if not values:
            return False
        marks = self.flag_marks(scope, key, is_attr)
        if self.scripts:
            # the last `env[FLAG] = "1"` after the final assignment and before the call, with no other write after it
            last = max(getattr(v, "lineno", 0) for v in values)
            sets = [at for kind, at in marks if kind == "set" and last <= at < line]
            if sets and not any(kind == "touch" and at > max(sets) for kind, at in marks):
                return True
        if any(kind == "touch" for kind, _ in marks):
            return False
        return all(self.ok(value, scope, seen | {key}, line) for value in values)

    def sets_flag(self, expr: ast.AST) -> bool:
        """A dict display or ``dict(...)`` that sets the flag to "1" last."""
        if isinstance(expr, ast.Dict):
            spreads = [i for i, k in enumerate(expr.keys) if k is None]
            for i, (k, v) in enumerate(zip(expr.keys, expr.values)):
                if _is_str(k, FLAG) and _is_str(v, "1") and all(s < i for s in spreads):
                    return not any(_is_str(k2, FLAG) and not _is_str(v2, "1") for k2, v2 in zip(expr.keys[i + 1 :], expr.values[i + 1 :]))
            return False
        if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "dict":
            return any(k.arg == FLAG and _is_str(k.value, "1") for k in expr.keywords)
        return False

    def function_ok(self, func: ast.AST, seen: frozenset[str]) -> bool:
        returns = list(_returns(func))
        return bool(returns) and all(r.value is not None and self.ok(r.value, func, seen, r.lineno) for r in returns)

    def flag_marks(self, scope: ast.AST, key: str, is_attr: bool) -> list[tuple[str, int]]:
        """Writes to the dict named ``key`` (or an alias of it): ("set", line) for ``[FLAG] = "1"``, ("touch", line) for others that may change the flag."""
        names = {key}
        grew = True
        while grew:  # other = env: a write through `other` changes the same dict
            grew = False
            for name, values in (self.attributes if is_attr else _assignments(scope)).items():
                if name not in names and any(_target_key(v) in names and isinstance(v, (ast.Name, ast.Attribute)) for v in values):
                    names.add(name)
                    grew = True

        def named(node: ast.AST) -> bool:
            if is_attr:
                return isinstance(node, ast.Attribute) and node.attr in names
            return isinstance(node, ast.Name) and node.id in names

        marks: list[tuple[str, int]] = []
        for node in ast.walk(scope):
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
                if isinstance(node, ast.Assign):
                    targets = node.targets
                elif isinstance(node, ast.Delete):
                    targets = node.targets
                else:
                    targets = [node.target]
                    if named(node.target) and isinstance(node, ast.AugAssign):
                        marks.append(("touch", node.lineno))  # env |= {...}
                for target in targets:
                    if isinstance(target, ast.Subscript) and named(target.value):
                        constant = _is_str(target.slice)
                        if constant and target.slice.value != FLAG or self._loop_key_is_safe(scope, target.slice):
                            continue
                        stores_one = isinstance(node, ast.Assign) and _is_str(node.value, "1")
                        marks.append(("set" if constant and stores_one else "touch", node.lineno))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and named(node.func.value):
                method, first = node.func.attr, (node.args[0] if node.args else None)
                if method in {"pop", "setdefault"} and _is_str(first) and first.value != FLAG:
                    continue
                if method == "update" and self._update_is_safe(node):
                    continue
                if method in {"pop", "setdefault", "update", "clear", "popitem", "__setitem__", "__delitem__"}:
                    marks.append(("touch", node.lineno))
        return marks

    @staticmethod
    def _loop_key_is_safe(scope: ast.AST, key: ast.AST) -> bool:
        """``for name in ("A", "B"): env[name] = ...``: every key is a literal other than the flag."""
        if not isinstance(key, ast.Name):
            return False
        loops = [n for n in ast.walk(scope) if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == key.id]
        return bool(loops) and all(
            isinstance(n.iter, (ast.Tuple, ast.List)) and all(_is_str(e) and e.value != FLAG for e in n.iter.elts) for n in loops
        )

    @staticmethod
    def _update_is_safe(call: ast.Call) -> bool:
        if any(k.arg is None or k.arg == FLAG for k in call.keywords):
            return False
        for arg in call.args:
            if not (isinstance(arg, ast.Dict) and all(_is_str(k) and k.value != FLAG for k in arg.keys)):
                return False
        return True


def _returns(func: ast.AST):
    """Return statements of ``func`` itself, not of functions or lambdas nested in it."""
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, ast.Return):
            yield node
        stack.extend(ast.iter_child_nodes(node))


def _enclosing(tree: ast.AST) -> dict[int, tuple[ast.AST | None, str]]:
    """Map id(call node) to (innermost enclosing function, its dotted name)."""
    found: dict[int, tuple[ast.AST | None, str]] = {}

    def visit(node: ast.AST, func: ast.AST | None, path: tuple[str, ...]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func, path = node, path + (node.name,)
        elif isinstance(node, ast.ClassDef):
            path = path + (node.name,)
        if isinstance(node, ast.Call):
            found[id(node)] = (func, ".".join(path) or "<module>")
        for child in ast.iter_child_nodes(node):
            visit(child, func, path)

    visit(tree, None, ())
    return found


def scan(source: str, name: str = "<test>", scripts: bool = False) -> list[tuple[str, int, str]]:
    """(file, line, function) of each child-starting call whose env may lack the flag."""
    tree = ast.parse(source, name)
    calls = _Calls(tree)
    module = _Module(tree, scripts)
    enclosing = _enclosing(tree)
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kind = calls.classify(node)
        if kind is None:
            continue
        envs, hidden = calls.env_args(node, *kind)
        func, qualname = enclosing[id(node)]
        scope = func if func is not None else tree
        if hidden or not all(module.ok(env, scope, line=node.lineno) for env in envs):
            bad.append((name, node.lineno, qualname))
    return sorted(bad, key=lambda b: b[1])


def offenders(source: str, name: str = "<test>", scripts: bool = False, allow=ALLOW) -> list[str]:
    """``file:line`` of each child-starting call whose env may lack the flag, minus the allow-list."""
    return [f"{f}:{line}" for f, line, func in scan(source, name, scripts) if (f, func) not in allow]


class SourceScanTests(unittest.TestCase):
    def test_every_test_subprocess_env_carries_the_flag(self) -> None:
        bad = []
        for path in sorted((ROOT / "tests").glob("*.py")):
            bad += offenders(path.read_text(encoding="utf-8"), f"tests/{path.name}")
        self.assertEqual(bad, [], "child env= must come from tests/subproc_env.child_env (or be in ALLOW)")

    def test_every_allow_entry_still_matches_a_flagged_call(self) -> None:
        hit = set()
        for path in sorted((ROOT / "tests").glob("*.py")):
            hit |= {(f, func) for f, _, func in scan(path.read_text(encoding="utf-8"), f"tests/{path.name}")}
        self.assertEqual(sorted(set(ALLOW) - hit), [], "stale ALLOW entry: delete it")

    def test_every_script_child_env_sets_the_flag_at_the_call(self) -> None:
        bad = []
        for path in sorted((ROOT / "scripts").glob("*.py")):
            bad += offenders(path.read_text(encoding="utf-8"), f"scripts/{path.name}", scripts=True)
        self.assertEqual(bad, [], "scripts that start a child with env= must set ORT_DISABLE_TELEMETRY=1 for that env")


IMPORT = "import subprocess, os\nfrom subproc_env import child_env\n"


class DetectorTests(unittest.TestCase):
    """The scan itself: what it flags and what it lets through."""

    def flagged(self, source: str, scripts: bool = False) -> int:
        return len(offenders(source, scripts=scripts, allow=()))

    def test_flags_a_stripped_env(self) -> None:
        self.assertEqual(self.flagged("import subprocess, os\nsubprocess.run(['x'], env={'PATH': os.environ['PATH']})\n"), 1)

    def test_flags_a_copy_of_the_parent_env(self) -> None:
        self.assertEqual(self.flagged("import subprocess, os\nsubprocess.Popen(['x'], env={**os.environ, 'A': '1'})\n"), 1)

    def test_flags_a_name_bound_to_a_plain_dict(self) -> None:
        self.assertEqual(self.flagged("import subprocess\ndef f():\n    env = {'A': '1'}\n    subprocess.check_output(['x'], env=env)\n"), 1)

    def test_flags_a_bare_imported_call(self) -> None:
        self.assertEqual(self.flagged("from subprocess import run\nrun(['x'], env={})\n"), 1)

    def test_flags_when_any_assignment_is_plain(self) -> None:
        source = IMPORT + "def f(a):\n    env = child_env()\n    if a:\n        env = {}\n    subprocess.run(['x'], env=env)\n"
        self.assertEqual(self.flagged(source), 1)

    def test_passes_the_helper(self) -> None:
        self.assertEqual(self.flagged(IMPORT + "subprocess.run(['x'], env=child_env(A='1'))\n"), 0)

    def test_passes_a_name_from_the_helper(self) -> None:
        self.assertEqual(self.flagged(IMPORT + "def f():\n    env = child_env()\n    subprocess.run(['x'], env=env)\n"), 0)

    def test_passes_a_local_function_that_calls_the_helper(self) -> None:
        source = IMPORT + "class T:\n    def _env(self):\n        return child_env()\n    def t(self):\n        subprocess.run(['x'], env=self._env())\n"
        self.assertEqual(self.flagged(source), 0)

    def test_passes_the_helper_through_a_package_import(self) -> None:
        for line in (
            "from .subproc_env import child_env as ce",
            "from tests.subproc_env import child_env as ce",
        ):
            self.assertEqual(self.flagged(f"import subprocess\n{line}\nsubprocess.run(['x'], env=ce())\n"), 0, line)
        self.assertEqual(self.flagged("import subprocess\nfrom . import subproc_env\nsubprocess.run(['x'], env=subproc_env.child_env())\n"), 0)

    def test_passes_a_harmless_write_after_the_helper(self) -> None:
        source = IMPORT + "def f():\n    env = child_env()\n    env['A'] = '2'\n    env.update(B='3')\n    env.pop('C', None)\n    subprocess.run(['x'], env=env)\n"
        self.assertEqual(self.flagged(source), 0)

    def test_ignores_calls_without_env(self) -> None:
        self.assertEqual(self.flagged("import subprocess\nsubprocess.run(['x'])\n"), 0)

    def test_allow_list_names_a_file_and_function_not_the_flag(self) -> None:
        source = "import subprocess\nclass T:\n    def t(self):\n        subprocess.run(['x'], env={'ORT_DISABLE_TELEMETRY': '0'})\n"
        self.assertEqual(self.flagged(source), 1)  # naming the flag is no longer an exemption
        self.assertEqual(offenders(source, "a.py", allow={("a.py", "T.t")}), [])
        self.assertEqual(len(offenders(source, "a.py", allow={("a.py", "t")})), 1)
        self.assertEqual(len(offenders(source, "b.py", allow={("a.py", "T.t")})), 1)

    # SF2 evasions: each used to pass with 0 flagged.

    def test_flags_an_aliased_subprocess_module(self) -> None:
        self.assertEqual(self.flagged("import subprocess as sp\nsp.run(['x'], env={})\n"), 1)

    def test_flags_an_aliased_bare_call(self) -> None:
        self.assertEqual(self.flagged("from subprocess import Popen as P\nP(['x'], env={})\n"), 1)
        self.assertEqual(self.flagged("import subprocess\nr = subprocess.run\nr(['x'], env={})\n"), 1)
        self.assertEqual(self.flagged("from subprocess import *\nrun(['x'], env={})\n"), 1)

    def test_flags_a_positional_env(self) -> None:
        args = "['x'], -1, None, None, None, None, None, True, False, None, {}"
        self.assertEqual(self.flagged(f"import subprocess\nsubprocess.Popen({args})\n"), 1)

    def test_flags_env_hidden_in_kwargs(self) -> None:
        self.assertEqual(self.flagged("import subprocess\ndef f(**kw):\n    subprocess.run(['x'], **kw)\n"), 1)
        self.assertEqual(self.flagged("import subprocess\nsubprocess.run(['x'], **{'env': {}})\n"), 1)

    def test_flags_os_exec_and_spawn_with_an_env(self) -> None:
        for call in (
            "os.execve('/x', ['x'], {})",
            "os.execvpe('x', ['x'], {})",
            "os.execle('/x', 'x', {})",
            "os.execlpe('x', 'x', {})",
            "os.spawnve(os.P_WAIT, '/x', ['x'], {})",
            "os.spawnvpe(os.P_WAIT, 'x', ['x'], {})",
            "os.spawnle(os.P_WAIT, '/x', 'x', {})",
            "os.spawnlpe(os.P_WAIT, 'x', 'x', {})",
            "os.posix_spawn('/x', ['x'], {})",
            "os.posix_spawnp('x', ['x'], env={})",
        ):
            self.assertEqual(self.flagged(f"import os\n{call}\n"), 1, call)
        self.assertEqual(self.flagged("import os as o\no.execve('/x', ['x'], {})\n"), 1)
        self.assertEqual(self.flagged("from os import execve as e\ne('/x', ['x'], {})\n"), 1)
        self.assertEqual(self.flagged("import os\nos.execv('/x', ['x'])\n"), 0)  # inherits the parent env
        self.assertEqual(self.flagged(IMPORT + "os.execve('/x', ['x'], child_env())\n"), 0)

    def test_flags_asyncio_subprocess(self) -> None:
        for call in ("asyncio.create_subprocess_exec('x', env={})", "asyncio.create_subprocess_shell('x', env={})"):
            self.assertEqual(self.flagged(f"import asyncio\nasync def f():\n    await {call}\n"), 1, call)
        self.assertEqual(self.flagged("from asyncio import create_subprocess_exec as c\nasync def f():\n    await c('x', env={})\n"), 1)
        self.assertEqual(self.flagged(IMPORT + "import asyncio\nasync def f():\n    await asyncio.create_subprocess_exec('x', env=child_env())\n"), 0)

    def test_flags_the_flag_deleted_after_the_helper_returns(self) -> None:
        for edit in ("env.pop('ORT_DISABLE_TELEMETRY')", "del env['ORT_DISABLE_TELEMETRY']", "env['ORT_DISABLE_TELEMETRY'] = '0'",
                     "env.update(ORT_DISABLE_TELEMETRY='0')", "env.update({'ORT_DISABLE_TELEMETRY': '0'})", "env.clear()",
                     "env |= {'ORT_DISABLE_TELEMETRY': '0'}", "env[key] = '0'", "env.update(other)", "env.setdefault(key, '0')"):
            source = IMPORT + f"def f(key, other):\n    env = child_env()\n    {edit}\n    subprocess.run(['x'], env=env)\n"
            self.assertEqual(self.flagged(source), 1, edit)

    def test_flags_a_mutation_through_an_alias_or_attribute(self) -> None:
        source = IMPORT + "def f():\n    env = child_env()\n    other = env\n    other.pop('ORT_DISABLE_TELEMETRY')\n    subprocess.run(['x'], env=env)\n"
        self.assertEqual(self.flagged(source), 1)
        source = IMPORT + "class T:\n    def setUp(self):\n        self.env = child_env()\n    def t(self):\n        self.env.pop('ORT_DISABLE_TELEMETRY')\n        subprocess.run(['x'], env=self.env)\n"
        self.assertEqual(self.flagged(source), 1)

    def test_flags_a_function_that_calls_the_helper_but_returns_a_plain_dict(self) -> None:
        source = IMPORT + "def make():\n    child_env()\n    return {'A': '1'}\nsubprocess.run(['x'], env=make())\n"
        self.assertEqual(self.flagged(source), 1)
        source = IMPORT + "def make(a):\n    if a:\n        return child_env()\n    return {}\nsubprocess.run(['x'], env=make(1))\n"
        self.assertEqual(self.flagged(source), 1)
        source = IMPORT + "def make():\n    def inner():\n        return {}\n    return child_env()\nsubprocess.run(['x'], env=make())\n"
        self.assertEqual(self.flagged(source), 0)  # a nested function's return is not make's

    def test_flags_a_local_fake_helper(self) -> None:
        fakes = (
            "def child_env(*a, **k):\n    return {}\n",
            "child_env = lambda *a, **k: {}\n",
            "from os import environ as child_env\n",
            "from other import child_env\n",
            "import subproc_env\ndef child_env():\n    return {}\n",
            "from subproc_env import child_env\nclass child_env:\n    pass\n",
            "from subproc_env import child_env\ndef g(child_env):\n    pass\n",
            "from subproc_env import child_env\ntry:\n    pass\nexcept Exception as child_env:\n    pass\n",
        )
        for fake in fakes:
            self.assertEqual(self.flagged("import subprocess\n" + fake + "subprocess.run(['x'], env=child_env())\n"), 1, fake)
        self.assertEqual(self.flagged("import subprocess\nsubprocess.run(['x'], env=child_env())\n"), 1)  # never imported
        self.assertEqual(self.flagged("import subprocess\nimport other as subproc_env\nsubprocess.run(['x'], env=subproc_env.child_env())\n"), 1)

    def test_flags_when_a_same_named_method_is_defined_twice(self) -> None:
        good = "    def _env(self):\n        return child_env()\n"
        bad = "    def _env(self):\n        return {}\n"
        call = "    def t(self):\n        subprocess.run(['x'], env=self._env())\n"
        for order in ((good, bad), (bad, good)):
            self.assertEqual(self.flagged(IMPORT + "class T:\n" + "".join(order) + call), 1)
        self.assertEqual(self.flagged(IMPORT + "class T:\n" + good + good + call), 0)

    def test_script_comment_or_other_function_does_not_exempt_the_file(self) -> None:
        source = "import subprocess\n# ORT_DISABLE_TELEMETRY=1 is set elsewhere\ndef f():\n    subprocess.run(['x'], env={})\n"
        self.assertEqual(self.flagged(source, scripts=True), 1)
        source = "import subprocess\ndef g():\n    return {'ORT_DISABLE_TELEMETRY': '1'}\ndef f():\n    subprocess.run(['x'], env={})\n"
        self.assertEqual(self.flagged(source, scripts=True), 1)

    def test_script_env_must_set_the_flag_for_that_call(self) -> None:
        sets = "import subprocess, os\ndef f():\n    env = dict(os.environ)\n    env['ORT_DISABLE_TELEMETRY'] = '1'\n    subprocess.Popen(['x'], env=env)\n"
        self.assertEqual(self.flagged(sets, scripts=True), 0)
        late = "import subprocess, os\ndef f():\n    env = dict(os.environ)\n    subprocess.Popen(['x'], env=env)\n    env['ORT_DISABLE_TELEMETRY'] = '1'\n"
        self.assertEqual(self.flagged(late, scripts=True), 1)
        reset = "import subprocess, os\ndef f():\n    env = dict(os.environ)\n    env['ORT_DISABLE_TELEMETRY'] = '1'\n    env = dict(os.environ)\n    subprocess.Popen(['x'], env=env)\n"
        self.assertEqual(self.flagged(reset, scripts=True), 1)
        wrong = "import subprocess, os\ndef f():\n    env = dict(os.environ)\n    env['ORT_DISABLE_TELEMETRY'] = '0'\n    subprocess.Popen(['x'], env=env)\n"
        self.assertEqual(self.flagged(wrong, scripts=True), 1)
        named = "import subprocess, os\ndef f():\n    env = {**os.environ, 'ORT_DISABLE_TELEMETRY': '1'}\n    subprocess.Popen(['x'], env=env)\n"
        self.assertEqual(self.flagged(named, scripts=True), 0)
        self.assertEqual(self.flagged(named.replace("    subprocess", "    env.clear()\n    subprocess"), scripts=True), 1)
        early = sets.replace("    env['ORT", "    env.update(B='2')\n    env['ORT")
        self.assertEqual(self.flagged(early, scripts=True), 0)  # a write before the final set is overwritten by it
        undone = sets.replace("    subprocess.Popen", "    env.pop('ORT_DISABLE_TELEMETRY')\n    subprocess.Popen")
        self.assertEqual(self.flagged(undone, scripts=True), 1)

    def test_script_loop_key_over_literals_is_not_a_flag_write(self) -> None:
        head = "import subprocess, os\ndef f(names):\n    env = os.environ.copy()\n    env['ORT_DISABLE_TELEMETRY'] = '1'\n"
        tail = "    subprocess.Popen(['x'], env=env)\n"
        self.assertEqual(self.flagged(head + "    for n in ('A', 'B'):\n        env[n] = '1'\n" + tail, scripts=True), 0)
        self.assertEqual(self.flagged(head + "    for n in names:\n        env[n] = '1'\n" + tail, scripts=True), 1)
        self.assertEqual(self.flagged(head + "    for n in ('ORT_DISABLE_TELEMETRY',):\n        env[n] = '0'\n" + tail, scripts=True), 1)

    def test_script_dict_displays_must_end_with_the_flag(self) -> None:
        ok = "import subprocess, os\nsubprocess.run(['x'], env={**os.environ, 'ORT_DISABLE_TELEMETRY': '1'})\n"
        self.assertEqual(self.flagged(ok, scripts=True), 0)
        spread_last = "import subprocess, os\nsubprocess.run(['x'], env={'ORT_DISABLE_TELEMETRY': '1', **os.environ})\n"
        self.assertEqual(self.flagged(spread_last, scripts=True), 1)
        self.assertEqual(self.flagged("import subprocess, os\nsubprocess.run(['x'], env=dict(os.environ, ORT_DISABLE_TELEMETRY='1'))\n", scripts=True), 0)


class HelperTests(unittest.TestCase):
    def test_child_env_always_sets_the_flag_and_scratch_dirs(self) -> None:
        import tempfile

        env = subproc_env.child_env({"ORT_DISABLE_TELEMETRY": "0", "HOME": "/real"}, ORT_DISABLE_TELEMETRY="0")
        self.assertEqual(env["ORT_DISABLE_TELEMETRY"], "1")
        temp = Path(tempfile.gettempdir()).resolve()
        for key in ("HOME", "XDG_CACHE_HOME"):
            path = Path(env[key])
            self.assertTrue(path.is_dir())
            self.assertIn(temp, path.resolve().parents)
        self.assertEqual(set(subproc_env.child_env()), {"PATH", "HOME", "XDG_CACHE_HOME", "ORT_DISABLE_TELEMETRY"})
        kept = subproc_env.child_env({"XDG_CACHE_HOME": "/placed"}, keep=("XDG_CACHE_HOME",))
        self.assertEqual(kept["XDG_CACHE_HOME"], "/placed")


if __name__ == "__main__":
    unittest.main()
