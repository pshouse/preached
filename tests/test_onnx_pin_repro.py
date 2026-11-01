"""The repo's export reproduces the pinned graph, and the pin still bites.

docs/adr/0001-onnx-export-determinism.md has the cause: the exported bytes
follow torch's ATen CPU dispatch level and the order ModernBERT traces its
two rotary tables (``set(config.layer_types)``, so PYTHONHASHSEED). The
exporter fixes both: ATEN_CPU_CAPABILITY=avx2 before torch is imported, and a
restart under EXPORT_HASHSEED whatever the caller's seed.

ExportIsByteIdenticalTests runs the real exporter three times (about a minute
each on CPU). It skips only when the Granite weights are not in
PREACHED_CACHE, and it only reads them: outputs and the HF cache it uses are
under a TMPDIR temp dir. Every other test here stubs os.execv and the export
itself and points its outputs at temp dirs. ExportMainTests also resolves
every removal, copy, write and mkdir and refuses any outside its temp cache;
the other tests rely on their temp environment alone.
"""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import filecmp
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

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
if __package__:
    from .subproc_env import child_env
else:
    from subproc_env import child_env

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(os.environ.get("PREACHED_CACHE", "/cache"))
# Granite R2's pattern: one full layer, then two sliding.
LAYER_TYPES = ["full_attention", "sliding_attention", "sliding_attention"] * 7 + ["full_attention"]
TEMP_ROOT = Path(tempfile.gettempdir()).resolve()


def _inside_scratch(path: str | os.PathLike, cache: Path) -> Path:
    """Resolve path; raise unless it is under the temp root and the scratch cache.

    Resolved, not lexical: '..' and a symlinked parent can both lead a path
    that reads as $PREACHED_CACHE/... into the real cache.
    """
    resolved = Path(path).resolve()
    scratch = cache.resolve()
    if not (scratch.is_relative_to(TEMP_ROOT) and resolved.is_relative_to(TEMP_ROOT) and resolved.is_relative_to(scratch)):
        raise AssertionError(f"{path} resolves to {resolved}, outside the scratch cache {scratch} under {TEMP_ROOT}")
    return resolved


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
    # The script sets CUDA, dispatch and HF cache variables at import; keep
    # them out of this process's environment.
    with mock.patch.dict(os.environ):
        spec.loader.exec_module(module)
    return module


SCRIPT = ROOT / "scripts" / "export_onnx.py"
# Prepended to subprocess code that runs the script as __main__. os.execv and
# the export are stubbed: execv prints EXEC and its argv tail; main() prints
# MAIN at its first import (torch / huggingface_hub are fakes). Either stub
# exits 0, so nothing is downloaded, exported, or written.
STUBS = (
    "import json, os, sys, runpy, types\n"
    "def execv(path, argv):\n"
    "    print('EXEC', json.dumps(argv[1:]), flush=True)\n"
    "    raise SystemExit(0)\n"
    "os.execv = execv\n"
    "class Stub(types.ModuleType):\n"
    "    def __getattr__(self, name):\n"
    "        print('MAIN', flush=True)\n"
    "        raise SystemExit(0)\n"
    "sys.modules['torch'] = Stub('torch')\n"
    "sys.modules['huggingface_hub'] = Stub('huggingface_hub')\n"
)


