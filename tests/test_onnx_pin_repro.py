"""The repo's export reproduces the pinned graph, and the pin still bites.

docs/adr/0001-onnx-export-determinism.md has the cause: the exported bytes
follow torch's ATen CPU dispatch level and the order ModernBERT traces its
two rotary tables (``set(config.layer_types)``, so PYTHONHASHSEED). The
exporter fixes both: ATEN_CPU_CAPABILITY=avx2 before torch is imported, and a
restart under EXPORT_HASHSEED whatever the caller's seed.

ExportIsByteIdenticalTests runs the real exporter three times (about a minute
each on CPU). It skips only when the Granite weights are not in
PREACHED_CACHE.
"""

from __future__ import annotations

import filecmp
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
    GRANITE_MODEL_KEY,
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
        from app.server import MISSING_GRAPH_NOTE, UNAVAILABLE_LOG

        with tempfile.TemporaryDirectory() as tmp:
            encode, note, text = self._load(Path(tmp), Path(tmp) / "index.sqlite")
        self.assertIsNone(encode)
        self.assertEqual(note, MISSING_GRAPH_NOTE)
        # The runbook's D2 page still matches.
        self.assertIn(f"ERROR:root:{UNAVAILABLE_LOG}", text.splitlines())
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


class HealthzSearchModeTests(unittest.TestCase):
    """/healthz says which search is live and, when it is BM25, why."""

    def _app(self, *, loader=None, bm25_only=False):
        from app.server import STATIC_DIR, build_app
        from test_server import build_rich_index, reopen

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        index = Path(tmp.name) / "rich.sqlite"
        build_rich_index(index)
        app = build_app(
            reopen(index),
            model_key=GRANITE_MODEL_KEY,
            bm25_only=bm25_only,
            hosts={"127.0.0.1"},
            static_dir=STATIC_DIR,
            loader=loader,
        )
        self.addCleanup(app.connection.close)
        return app

    def test_a_missing_graph_shows_as_bm25_with_its_reason(self) -> None:
        def loader(_connection, _model_key):
            raise ArtifactMissing(f"missing ONNX manifest at /x/manifest.json; build it with: {EXPORT_COMMAND}")

        with self.assertLogs(level="ERROR"):
            health = self._app(loader=loader).health()
        self.assertEqual(health["search_mode"], "bm25")
        self.assertEqual(health["search_mode_reason"], "onnx_graph_not_built")
        self.assertTrue(health["fallback"])
        # A code, not the path or the command.
        self.assertNotIn("/x/", json.dumps(health))

    def test_another_load_failure_has_its_own_reason(self) -> None:
        def loader(_connection, _model_key):
            raise RuntimeError("boom")

        with self.assertLogs(level="ERROR"):
            health = self._app(loader=loader).health()
        self.assertEqual((health["search_mode"], health["search_mode_reason"]), ("bm25", "model_unavailable"))

    def test_bm25_by_request_and_hybrid(self) -> None:
        from preached.search import Searcher
        from test_server import FIXTURE_FP, encode_fixture

        health = self._app(bm25_only=True).health()
        self.assertEqual((health["search_mode"], health["search_mode_reason"]), ("bm25", "bm25_only"))

        def loader(connection, _model_key):
            return Searcher(connection, model="fixture", fingerprint=FIXTURE_FP), encode_fixture

        health = self._app(loader=loader).health()
        self.assertEqual((health["search_mode"], health["search_mode_reason"]), ("hybrid", None))


