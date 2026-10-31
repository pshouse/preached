"""The repo's export reproduces the pinned graph, and the pin still bites.

reports/W4-ONNX-PIN-REPRO.md has the cause: ModernBERT traces its two
rotary tables in ``set(config.layer_types)`` order, which follows
PYTHONHASHSEED. The exporter fixes the seed.

The full export test is slow (two exports, about a minute each on CPU) and
needs the bench group and the Hugging Face snapshot. Run it with:

  PREACHED_TEST_EXPORT=1 uv run --group bench python -m unittest tests.test_onnx_pin_repro
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from preached.artifacts import (
    EXPORT_COMMAND,
    FP32_ONNX_SHA256,
    GRANITE_HF_ID,
    GRANITE_REVISION,
    TOKENIZER_SHA256,
    ArtifactError,
    ArtifactMissing,
    artifact_dir,
    sha256_file,
    verify_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(os.environ.get("PREACHED_CACHE", "/cache"))
# Granite R2's pattern: one full layer, then two sliding.
LAYER_TYPES = ["full_attention", "sliding_attention", "sliding_attention"] * 7 + ["full_attention"]


def _manifest(folder: Path, files: dict[str, dict]) -> None:
    payload = {
        "hf_id": GRANITE_HF_ID,
        "revision": GRANITE_REVISION,
        "pooling": "cls",
        "normalize": "l2",
        "max_seq_length": 8192,
        "hidden_size": 768,
        "default_variant": "fp32",
        "variants": {"fp32": "model.fp32.onnx", "int8": "model.int8.onnx"},
        "files": files,
    }
    (folder / "manifest.json").write_text(json.dumps(payload))


def _seed_granite(path: Path):
    """An index whose fingerprint matches, so load fails on the artifact."""
    import numpy as np

    from preached.models import MODELS
    from preached.store import connect, save_embedding_info, write_embeddings

    spec = MODELS["granite-english-r2"]
    connection = connect(path)
    write_embeddings(connection, spec.key, [1], np.zeros((1, 768), dtype=np.float32))
    save_embedding_info(connection, spec.key, {"fingerprint": spec.fingerprint(), "backend": "onnx"})
    return connection


class _OnnxDir:
    def __init__(self, path: Path) -> None:
        self.path = str(path)

    def __enter__(self):
        self.previous = os.environ.get("PREACHED_ONNX_DIR")
        os.environ["PREACHED_ONNX_DIR"] = self.path

    def __exit__(self, *exc):
        if self.previous is None:
            os.environ.pop("PREACHED_ONNX_DIR", None)
        else:
            os.environ["PREACHED_ONNX_DIR"] = self.previous


class MissingGraphMessageTests(unittest.TestCase):
    """app/server.py load_search, run by build_app at startup."""

    def _load(self, onnx_dir: Path, index: Path):
        from app.server import load_search

        with _OnnxDir(onnx_dir):
            connection = _seed_granite(index)
            try:
                with self.assertLogs(level="ERROR") as logs:
                    _searcher, encode, note = load_search(
                        connection, "granite-english-r2", embed_backend="onnx"
                    )
            finally:
                connection.close()
        return encode, note, "\n".join(logs.output)

    def test_missing_manifest_names_the_export_step(self) -> None:
        from app.server import FALLBACK_NOTE

        with tempfile.TemporaryDirectory() as tmp:
            encode, note, text = self._load(Path(tmp), Path(tmp) / "index.sqlite")
        self.assertIsNone(encode)
        self.assertEqual(note, FALLBACK_NOTE)
        self.assertIn("ONNX GRAPH NOT BUILT", text)
        self.assertIn("Hybrid search is OFF", text)
        self.assertIn(EXPORT_COMMAND, text)
        self.assertIn(str(Path(tmp) / GRANITE_REVISION / "manifest.json"), text)

    def test_missing_graph_beside_a_manifest_names_the_export_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / GRANITE_REVISION
            folder.mkdir()
            files = {name: {"sha256": "ab" * 32, "bytes": 1} for name in ("model.fp32.onnx", "tokenizer.json", "pooling.json")}
            _manifest(folder, files)
            encode, _note, text = self._load(Path(tmp), Path(tmp) / "index.sqlite")
        self.assertIsNone(encode)
        self.assertIn("ONNX GRAPH NOT BUILT", text)
        self.assertIn(str(folder / "model.fp32.onnx"), text)
        self.assertIn(EXPORT_COMMAND, text)

    def test_present_but_wrong_graph_is_not_called_unbuilt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / GRANITE_REVISION
            folder.mkdir()
            files = {}
            for name in ("model.fp32.onnx", "tokenizer.json", "pooling.json"):
                (folder / name).write_bytes(b"x")
                files[name] = {"sha256": "ab" * 32, "bytes": 1}
            _manifest(folder, files)
            encode, _note, text = self._load(Path(tmp), Path(tmp) / "index.sqlite")
        self.assertIsNone(encode)
        self.assertNotIn("ONNX GRAPH NOT BUILT", text)
        self.assertIn("embedding model unavailable", text)

    def test_missing_is_a_kind_of_artifact_error(self) -> None:
        # Callers that catch ArtifactError (search/query.py) still catch it,
        # and its message carries the step.
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ArtifactMissing) as ctx:
                verify_manifest(Path(tmp))
        self.assertIsInstance(ctx.exception, ArtifactError)
        self.assertIn(EXPORT_COMMAND, str(ctx.exception))


def _first_initializer_value(data: bytes | memoryview) -> int:
    """Offset of the first float in the first raw_data initializer.

    ModelProto.graph (7) -> GraphProto.initializer (5) -> TensorProto.raw_data (9).
    """
    from preached.onnx_embed import _varint

    def fields(start: int, end: int):
        pos = start
        while pos < end:
            key, pos = _varint(data, pos, end)
            field, wire = key >> 3, key & 7
            if wire == 0:
                _value, pos = _varint(data, pos, end)
            elif wire == 2:
                size, pos = _varint(data, pos, end)
                yield field, pos, pos + size
                pos += size
            elif wire == 1:
                pos += 8
            elif wire == 5:
                pos += 4
            else:
                raise AssertionError(f"unexpected wire type {wire}")

    for field, start, end in fields(0, len(data)):
        if field != 7:
            continue
        for gfield, gstart, gend in fields(start, end):
            if gfield != 5:
                continue
            for tfield, tstart, tend in fields(gstart, gend):
                if tfield == 9 and tend - tstart >= 4:
                    return tstart
    raise AssertionError("no raw_data initializer found")


class MutantGraphTests(unittest.TestCase):
    def test_one_flipped_initializer_value_is_refused(self) -> None:
        source = artifact_dir()
        if not (source / "model.fp32.onnx").is_file():
            self.skipTest("granite onnx artifacts are not in /cache")
        if not os.access(source.parent.parent, os.W_OK):
            self.skipTest("model mount is read-only; the test copies the 597 MB graph beside it")
        from preached.onnx_embed import OnnxEmbedder

        with tempfile.TemporaryDirectory(dir=source.parent.parent) as tmp:
            folder = Path(tmp)
            graph = folder / "model.fp32.onnx"
            shutil.copyfile(source / "model.fp32.onnx", graph)
            with graph.open("r+b") as handle:
                import mmap

                with mmap.mmap(handle.fileno(), 0) as view:
                    offset = _first_initializer_value(view)
                    # Flip the low mantissa bit of one float32 weight.
                    view[offset] ^= 0x01
            for name in ("tokenizer.json", "pooling.json"):
                shutil.copyfile(source / name, folder / name)
            manifest = json.loads((source / "manifest.json").read_text())
            mutant_sha = sha256_file(graph)
            self.assertNotEqual(mutant_sha, FP32_ONNX_SHA256)
            # The manifest is rewritten to agree with the mutant, so only the
            # code pin stands between it and the runtime.
            manifest["files"]["model.fp32.onnx"]["sha256"] = mutant_sha
            (folder / "manifest.json").write_text(json.dumps(manifest))
            verify_manifest(folder, variant="fp32", enforce_pins=False)
            with self.assertRaisesRegex(ArtifactError, "not the pinned digest"):
                verify_manifest(folder, variant="fp32")
            with self.assertRaisesRegex(ArtifactError, "not the pinned digest"):
                OnnxEmbedder.load(variant="fp32", directory=folder, ort_threads=1, batch_size=1)


class TraceOrderTests(unittest.TestCase):
    """scripts/export_onnx.py refuses a trace order that is not the pin's."""

    def _check(self, seed: str) -> subprocess.CompletedProcess:
        code = (
            "import sys; from types import SimpleNamespace as N\n"
            f"sys.path.insert(0, {str(ROOT / 'scripts')!r})\n"
            "import export_onnx\n"
            f"export_onnx._check_trace_order(N(config=N(layer_types={LAYER_TYPES!r})))\n"
            "print('ok')\n"
        )
        env = dict(os.environ, PYTHONHASHSEED=seed)
        return subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60
        )

    def test_the_export_seed_gives_the_pinned_order(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("export_onnx_probe", ROOT / "scripts" / "export_onnx.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = self._check(module.EXPORT_HASHSEED)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)

    def test_another_seed_is_refused_before_export(self) -> None:
        result = self._check("0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("would not match the pinned graph", result.stderr)


def _bench_ready() -> str | None:
    if os.environ.get("PREACHED_TEST_EXPORT") != "1":
        return "slow (two full exports); set PREACHED_TEST_EXPORT=1 and use uv run --group bench"
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        return "bench group not installed; run under uv run --group bench"
    return None


@unittest.skipIf(_bench_ready() is not None, _bench_ready() or "")
class ExportReproducesThePinTests(unittest.TestCase):
    def test_two_exports_under_different_seeds_match_each_other_and_the_pin(self) -> None:
        CACHE.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=CACHE, prefix="export-repro-") as tmp:
            manifests = []
            # 0 and 3 traced the other order before the fix.
            for seed in ("0", "3"):
                out = Path(tmp) / f"seed{seed}"
                env = dict(
                    os.environ,
                    PYTHONHASHSEED=seed,
                    PREACHED_ONNX_DIR=str(out),
                    CUDA_VISIBLE_DEVICES="",
                )
                result = subprocess.run(
                    [sys.executable, str(ROOT / "scripts" / "export_onnx.py")],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=1800,
                )
                self.assertEqual(result.returncode, 0, result.stderr[-4000:])
                folder = out / GRANITE_REVISION
                self.assertEqual(sha256_file(folder / "model.fp32.onnx"), FP32_ONNX_SHA256)
                self.assertEqual(sha256_file(folder / "tokenizer.json"), TOKENIZER_SHA256)
                verify_manifest(folder, variant="fp32")
                manifests.append((folder / "manifest.json").read_text())
            self.assertEqual(manifests[0], manifests[1])


if __name__ == "__main__":
    logging.basicConfig()
    unittest.main()