def _sandbox_env(tmp: Path, **extra: str) -> dict[str, str]:
    """Scratch caches and ONNX dir under tmp, offline, no hash seed."""
    drop = {"PYTHONHASHSEED", "HF_HOME", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"}
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env.update(
        PREACHED_CACHE=str(tmp / "cache"),
        PREACHED_ONNX_DIR=str(tmp / "onnx"),
        HF_HOME=str(tmp / "hf"),
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
    )
    return child_env(env, **extra)


def _tree(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


class Avx2GuardTests(unittest.TestCase):
    """scripts/export_onnx.py pins the dispatch level and refuses hosts without it."""

    def test_the_dispatch_level_is_set_before_torch_is_imported(self) -> None:
        code = (
            "import os, sys\n"
            f"sys.path.insert(0, {str(ROOT / 'scripts')!r})\n"
            "import export_onnx\n"
            "print(os.environ['ATEN_CPU_CAPABILITY'], 'torch' in sys.modules)\n"
        )
        env = child_env(os.environ, ATEN_CPU_CAPABILITY="default")
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
        # Sandboxed: if __main__ skipped the guard, the stubbed execv (or the
        # stubbed main) would exit 0 and this test would fail without any
        # download, export, or write.
        code = STUBS + (
            "import platform\n"
            "platform.machine = lambda: 'arm64'\n"
            f"runpy.run_path({str(SCRIPT)!r}, run_name='__main__')\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, "-c", code],
                env=_sandbox_env(Path(tmp)),
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(_tree(Path(tmp)), [])
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("export needs an x86-64 host with AVX2", result.stderr)
        self.assertNotIn("EXEC", result.stdout)
        self.assertNotIn("MAIN", result.stdout)


class MainOrderTests(unittest.TestCase):
    """The script's __main__ block: avx2 guard, then the seed restart (argv kept), then main."""

    def _run(self, seed: str | None) -> list[str]:
        code = STUBS + (
            "import pathlib, platform\n"
            "def machine():\n"
            "    print('AVX2', flush=True)\n"
            "    return 'x86_64'\n"
            "platform.machine = machine\n"
            "read_text = pathlib.Path.read_text\n"
            "def fake_read_text(self, *args, **kwargs):\n"
            "    if str(self) == '/proc/cpuinfo':\n"
            "        return 'flags\\t: fpu avx avx2\\n'\n"
            "    return read_text(self, *args, **kwargs)\n"
            "pathlib.Path.read_text = fake_read_text\n"
            f"sys.argv = [{str(SCRIPT)!r}, '--extra-arg', 'x y']\n"
            f"runpy.run_path({str(SCRIPT)!r}, run_name='__main__')\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            extra = {} if seed is None else {"PYTHONHASHSEED": seed}
            result = subprocess.run(
                [sys.executable, "-c", code],
                env=_sandbox_env(Path(tmp), **extra),
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(_tree(Path(tmp)), [])
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.splitlines()

    def test_without_the_seed_it_guards_then_restarts_with_argv(self) -> None:
        for seed in (None, "0", "random"):
            with self.subTest(seed=seed):
                lines = self._run(seed)
                self.assertEqual(lines[0], "AVX2")
                self.assertEqual(lines[1:], ['EXEC ' + json.dumps([str(SCRIPT.resolve()), "--extra-arg", "x y"])])

    def test_under_the_seed_it_guards_then_runs_main(self) -> None:
        self.assertEqual(self._run(_load_exporter().EXPORT_HASHSEED), ["AVX2", "MAIN"])


class ExportMainTests(unittest.TestCase):
    """main() with torch, the Hub and the export stubbed: where it writes, and the pin check."""

    def _main(
        self, cache: Path, *, pin: str | None = None, onnx_dir: str | None = None, export=None
    ) -> tuple[Path, list[tuple[str, str]]]:
        exporter = _load_exporter()
        snapshot = cache.parent / "snapshot"
        (snapshot / "1_Pooling").mkdir(parents=True)
        (snapshot / "1_Pooling" / "config.json").write_text(json.dumps({"pooling_mode_cls_token": True}))
        (snapshot / "sentence_bert_config.json").write_text(json.dumps({"max_seq_length": 8192}))
        (snapshot / "tokenizer.json").write_text("{}")
        torch = SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: False),
            backends=SimpleNamespace(cpu=SimpleNamespace(get_cpu_capability=lambda: "AVX2")),
        )
        hub = SimpleNamespace(snapshot_download=lambda *a, **k: str(snapshot))
        touched: list[tuple[str, str]] = []

        def record(kind, original, target=0):
            # Every removal, copy, write and mkdir must land in the scratch
            # cache once resolved; refuse before acting, not after.
            def wrapper(*args, **kwargs):
                _inside_scratch(args[target], cache)
                touched.append((kind, str(args[target])))
                return original(*args, **kwargs)

            return wrapper

        env = {k: v for k, v in os.environ.items() if k != "PREACHED_ONNX_DIR"}
        env["PREACHED_CACHE"] = str(cache)
        if onnx_dir is not None:
            env["PREACHED_ONNX_DIR"] = onnx_dir
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.dict(sys.modules, {"torch": torch, "huggingface_hub": hub}),
            mock.patch.object(exporter, "_load_encoder", lambda _snapshot: object()),
            mock.patch.object(exporter, "_export", export or (lambda _model, path: path.write_bytes(b"stub graph"))),
            mock.patch.object(exporter, "_check_export", lambda _model, _path: None),
            mock.patch.object(exporter, "_quantize", lambda _src, dst: dst.write_bytes(b"stub int8")),
            mock.patch.object(exporter, "FP32_ONNX_SHA256", pin or FP32_ONNX_SHA256),
            mock.patch.object(shutil, "rmtree", record("rmtree", shutil.rmtree)),
            mock.patch.object(shutil, "copyfile", record("copy", shutil.copyfile, target=1)),
            mock.patch.object(Path, "write_text", autospec=True, side_effect=record("write", Path.write_text)),
            mock.patch.object(Path, "write_bytes", autospec=True, side_effect=record("write", Path.write_bytes)),
            mock.patch.object(Path, "mkdir", autospec=True, side_effect=record("mkdir", Path.mkdir)),
            mock.patch("builtins.print"),
        ):
            folder = artifact_dir()
            # main() removes this directory. Never let it run anywhere but the
            # scratch cache, even when onnx_root is broken (a mutant once let
            # it remove the real /cache export). The check is on the resolved
            # path: a lexical one let '..' and a symlinked models dir through.
            _inside_scratch(folder, cache)
            try:
                exporter.main()
            finally:
                touched = [(kind, path) for kind, path in touched if not path.startswith(str(snapshot))]
        return folder, touched

    def test_a_graph_that_is_not_the_pin_writes_no_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "pc"
            with self.assertRaisesRegex(SystemExit, "is not the pin"):
                self._main(cache)
            folder = cache / "models" / "granite-english-r2-onnx" / GRANITE_REVISION
            self.assertTrue((folder / "model.fp32.onnx").is_file())
            self.assertFalse((folder / "manifest.json").exists())

    def test_a_custom_preached_cache_holds_every_output_and_the_server_reads_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "pc"
            # A stale export is replaced; a neighbour outside the export dir is not touched.
            stale = cache / "models" / "granite-english-r2-onnx" / GRANITE_REVISION / "stale"
            stale.parent.mkdir(parents=True)
            stale.write_text("old")
            neighbour = cache / "models" / "other" / "keep"
            neighbour.parent.mkdir(parents=True)
            neighbour.write_text("keep")
            pin = hashlib.sha256(b"stub graph").hexdigest()
            folder, touched = self._main(cache, pin=pin)
            self.assertEqual(folder, cache / "models" / "granite-english-r2-onnx" / GRANITE_REVISION)
            self.assertFalse(stale.exists())
            self.assertEqual(neighbour.read_text(), "keep")
            self.assertEqual(
                sorted(p.name for p in folder.iterdir()),
                ["manifest.json", "model.fp32.onnx", "model.int8.onnx", "pooling.json", "tokenizer.json"],
            )
            # Every write, mkdir and removal is in the export dir.
            self.assertIn(("rmtree", str(folder)), touched)
            for kind, path in touched:
                with self.subTest(kind=kind, path=path):
                    self.assertTrue(path == str(folder) or path.startswith(str(folder) + os.sep), path)
            # The server's default directory is the same one.
            with mock.patch.dict(os.environ, {"PREACHED_CACHE": str(cache)}):
                os.environ.pop("PREACHED_ONNX_DIR", None)
                self.assertEqual(artifact_dir(), folder)
                verified = verify_manifest(variant="fp32", enforce_pins=False)
            self.assertEqual(verified.manifest["files"]["model.fp32.onnx"]["sha256"], pin)

    def _assert_refused(self, cache: Path, canary: Path, **kwargs) -> None:
        with self.assertRaisesRegex(AssertionError, "outside the scratch cache"):
            self._main(cache, **kwargs)
        self.assertEqual(canary.read_text(), "real")
        self.assertEqual(sorted(p.name for p in canary.parent.iterdir()), ["canary"])

    def _outside(self, tmp: str) -> Path:
        # Stands in for the real cache's export: beside the scratch cache, not in it.
        canary = Path(tmp) / "real" / "models" / "granite-english-r2-onnx" / GRANITE_REVISION / "canary"
        canary.parent.mkdir(parents=True)
        canary.write_text("real")
        return canary

    def test_a_dotdot_export_dir_is_refused_before_main(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "pc"
            cache.mkdir()
            canary = self._outside(tmp)
            # Reads as under the scratch cache; resolves to the stand-in.
            self._assert_refused(cache, canary, onnx_dir=str(cache / ".." / "real" / "models" / "granite-english-r2-onnx"))

    def test_a_symlinked_models_dir_is_refused_before_main(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "pc"
            cache.mkdir()
            canary = self._outside(tmp)
            (cache / "models").symlink_to(canary.parents[2], target_is_directory=True)
            self._assert_refused(cache, canary)

    def test_a_write_that_escapes_inside_main_is_refused(self) -> None:
        # The pre-check passes; a write main() makes elsewhere is still refused.
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "pc"
            canary = self._outside(tmp)
            escape = canary.parent / "model.fp32.onnx"
            with self.assertRaisesRegex(AssertionError, "outside the scratch cache"):
                self._main(cache, export=lambda _model, _path: escape.write_bytes(b"stub graph"))
            self.assertFalse(escape.exists())
            self.assertEqual(canary.read_text(), "real")

class OnnxRootTests(unittest.TestCase):
    """The ONNX root: PREACHED_ONNX_DIR, else $PREACHED_CACHE/models/..., else /cache/models/..."""

    def _root(self, **env: str) -> Path:
        from preached.artifacts import onnx_root

        base = {k: v for k, v in os.environ.items() if k not in {"PREACHED_ONNX_DIR", "PREACHED_CACHE"}}
        base.update(env)
        with mock.patch.dict(os.environ, base, clear=True):
            return onnx_root()

    def test_precedence(self) -> None:
        self.assertEqual(self._root(), Path("/cache/models/granite-english-r2-onnx"))
        self.assertEqual(self._root(PREACHED_CACHE="/tmp/pc-x"), Path("/tmp/pc-x/models/granite-english-r2-onnx"))
        self.assertEqual(self._root(PREACHED_CACHE="/tmp/pc-x", PREACHED_ONNX_DIR="/tmp/o"), Path("/tmp/o"))

    def test_the_server_names_the_custom_cache_path_when_the_graph_is_missing(self) -> None:
        from app.server import load_search

        with tempfile.TemporaryDirectory() as tmp:
            base = {k: v for k, v in os.environ.items() if k != "PREACHED_ONNX_DIR"}
            base["PREACHED_CACHE"] = tmp
            with mock.patch.dict(os.environ, base, clear=True):
                connection = _seed_granite(Path(tmp) / "index.sqlite")
                try:
                    with self.assertLogs(level="ERROR") as logs:
                        load_search(connection, GRANITE_MODEL_KEY, embed_backend="onnx")
                finally:
                    connection.close()
            expected = Path(tmp) / "models" / "granite-english-r2-onnx" / GRANITE_REVISION / "manifest.json"
            self.assertIn(str(expected), "\n".join(logs.output))
            self.assertEqual(_tree(Path(tmp)), ["index.sqlite"])


class HfCacheDefaultTests(unittest.TestCase):
    """The export's Hugging Face cache follows PREACHED_CACHE; nothing is downloaded."""

    def _run(self, **env_set: str) -> list[str]:
        # execv is replaced so the restart is recorded: the env it would pass on
        # is what the real second process starts with.
        code = (
            "import os, sys\n"
            f"sys.path.insert(0, {str(ROOT / 'scripts')!r})\n"
            "import export_onnx\n"
            "def execv(path, argv):\n"
            "    print(os.environ['HF_HOME'], os.environ['HUGGINGFACE_HUB_CACHE'], 'torch' in sys.modules)\n"
            "    assert os.environ['HF_HUB_CACHE'] == os.environ['HUGGINGFACE_HUB_CACHE']\n"
            "    raise SystemExit(0)\n"
            "os.execv = execv\n"
            "export_onnx._reexec_with_hashseed()\n"
        )
        drop = {"PYTHONHASHSEED", "HF_HOME", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "PREACHED_CACHE"}
        env = child_env({k: v for k, v in os.environ.items() if k not in drop}, **env_set)
        result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.split()

    def test_the_cache_follows_preached_cache(self) -> None:
        self.assertEqual(
            self._run(PREACHED_CACHE="/tmp/pc-x"),
            ["/tmp/pc-x/huggingface", "/tmp/pc-x/huggingface/hub", "False"],
        )

    def test_unset_preached_cache_falls_back_to_slash_cache(self) -> None:
        self.assertEqual(self._run(), ["/cache/huggingface", "/cache/huggingface/hub", "False"])

    def test_an_explicit_hf_home_wins_and_the_hub_cache_follows_it(self) -> None:
        self.assertEqual(
            self._run(PREACHED_CACHE="/tmp/pc-x", HF_HOME="/tmp/hf-y"),
            ["/tmp/hf-y", "/tmp/hf-y/hub", "False"],
        )

    def test_an_explicit_hub_cache_under_either_name_wins(self) -> None:
        # huggingface_hub reads HF_HUB_CACHE first; both names end up equal.
        for name in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
            with self.subTest(name=name):
                self.assertEqual(
                    self._run(PREACHED_CACHE="/tmp/pc-x", **{name: "/tmp/hub-z"}),
                    ["/tmp/pc-x/huggingface", "/tmp/hub-z", "False"],
                )


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
            self.skipTest("granite onnx artifacts are not under PREACHED_CACHE (or PREACHED_ONNX_DIR)")
        from preached.onnx_embed import OnnxEmbedder

        # The cache is only read; the 597 MB copy goes to TMPDIR.
        with tempfile.TemporaryDirectory() as tmp:
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
        env = child_env(os.environ, PYTHONHASHSEED=seed)
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
        env = child_env({k: v for k, v in os.environ.items() if k != "PYTHONHASHSEED"})
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
        # Outputs and the HF cache are in a TMPDIR temp dir; the snapshot in
        # CACHE is only read, through a symlink, offline.
        with tempfile.TemporaryDirectory(prefix="export-repro-") as tmp:
            hf_home = Path(tmp) / "hf"
            linked = hf_home / "hub" / SNAPSHOT.relative_to(CACHE / "huggingface" / "hub")
            linked.parent.mkdir(parents=True)
            linked.symlink_to(SNAPSHOT, target_is_directory=True)
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
                env = _sandbox_env(Path(tmp), PREACHED_ONNX_DIR=str(out), CUDA_VISIBLE_DEVICES="", **start)
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
