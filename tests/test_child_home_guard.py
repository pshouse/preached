"""A real-model child must not write ORT telemetry under its HOME.

The 23:38 onnxruntime.db write came from ``test_shutdown._env``: an allow-list
env that kept the real HOME and dropped ORT_DISABLE_TELEMETRY and
XDG_CACHE_HOME, so the hybrid server child wrote $HOME/.cache/Microsoft. It
only happens with a real index and ONNX model, so these tests need both.

Rule 5 forbids pointing PREACHED_CACHE at a real cache. PREACHED_GUARD_REAL_SRC
must be a read-only bind mount or a pre-made copy of a cache root, never a
writable live cache. The tests only byte-copy index/wesley.sqlite and the fp32
export into a temp directory and use the copy; they never open the source in
place. tests/README.md says the same ("a read-only copy or bind mount").

The guard refuses a source it cannot trust and skips with the reason: a source
file the test process can write to (unless PREACHED_GUARD_ALLOW_RW_SRC=1), a
non-empty index/wesley.sqlite-wal, or an existing index/wesley.sqlite-journal.
Only the main db file is copied, so committed WAL frames would silently be
missing from the copy. Without the variable, or without the files, the tests
skip and say why.
"""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import http.client
import importlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_pkg = "tests." if __package__ else ""
test_shutdown = importlib.import_module(_pkg + "test_shutdown")
subproc_env = importlib.import_module(_pkg + "subproc_env")

ROOT = Path(__file__).resolve().parent.parent
SRC_ENV = "PREACHED_GUARD_REAL_SRC"
_SRC = os.environ.get(SRC_ENV)
_REV = test_shutdown.GRANITE_REVISION
_NAMES = test_shutdown._fp32_export_names()


ALLOW_RW_ENV = "PREACHED_GUARD_ALLOW_RW_SRC"


def _source_files(root: Path) -> list[Path]:
    folder = root / "models" / "granite-english-r2-onnx" / _REV
    return [root / "index" / "wesley.sqlite", *(folder / name for name in _NAMES)]


def _skip_reason_for(src: str | None, environ=os.environ) -> str | None:
    if not src:
        return f"{SRC_ENV} is not set: no real index and ONNX model to copy (rule 5 forbids using a real cache directly)"
    root = Path(src)
    if not (root / "index" / "wesley.sqlite").is_file():
        return f"{SRC_ENV}={src} has no index/wesley.sqlite"
    folder = root / "models" / "granite-english-r2-onnx" / _REV
    missing = [name for name in _NAMES if not (folder / name).is_file()]
    if missing:
        return f"{SRC_ENV}={src} lacks {missing} under models/granite-english-r2-onnx/{_REV}"
    db = root / "index" / "wesley.sqlite"
    wal = db.with_name(db.name + "-wal")
    if wal.exists() and wal.stat().st_size > 0:
        return f"{SRC_ENV}={src} has a non-empty {wal.name}: only the main db is copied, so committed WAL frames would be missing"
    journal = db.with_name(db.name + "-journal")
    if journal.exists():
        return f"{SRC_ENV}={src} has a {journal.name}: the db may be mid-transaction"
    if environ.get(ALLOW_RW_ENV) != "1":
        writable = [str(p.relative_to(root)) for p in _source_files(root) if os.access(p, os.W_OK)]
        if writable:
            return (
                f"{SRC_ENV}={src} is writable by this process ({writable[0]}"
                f"{' and others' if len(writable) > 1 else ''}): use a read-only bind mount or copy, or set {ALLOW_RW_ENV}=1"
            )
    return None


def _skip_reason() -> str | None:
    return _skip_reason_for(_SRC)


def microsoft_dirs(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_dir() and p.name in ("Microsoft", "DeveloperTools"))


