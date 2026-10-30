"""Serve-time footprint, health identity, and the deploy bundle."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from app.server import (  # noqa: E402
    MAX_HEADER_BYTES,
    STATIC_DIR,
    App,
    RateLimiter,
    make_server,
    public_sha256,
)
from preached.artifacts import FP32_ONNX_SHA256, GRANITE_REVISION  # noqa: E402
from preached.search import Searcher  # noqa: E402
from preached.store import connect  # noqa: E402

SHA = "ab" * 32
OTHER_SHA = "cd" * 32
FORBIDDEN_IMPORTS = (
    "torch",
    "torchvision",
    "torchaudio",
    "whisper",
    "faster_whisper",
    "ctranslate2",
    "sentence_transformers",
    "transformers",
    "yt_dlp",
    "onnx",
    "onnxscript",
    "PIL",
    "av",
    "nvidia",
    "huggingface_hub",
)
def _insert(connection: sqlite3.Connection, text: str) -> None:
    connection.execute(
        """
        INSERT INTO chunks (chunk_id, sermon_id, sermon_title, text, sermon_number, word_count)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("wesley-001-c0000", "wesley-001", "Salvation by Faith", text, 1, 4),
    )


def _encode(_query: str) -> np.ndarray:
    return np.array([1, 0, 0, 0], dtype=np.float32)


FORBIDDEN_REQUIREMENTS = (
    "torch",
    "torchvision",
    "faster-whisper",
    "faster_whisper",
    "ctranslate2",
    "sentence-transformers",
    "yt-dlp",
    "yt_dlp",
    "onnxscript",
    "pillow",
)


def _request(port: int, path: str, headers: dict | None = None):
    import http.client

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path, headers=headers or {})
    response = conn.getresponse()
    body = response.read()
    header_map = {key: value for key, value in response.getheaders()}
    status = response.status
    conn.close()
    return status, header_map, body


class ShaTests(unittest.TestCase):
    def test_only_hex_is_public(self) -> None:
        self.assertEqual(public_sha256(SHA), SHA)
        self.assertIsNone(public_sha256("/cache/index/wesley.sqlite"))
        self.assertIsNone(public_sha256(SHA.upper()))
        self.assertIsNone(public_sha256(SHA[:-1]))
        self.assertIsNone(public_sha256(None))


class HealthIdentityTests(unittest.TestCase):
    def test_health_reports_hashes_and_drops_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wesley.sqlite"
            connection = connect(path)
            _insert(connection, "By grace are ye saved through faith.")
            connection.execute(
                "INSERT INTO meta (key, value) VALUES ('chunks_sha256', ?)",
                (SHA,),
            )
            connection.commit()

            def encode(_query: str):
                return _encode(_query)

            encode.model_sha256 = OTHER_SHA
            encode.backend = "onnx"
            app = App(
                connection=connection,
                searcher=Searcher(connection),
                encode=encode,
                fallback_note=None,
                model_name="granite-english-r2",
                hosts={"127.0.0.1"},
                static_dir=STATIC_DIR,
                backend="onnx",
            )
            health = app.health()
            self.assertEqual(health["index_version"], SHA)
            self.assertEqual(health["model_sha256"], OTHER_SHA)
            self.assertFalse(health["disabled"])
            self.assertNotIn("/", json.dumps(health))

            connection.execute(
                "UPDATE meta SET value = ? WHERE key = 'chunks_sha256'",
                ("/cache/index/wesley.sqlite",),
            )
            connection.commit()
            encode.model_sha256 = "/cache/models/granite/model.fp32.onnx"
            hidden = app.health()
            self.assertIsNone(hidden["index_version"])
            self.assertIsNone(hidden["model_sha256"])
            self.assertNotIn("cache", json.dumps(hidden))
            self.assertNotIn(".sqlite", json.dumps(hidden))
            connection.close()