def _load_exporter(name: str = "export_onnx_probe"):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "export_onnx.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Avx2GuardTests(unittest.TestCase):
    """scripts/export_onnx.py pins the dispatch level and refuses hosts without it."""

    def test_the_dispatch_level_is_set_before_torch_is_imported(self) -> None:
        code = (
            "import os, sys\n"
            f"sys.path.insert(0, {str(ROOT / 'scripts')!r})\n"
            "import export_onnx\n"
            "print(os.environ['ATEN_CPU_CAPABILITY'], 'torch' in sys.modules)\n"
        )
        env = dict(os.environ, ATEN_CPU_CAPABILITY="default")
        result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ["avx2", "False"])

    def test_a_host_that_is_not_x86_64_is_refused(self) -> None:
        exporter = _load_exporter()
        with self.assertRaisesRegex(SystemExit, "x86-64 host with AVX2.*aarch64"):
            exporter._require_avx2("aarch64")

    def test_an_x86_64_cpu_without_avx2_is_refused(self) -> None:
        exporter = _load_exporter()
        with tempfile.TemporaryDirectory() as tmp:
            cpuinfo = Path(tmp) / "cpuinfo"
            cpuinfo.write_text("processor\t: 0\nflags\t\t: fpu sse sse2 avx\n")
            with self.assertRaisesRegex(SystemExit, "does not report avx2"):
                exporter._require_avx2("x86_64", cpuinfo)
            cpuinfo.write_text("processor\t: 0\nflags\t\t: fpu sse sse2 avx avx2\n")
            exporter._require_avx2("x86_64", cpuinfo)
            with self.assertRaisesRegex(SystemExit, "cannot read"):
                exporter._require_avx2("x86_64", Path(tmp) / "missing")

    def test_the_script_exits_non_zero_on_a_refused_host(self) -> None:
        code = (
            "import runpy, platform\n"
            "platform.machine = lambda: 'arm64'\n"
            f"runpy.run_path({str(ROOT / 'scripts' / 'export_onnx.py')!r}, run_name='__main__')\n"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("export needs an x86-64 host with AVX2", result.stderr)


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
        exporter = _load_exporter()
        self.assertEqual(exporter.PINNED_TRACE_ORDER, ["sliding_attention", "full_attention"])
        result = self._check(exporter.EXPORT_HASHSEED)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)

    def test_another_seed_is_refused_before_export(self) -> None:
        # Seed 0 iterates full_attention first on CPython 3.12.
        result = self._check("0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("would not match the pinned graph", result.stderr)


class HashSeedReexecTests(unittest.TestCase):
    """scripts/export_onnx.py restarts under EXPORT_HASHSEED whatever the caller's seed."""

    def _reexec(self, ambient: str | None, *flags: str) -> list[str]:
        # os.execv is replaced, so the restart is recorded instead of run.
        code = (
            "import os, sys\n"
            f"sys.path.insert(0, {str(ROOT / 'scripts')!r})\n"
            "import export_onnx\n"
            "def execv(path, argv):\n"
            "    print('EXEC', os.environ['PYTHONHASHSEED'], path == sys.executable, argv[1:])\n"
            "    raise SystemExit(0)\n"
            "os.execv = execv\n"
            "export_onnx._reexec_with_hashseed()\n"
            "print('NOEXEC', os.environ['PYTHONHASHSEED'])\n"
        )
        env = dict(os.environ)
        env.pop("PYTHONHASHSEED", None)
        if ambient is not None:
            env["PYTHONHASHSEED"] = ambient
        result = subprocess.run(
            [sys.executable, *flags, "-c", code], env=env, capture_output=True, text=True, timeout=60
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.split()

    def test_any_other_ambient_seed_restarts_under_the_export_seed(self) -> None:
        exporter = _load_exporter()
        script = str((ROOT / "scripts" / "export_onnx.py").resolve())
        for ambient in (None, "random", "0", "2", "3", "4", "5"):
            with self.subTest(ambient=ambient):
                out = self._reexec(ambient)
                self.assertEqual(out[:3], ["EXEC", exporter.EXPORT_HASHSEED, "True"])
                self.assertIn(script, " ".join(out[3:]))

    def test_the_export_seed_does_not_restart(self) -> None:
        exporter = _load_exporter()
        self.assertEqual(self._reexec(exporter.EXPORT_HASHSEED), ["NOEXEC", exporter.EXPORT_HASHSEED])

    def test_dash_r_under_the_export_seed_does_not_restart(self) -> None:
        # A numeric PYTHONHASHSEED wins over -R, so the seed is still fixed.
        # (sys.flags.hash_randomization reads 1 under seed 1: testing it
        # would restart forever.)
        exporter = _load_exporter()
        self.assertEqual(self._reexec(exporter.EXPORT_HASHSEED, "-R")[:2], ["NOEXEC", exporter.EXPORT_HASHSEED])

SNAPSHOT = (
    CACHE / "huggingface" / "hub" / "models--ibm-granite--granite-embedding-english-r2" / "snapshots" / GRANITE_REVISION
)


def _export_command() -> list[str]:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        return ["uv", "run", "--group", "bench", "python"]
    return [sys.executable]


@unittest.skipUnless(
    (SNAPSHOT / "model.safetensors").is_file(),
    f"Granite weights are not in PREACHED_CACHE ({SNAPSHOT})",
)
class ExportIsByteIdenticalTests(unittest.TestCase):
    def test_exports_under_any_ambient_seed_are_byte_identical_and_are_the_pin(self) -> None:
        with tempfile.TemporaryDirectory(dir=CACHE, prefix="export-repro-") as tmp:
            manifests = []
            # The runs start under different ambient hash seeds (unset, 0, 3)
            # and dispatch levels. Unfixed, seed 0 traces the other rotary
            # order and default dispatch changes the bytes again; avx512 is an
            # AVX512 host's native level (on a CPU without AVX512 torch does
            # not clamp it; the export dies with SIGILL). The script must
            # override both and write the pin every time.
            for name, start in (
                ("a", {"ATEN_CPU_CAPABILITY": "default"}),
                ("b", {"PYTHONHASHSEED": "0", "ATEN_CPU_CAPABILITY": "avx2"}),
                ("c", {"PYTHONHASHSEED": "3", "ATEN_CPU_CAPABILITY": "avx512"}),
            ):
                out = Path(tmp) / name
                env = {k: v for k, v in os.environ.items() if k != "PYTHONHASHSEED"}
                env.update(
                    PREACHED_ONNX_DIR=str(out),
                    CUDA_VISIBLE_DEVICES="",
                    HF_HOME=str(CACHE / "huggingface"),
                    HUGGINGFACE_HUB_CACHE=str(CACHE / "huggingface" / "hub"),
                    HF_HUB_OFFLINE="1",
                    **start,
                )
                result = subprocess.run(
                    [*_export_command(), str(ROOT / "scripts" / "export_onnx.py")],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=1800,
                )
                self.assertEqual(result.returncode, 0, result.stderr[-4000:])
                folder = out / GRANITE_REVISION
                self.assertEqual(sha256_file(folder / "tokenizer.json"), TOKENIZER_SHA256)
                verify_manifest(folder, variant="fp32")
                manifests.append((folder / "manifest.json").read_text())
            first, *rest = (Path(tmp) / name / GRANITE_REVISION / "model.fp32.onnx" for name in "abc")
            for other in rest:
                self.assertTrue(filecmp.cmp(first, other, shallow=False), f"{other.parent.parent.name} differs")
            self.assertEqual(sha256_file(first), FP32_ONNX_SHA256)
            # The manifest carries every file's sha256, int8 included.
            self.assertEqual(manifests[0], manifests[1])
            self.assertEqual(manifests[0], manifests[2])

if __name__ == "__main__":
    logging.basicConfig()
    unittest.main()
