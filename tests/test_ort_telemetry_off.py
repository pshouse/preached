"""ONNX Runtime's Microsoft telemetry stays off.

onnxruntime 1.31.1 (observed) writes a device ID and an event DB under
$XDG_CACHE_HOME/Microsoft/DeveloperTools/ at `import onnxruntime`, unless
ORT_DISABLE_TELEMETRY=1 is set first. The checks run in a fresh interpreter
because ORT reads the variable once, at import.
"""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HAVE_ORT = importlib.util.find_spec("onnxruntime") is not None


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _field(number: int, payload: bytes) -> bytes:
    return _varint(number << 3 | 2) + _varint(len(payload)) + payload


def _int(number: int, value: int) -> bytes:
    return _varint(number << 3) + _varint(value)


def _identity_model() -> bytes:
    """ModelProto: Identity on a float[1] input."""
    dim = _field(1, _int(1, 1))
    tensor = _field(1, _int(1, 1) + _field(2, dim))
    info = lambda name: _field(1, name) + _field(2, tensor)  # noqa: E731
    node = _field(1, b"x") + _field(2, b"y") + _field(4, b"Identity")
    graph = _field(1, node) + _field(2, b"g") + _field(11, info(b"x")) + _field(12, info(b"y"))
    return _int(1, 8) + _field(8, _int(2, 13)) + _field(7, graph)


def _child(first_import: str) -> str:
    # -I ignores PYTHONPATH, so the checkout's src is put on sys.path by hand.
    return f"""
import sys
sys.path.insert(0, sys.argv[2])
{first_import}
import onnxruntime as ort
session = ort.InferenceSession(sys.argv[1], providers=["CPUExecutionProvider"])
assert session.get_inputs()[0].name == "x"
"""


@unittest.skipUnless(HAVE_ORT, "onnxruntime is not installed")
class OrtTelemetryTests(unittest.TestCase):
    def _run(self, first_import: str, inherited: str | None) -> list[Path]:
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp).resolve()
            model = scratch / "identity.onnx"
            model.write_bytes(_identity_model())
            env = {
                key: value
                for key, value in os.environ.items()
                if key not in ("ORT_DISABLE_TELEMETRY", "XDG_CACHE_HOME", "HOME", "PYTHONPATH")
            }
            if inherited is not None:
                env["ORT_DISABLE_TELEMETRY"] = inherited
            env.update(HOME=str(scratch / "home"), XDG_CACHE_HOME=str(scratch / "xdg"))
            (scratch / "home").mkdir()
            (scratch / "xdg").mkdir()
            done = subprocess.run(
                [sys.executable, "-I", "-c", _child(first_import), str(model), str(ROOT / "src")],
                env=env,
                cwd=scratch,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            return [
                p.relative_to(scratch)
                for p in scratch.rglob("*")
                if p.name in ("DeveloperTools", "Microsoft", "onnxruntime.db", "deviceid")
            ]

    def test_onnx_embed_import_then_session_writes_nothing(self) -> None:
        self.assertEqual(self._run("from preached import onnx_embed", None), [])

    def test_inherited_zero_is_overridden(self) -> None:
        self.assertEqual(self._run("from preached import onnx_embed", "0"), [])

    def test_other_submodule_then_onnxruntime_writes_nothing(self) -> None:
        # scripts/export_onnx.py imports preached.* first, then onnxruntime.
        self.assertEqual(self._run("import preached.models", None), [])
        self.assertEqual(self._run("import preached.models", "0"), [])



class ServeShTests(unittest.TestCase):
    def test_serve_sh_exports_and_passes_the_variable(self) -> None:
        text = (ROOT / "scripts" / "serve.sh").read_text(encoding="utf-8")
        self.assertIn("\nORT_DISABLE_TELEMETRY=1\n", text)
        self.assertIn("\npass ORT_DISABLE_TELEMETRY\n", text)


if __name__ == "__main__":
    unittest.main()