class RateAndKillTests(unittest.TestCase):
    def _serve(self, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "wesley.sqlite"
        connection = connect(path)
        _insert(connection, "zealboundary grace")
        connection.commit()
        connection.close()
        connection = sqlite3.connect(path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        app = App(
            connection=connection,
            searcher=Searcher(connection),
            encode=None,
            fallback_note=None,
            model_name=None,
            hosts={"127.0.0.1", "localhost"},
            static_dir=STATIC_DIR,
            **kwargs,
        )
        server = make_server(app, "127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        self.addCleanup(connection.close)
        return server.server_address[1], app

    def test_per_ip_limit_ignores_forwarded_for(self) -> None:
        port, _app = self._serve(rate_limit=2, rate_window_s=60)
        first, _, _ = _request(port, "/healthz")
        second, _, _ = _request(port, "/healthz")
        third, headers, body = _request(
            port,
            "/api/search?q=secretquery",
            headers={"X-Forwarded-For": "203.0.113.5"},
        )
        self.assertEqual(first, 200)
        self.assertEqual(second, 200)
        self.assertEqual(third, 429)
        self.assertEqual(json.loads(body), {"error": "too many requests"})
        self.assertNotIn(b"secretquery", body)
        self.assertIn("Retry-After", {key.title(): value for key, value in headers.items()} | headers)
        self.assertEqual(headers.get("Retry-After"), "60")

    def test_kill_file_stops_search_without_leaking_the_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kill = Path(tmp) / "KILL"
            port, app = self._serve(kill_file=kill)
            status, _, body = _request(port, "/healthz")
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body)["ok"])
            kill.write_text("operator-note\n")
            status, _, body = _request(port, "/healthz")
            self.assertEqual(status, 503)
            self.assertEqual(json.loads(body), {"ok": False, "disabled": True})
            self.assertNotIn(b"operator-note", body)
            self.assertNotIn(b"KILL", body)
            self.assertNotIn(tmp.encode(), body)
            status, _, body = _request(port, "/api/search?q=secretquery")
            self.assertEqual(status, 503)
            self.assertEqual(json.loads(body), {"error": "unavailable"})
            self.assertNotIn(b"secretquery", body)
            self.assertTrue(app.disabled())
            kill.unlink()
            status, _, body = _request(port, "/healthz")
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body)["ok"])

    def test_disabled_env_is_a_kill_switch(self) -> None:
        port, _app = self._serve()
        previous = os.environ.get("PREACHED_DISABLED")
        os.environ["PREACHED_DISABLED"] = "1"
        try:
            status, _, body = _request(port, "/healthz")
        finally:
            if previous is None:
                os.environ.pop("PREACHED_DISABLED", None)
            else:
                os.environ["PREACHED_DISABLED"] = previous
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)["disabled"], True)

    def test_header_budget(self) -> None:
        port, _app = self._serve()
        status, _, body = _request(port, "/healthz", headers={"X-Pad": "a" * (MAX_HEADER_BYTES + 50)})
        self.assertEqual(status, 431)
        self.assertEqual(json.loads(body), {"error": "request too large"})
        self.assertNotIn(b"aaaaaaa", body)

    def test_access_log_drops_the_query(self) -> None:
        port, _app = self._serve()
        token = "querytokennotforlogs"
        with self.assertLogs(level="INFO") as logs:
            status, _, _body = _request(port, f"/api/search?q={token}&mode=bm25")
        self.assertEqual(status, 200)
        joined = "\n".join(logs.output)
        self.assertNotIn(token, joined)
        self.assertIn("/api/search", joined)

    def test_rate_table_drops_idle_keys(self) -> None:
        limiter = RateLimiter(1, 10, max_keys=2)
        self.assertTrue(limiter.allow("a", now=0))
        self.assertTrue(limiter.allow("b", now=0))
        self.assertFalse(limiter.allow("c", now=1))
        self.assertTrue(limiter.allow("c", now=11))