@unittest.skipIf(_skip_reason() is not None, _skip_reason() or "")
class RealModelChildHomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cache = Path(tempfile.mkdtemp(prefix="preached-homeguard-")).resolve()
        assert Path(tempfile.gettempdir()).resolve() in cls.cache.parents
        src = Path(_SRC)
        (cls.cache / "index").mkdir()
        shutil.copyfile(src / "index" / "wesley.sqlite", cls.cache / "index" / "wesley.sqlite")
        cls.onnx = cls.cache / "models" / "granite-english-r2-onnx"
        (cls.onnx / _REV).mkdir(parents=True)
        for name in _NAMES:
            shutil.copyfile(src / "models" / "granite-english-r2-onnx" / _REV / name, cls.onnx / _REV / name)

    @classmethod
    def tearDownClass(cls) -> None:
        if Path(tempfile.gettempdir()).resolve() in cls.cache.parents:
            shutil.rmtree(cls.cache, ignore_errors=True)

    def _shutdown_child(self, wrap) -> tuple[list[Path], int]:
        """Start the hybrid server as test_shutdown does, search once, SIGTERM.

        ``wrap`` takes the env test_shutdown built and returns the one used.
        Returns the HOME and XDG_CACHE_HOME dirs the child had, and its exit code.
        """
        seen: list[dict] = []

        def spy(base=None, /, **extra):
            env = wrap(subproc_env.child_env(base, **extra))
            seen.append(env)
            return env

        overrides = {"PREACHED_CACHE": str(self.cache), "PREACHED_ONNX_DIR": str(self.onnx)}
        with patch.dict(os.environ, overrides), patch.object(test_shutdown, "child_env", spy):
            with tempfile.TemporaryDirectory() as tmp:
                server = test_shutdown._Server(tmp, ["--index", str(self.cache / "index" / "wesley.sqlite")])
                self.assertIsNotNone(server.port, "server did not start")
                conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=120)
                conn.request("GET", "/api/search?q=grace+faith&mode=hybrid&k=5")
                response = conn.getresponse()
                body = response.read().decode()
                conn.close()
                self.assertEqual(response.status, 200)
                self.assertIn('"mode": "hybrid"', body.replace('":"', '": "'), "server fell back to BM25")
                rc, err = server.stop()
        self.assertEqual(rc, 0, err[-800:])
        env = seen[-1]
        return [Path(env[key]) for key in ("HOME", "XDG_CACHE_HOME") if key in env], rc

    def test_shutdown_child_in_a_fresh_home_writes_no_microsoft_dir(self) -> None:
        homes, _ = self._shutdown_child(lambda env: env)
        for home in homes:
            self.assertTrue(home.is_dir())
            self.assertEqual(microsoft_dirs(home), [], f"telemetry wrote under {home}")

    def test_guard_sees_a_telemetry_write(self) -> None:
        """Red check: the old allow-list shape (no flag, no XDG_CACHE_HOME) leaves a Microsoft dir."""
        with tempfile.TemporaryDirectory() as home:
            env = subproc_env.child_env(HOME=home, PYTHONPATH=str(ROOT / "src"))
            env.pop("ORT_DISABLE_TELEMETRY")
            env.pop("XDG_CACHE_HOME")
            # Import onnxruntime first: preached would turn the flag back on.
            subprocess.run([test_shutdown._python(), "-c", "import onnxruntime"], env=env, check=True, timeout=120)
            self.assertNotEqual(microsoft_dirs(Path(home)), [])

    def test_child_importing_onnxruntime_before_preached_writes_no_microsoft_dir(self) -> None:
        model = self.onnx / _REV / "model.fp32.onnx"
        code = (
            "import onnxruntime as ort\n"
            "import preached\n"
            f"ort.InferenceSession({str(model)!r}, providers=['CPUExecutionProvider'])\n"
        )
        env = subproc_env.child_env(PYTHONPATH=str(ROOT / "src"))
        subprocess.run([test_shutdown._python(), "-c", code], cwd=ROOT, env=env, check=True, timeout=300)
        for key in ("HOME", "XDG_CACHE_HOME"):
            self.assertEqual(microsoft_dirs(Path(env[key])), [])


class SourceRefusalTests(unittest.TestCase):
    """The source checks run on a fake cache root in a temp dir, so they need no real model."""

    def _root(self) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="preached-homeguard-src-")).resolve()
        assert Path(tempfile.gettempdir()).resolve() in tmp.parents
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "index").mkdir()
        (tmp / "index" / "wesley.sqlite").write_bytes(b"db")
        folder = tmp / "models" / "granite-english-r2-onnx" / _REV
        folder.mkdir(parents=True)
        for name in _NAMES:
            (folder / name).write_bytes(b"x")
        for path in _source_files(tmp):
            path.chmod(0o444)
        # Directories stay writable so cleanup works; the files are what the guard checks.
        return tmp

    def test_read_only_source_is_accepted(self) -> None:
        root = self._root()
        if os.access(root / "index" / "wesley.sqlite", os.W_OK):
            self.skipTest("this process can write to 0444 files (running as root)")
        self.assertIsNone(_skip_reason_for(str(root), {}))

    def test_writable_source_is_refused_unless_allowed(self) -> None:
        root = self._root()
        (root / "index" / "wesley.sqlite").chmod(0o644)
        reason = _skip_reason_for(str(root), {})
        self.assertIsNotNone(reason)
        self.assertIn("writable", reason)
        self.assertIn(ALLOW_RW_ENV, reason)
        self.assertIsNone(_skip_reason_for(str(root), {ALLOW_RW_ENV: "1"}))

    def test_non_empty_wal_is_refused_even_when_rw_is_allowed(self) -> None:
        root = self._root()
        (root / "index" / "wesley.sqlite-wal").write_bytes(b"frames")
        reason = _skip_reason_for(str(root), {ALLOW_RW_ENV: "1"})
        self.assertIsNotNone(reason)
        self.assertIn("-wal", reason)

    def test_empty_wal_is_not_a_refusal(self) -> None:
        root = self._root()
        (root / "index" / "wesley.sqlite-wal").write_bytes(b"")
        self.assertIsNone(_skip_reason_for(str(root), {ALLOW_RW_ENV: "1"}))

    def test_existing_journal_is_refused_even_when_rw_is_allowed(self) -> None:
        root = self._root()
        (root / "index" / "wesley.sqlite-journal").write_bytes(b"")
        reason = _skip_reason_for(str(root), {ALLOW_RW_ENV: "1"})
        self.assertIsNotNone(reason)
        self.assertIn("-journal", reason)


if __name__ == "__main__":
    unittest.main()
