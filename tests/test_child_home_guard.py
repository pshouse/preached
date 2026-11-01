"""A real-model child must not write ORT telemetry under its HOME.

The 23:38 onnxruntime.db write came from ``test_shutdown._env``: an allow-list
env that kept the real HOME and dropped ORT_DISABLE_TELEMETRY and
XDG_CACHE_HOME, so the hybrid server child wrote $HOME/.cache/Microsoft. It
only happens with a real index and ONNX model, so these tests need both.

Rule 5 forbids pointing PREACHED_CACHE at a real cache. Set
PREACHED_GUARD_REAL_SRC to a cache root (for example a read-only bind mount);
the tests copy only the Wesley index and the pinned fp32 export from it into a
temp directory and use the copy. Without it, or without those files, the tests
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


def _skip_reason() -> str | None:
    if not _SRC:
        return f"{SRC_ENV} is not set: no real index and ONNX model to copy (rule 5 forbids using a real cache directly)"
    root = Path(_SRC)
    if not (root / "index" / "wesley.sqlite").is_file():
        return f"{SRC_ENV}={_SRC} has no index/wesley.sqlite"
    folder = root / "models" / "granite-english-r2-onnx" / _REV
    missing = [name for name in _NAMES if not (folder / name).is_file()]
    if missing:
        return f"{SRC_ENV}={_SRC} lacks {missing} under models/granite-english-r2-onnx/{_REV}"
    return None


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


if __name__ == "__main__":
    unittest.main()