class ImportGuardTests(unittest.TestCase):
    def test_serve_imports_do_not_pull_build_deps(self) -> None:
        code = (
            "import sys\n"
            "from pathlib import Path\n"
            "root = Path(sys.argv[1])\n"
            "sys.path.insert(0, str(root / 'src'))\n"
            "sys.path.insert(0, str(root))\n"
            "import app.server\n"
            "import preached.onnx_embed\n"
            "import preached.artifacts\n"
            "import onnxruntime\n"
            "import tokenizers\n"
            "forbidden = set(sys.argv[2:])\n"
            "loaded = sorted(name.split('.', 1)[0] for name in sys.modules)\n"
            "hit = sorted(set(loaded) & forbidden)\n"
            "if hit:\n"
            "    raise SystemExit('forbidden imports: ' + ','.join(hit))\n"
            "needed = {'numpy', 'onnxruntime', 'tokenizers'}\n"
            "missing = sorted(needed - set(loaded))\n"
            "if missing:\n"
            "    raise SystemExit('serve deps not imported: ' + ','.join(missing))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, str(ROOT), *FORBIDDEN_IMPORTS],
            cwd=ROOT,
            env={**os.environ, "CUDA_VISIBLE_DEVICES": ""},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class BundleTests(unittest.TestCase):
    def _env(self, **extra) -> dict:
        env = os.environ.copy()
        env.update(extra)
        env.setdefault("PREACHED_BUNDLE_SKIP_PINS", "1")
        return env

    def _stand_in(self, root: Path) -> tuple[Path, Path]:
        model = root / "onnx" / GRANITE_REVISION
        model.mkdir(parents=True)
        for name in ("manifest.json", "model.fp32.onnx", "tokenizer.json", "pooling.json"):
            (model / name).write_bytes(f"stand-in {name}\n".encode())
        index_dir = root / "indexes"
        index_dir.mkdir()
        index = index_dir / "wesley.sqlite"
        connection = sqlite3.connect(index)
        connection.execute("CREATE TABLE chunks (chunk_id TEXT)")
        connection.commit()
        connection.close()
        return model.parent, index

    def test_refuses_church_and_youtube_libraries(self) -> None:
        script = ROOT / "scripts" / "build-bundle.sh"
        for library in ("sample", "cc-speech", "gaston", "youtube-gcc"):
            with self.subTest(library=library):
                result = subprocess.run(
                    ["bash", str(script), "/tmp/does-not-matter"],
                    cwd=ROOT,
                    env=self._env(PREACHED_LIBRARY=library),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertIn("refusing", result.stderr)

    def test_refuses_a_renamed_church_path_and_a_symlink(self) -> None:
        script = ROOT / "scripts" / "build-bundle.sh"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "real.sqlite"
            real.write_bytes(b"not a church db")
            linked_dir = root / "links"
            linked_dir.mkdir()
            link = linked_dir / "wesley.sqlite"
            link.symlink_to(real)
            church = root / "cc-speech" / "wesley.sqlite"
            church.parent.mkdir()
            church.write_bytes(b"no")
            out = root / "out"
            symlink = subprocess.run(
                ["bash", str(script), str(out)],
                cwd=ROOT,
                env=self._env(PREACHED_LIBRARY="wesley", PREACHED_INDEX=str(link)),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(symlink.returncode, 0)
            self.assertIn("symlink", symlink.stderr)
            renamed = subprocess.run(
                ["bash", str(script), str(out)],
                cwd=ROOT,
                env=self._env(PREACHED_LIBRARY="wesley", PREACHED_INDEX=str(church)),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(renamed.returncode, 0)
            self.assertIn("refusing", renamed.stderr)

    def test_bundle_is_reproducible_and_serve_only(self) -> None:
        script = ROOT / "scripts" / "build-bundle.sh"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            onnx_root, index = self._stand_in(root)
            env = self._env(
                PREACHED_LIBRARY="wesley",
                PREACHED_INDEX=str(index),
                PREACHED_ONNX_DIR=str(onnx_root),
            )
            first = root / "one"
            second = root / "two"
            for dest in (first, second):
                result = subprocess.run(
                    ["bash", str(script), str(dest)],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            manifest_a = (first / "MANIFEST.sha256").read_bytes()
            manifest_b = (second / "MANIFEST.sha256").read_bytes()
            self.assertEqual(manifest_a, manifest_b)
            self.assertEqual((Path(str(first) + ".tar.gz")).read_bytes(), (Path(str(second) + ".tar.gz")).read_bytes())
            names = [line.split("  ", 1)[1].strip() for line in manifest_a.decode().splitlines()]
            joined = "\n".join(names)
            self.assertIn(f"model/{GRANITE_REVISION}/model.fp32.onnx", names)
            self.assertIn("index/wesley.sqlite", names)
            self.assertIn("requirements-serve.txt", names)
            self.assertIn("app/server.py", names)
            self.assertNotIn("model.int8.onnx", joined)
            self.assertNotIn("torch_embed.py", joined)
            self.assertNotIn("transcribe.py", joined)
            self.assertNotIn("cc-speech", joined)
            requirements = (first / "requirements-serve.txt").read_text().lower()
            for package in FORBIDDEN_REQUIREMENTS:
                self.assertNotIn(package, requirements)
            self.assertIn("onnxruntime==", requirements)
            self.assertIn("tokenizers==", requirements)
            self.assertIn("numpy==", requirements)
            checked = subprocess.run(
                ["sha256sum", "-c", "MANIFEST.sha256"],
                cwd=first,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            mode = (first / "index" / "wesley.sqlite").stat().st_mode & 0o777
            self.assertEqual(mode, 0o444)

    def test_serve_sh_refuses_a_sample_library(self) -> None:
        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "serve.sh")],
            cwd=ROOT,
            env=self._env(PREACHED_LIBRARY="sample"),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("sample", result.stderr)
        self.assertNotIn(FP32_ONNX_SHA256, result.stderr)


if __name__ == "__main__":
    unittest.main()
