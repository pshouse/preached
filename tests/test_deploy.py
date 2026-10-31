"""Serve-time footprint, health identity, and the deploy bundle."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from app.server import (  # noqa: E402
    MAX_HEADER_BYTES,
    STATIC_DIR,
    App,
    bundle_problem,
    RateLimiter,
    main,
    make_server,
    onnx_dir_problem,
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
    def _serve(self, *, max_connections=None, max_per_client=None, header_deadline_s=None, **kwargs):
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
        if max_connections is not None:
            server.max_connections = max_connections
        if max_per_client is not None:
            server.max_connections_per_client = max_per_client
        if header_deadline_s is not None:
            server.header_deadline_s = header_deadline_s
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        self.addCleanup(connection.close)
        return server.server_address[1], app, server

    def test_per_ip_limit_ignores_forwarded_for(self) -> None:
        port, _app, _server = self._serve(rate_limit=2, rate_window_s=60)
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
            port, app, _server = self._serve(kill_file=kill)
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
        port, _app, _server = self._serve()
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
        port, _app, _server = self._serve()
        status, _, body = _request(port, "/healthz", headers={"X-Pad": "a" * (MAX_HEADER_BYTES + 50)})
        self.assertEqual(status, 431)
        self.assertEqual(json.loads(body), {"error": "request too large"})
        self.assertNotIn(b"aaaaaaa", body)

    def test_access_log_drops_the_query(self) -> None:
        port, _app, _server = self._serve()
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

    def test_full_table_refuses_a_new_client(self) -> None:
        limiter = RateLimiter(2, 60, max_keys=2)
        self.assertTrue(limiter.allow("a", now=0))
        self.assertTrue(limiter.allow("b", now=0))
        self.assertFalse(limiter.allow("new", now=1))
        self.assertTrue(limiter.allow("a", now=1))
        self.assertFalse(limiter.allow("a", now=1))

    def test_healthz_uses_the_same_bucket(self) -> None:
        port, _app, _server = self._serve(rate_limit=1, rate_window_s=60)
        self.assertEqual(_request(port, "/healthz")[0], 200)
        status, _, body = _request(port, "/healthz")
        self.assertEqual(status, 429)
        self.assertEqual(json.loads(body), {"error": "too many requests"})

    def test_kill_switch_fails_closed_on_surprises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "KILL"
            directory.mkdir()
            _port, app, _server = self._serve(kill_file=directory)
            self.assertTrue(app.disabled())
            status, _, body = _request(_port, "/healthz")
            self.assertEqual(status, 503)
            self.assertEqual(json.loads(body), {"ok": False, "disabled": True})

            dangling = root / "gone"
            dangling.symlink_to(root / "missing-target")
            app.kill_file = dangling
            self.assertTrue(app.disabled())

            hidden = root / "hidden"
            hidden.mkdir()
            app.kill_file = hidden / "KILL"
            hidden.chmod(0)
            try:
                self.assertTrue(app.disabled())
            finally:
                hidden.chmod(0o755)
            self.assertFalse(app.disabled())

    def test_bad_request_line_does_not_crash_and_controls_are_escaped(self) -> None:
        port, _app, _server = self._serve()
        sock = socket.create_connection(("127.0.0.1", port), timeout=2)
        sock.sendall(b"GET /healthz HTTP/nope\r\n\r\n")
        sock.settimeout(2)
        try:
            sock.recv(200)
        except OSError:
            pass
        sock.close()
        with self.assertLogs(level="INFO") as logs:
            raw = socket.create_connection(("127.0.0.1", port), timeout=2)
            raw.sendall(b"GET /\x01secret HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            raw.settimeout(2)
            reply = raw.recv(400)
            raw.close()
        # A control character in the request line is a 400 before parsing;
        # the line is neither echoed nor logged.
        self.assertTrue(reply.startswith(b"HTTP/1.1 400") or reply.startswith(b"HTTP/1.0 400"), reply)
        joined = "\n".join(logs.output)
        self.assertNotIn("\x01", joined)
        self.assertNotIn("secret", joined)
        status, _, _body = _request(port, "/healthz")
        self.assertEqual(status, 200)

    def test_header_deadline_is_not_per_read(self) -> None:
        port, _app, server = self._serve(header_deadline_s=0.4)
        sock = socket.create_connection(("127.0.0.1", port), timeout=2)
        started = time.monotonic()
        sock.sendall(b"G")
        held = False
        closed = False
        while time.monotonic() - started < 2.0:
            time.sleep(0.05)
            if server._conn_total >= 1 and time.monotonic() - started < 0.3:
                held = True
            try:
                sock.sendall(b"E")
            except OSError:
                closed = True
                break
            if server._conn_total == 0 and time.monotonic() - started > 0.3:
                closed = True
                break
        elapsed = time.monotonic() - started
        sock.close()
        self.assertTrue(held)
        self.assertTrue(closed)
        self.assertGreater(elapsed, 0.3)
        self.assertLess(elapsed, 1.2)
        status, _, _body = _request(port, "/healthz")
        self.assertEqual(status, 200)

    def test_connection_caps_reject_without_a_handler_slot(self) -> None:
        port, _app, server = self._serve(max_connections=4, max_per_client=1, header_deadline_s=2)
        held = socket.create_connection(("127.0.0.1", port), timeout=2)
        held.sendall(b"GET /healthz HTTP/1.1\r\n")
        for _ in range(50):
            if server._conn_total >= 1:
                break
            time.sleep(0.02)
        self.assertGreaterEqual(server._conn_total, 1)
        extra = socket.create_connection(("127.0.0.1", port), timeout=2)
        extra.settimeout(2)
        extra.sendall(b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        data = b""
        while len(data) < 16:
            chunk = extra.recv(200)
            if not chunk:
                break
            data += chunk
        extra.close()
        self.assertTrue(data.startswith(b"HTTP/1.1 503"), data[:80])
        held.close()
        for _ in range(50):
            if server._conn_total == 0:
                break
            time.sleep(0.02)
        status, _, _body = _request(port, "/healthz")
        self.assertEqual(status, 200)

    def test_server_refuses_root(self) -> None:
        with mock.patch.dict(os.environ, {"PREACHED_ALLOW_ROOT": "1"}):
            with mock.patch("app.server.os.geteuid", return_value=0):
                with self.assertRaises(SystemExit) as caught:
                    main([])
        self.assertIn("root", str(caught.exception))
        script = (ROOT / "scripts" / "serve.sh").read_text()
        self.assertNotIn("PREACHED_ALLOW_ROOT", script)
        self.assertNotIn("PREACHED_PYTHON", script)
        self.assertIn("env -i", script)


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
        return env

    def _stand_in(self, root: Path) -> tuple[Path, Path]:
        model = root / "onnx" / GRANITE_REVISION
        model.mkdir(parents=True)
        for name in ("manifest.json", "model.fp32.onnx", "tokenizer.json", "pooling.json"):
            (model / name).write_bytes(f"stand-in {name}\n".encode())
        index_dir = root / "indexes"
        index_dir.mkdir()
        index = index_dir / "wesley.sqlite"
        connection = connect(index)
        _insert(connection, "By grace are ye saved through faith.")
        connection.commit()
        connection.close()
        return model.parent, index

    def _fixture_source(self, root: Path) -> tuple[Path, Path, Path]:
        """A copy of the source tree whose artifacts.py pins the stand-in files.

        The build checks the real pins; there is no switch that skips them.
        The tests build from this copy, so the fixture model is "pinned" by
        the code that ships with it, the same way a real bundle is.
        """
        onnx_root, index = self._stand_in(root)
        source = root / "source"
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
        for rel in ("app", "src", "scripts", "search", "ingest/manifest"):
            shutil.copytree(ROOT / rel, source / rel, ignore=ignore)
        for rel in ("pyproject.toml", "uv.lock", "README.md", "AGENTS.md", ".python-version", "LICENSE", "NOTICE"):
            shutil.copy2(ROOT / rel, source / rel)
        (source / ".venv").symlink_to(ROOT / ".venv")
        model = onnx_root / GRANITE_REVISION
        pins = {
            "FP32_ONNX_SHA256": hashlib.sha256((model / "model.fp32.onnx").read_bytes()).hexdigest(),
            "TOKENIZER_SHA256": hashlib.sha256((model / "tokenizer.json").read_bytes()).hexdigest(),
        }
        artifacts = source / "src" / "preached" / "artifacts.py"
        lines = artifacts.read_text().splitlines(keepends=True)
        for number, line in enumerate(lines):
            for name, digest in pins.items():
                if line.startswith(f"{name} = "):
                    lines[number] = f'{name} = "{digest}"\n'
        artifacts.write_text("".join(lines))
        for name, digest in pins.items():
            self.assertIn(f'{name} = "{digest}"', artifacts.read_text())
        return source, onnx_root, index

    def _build(self, source: Path, out: Path, onnx_root: Path, index: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(source / "scripts" / "build-bundle.sh"), str(out)],
            cwd=source,
            env=self._env(
                PREACHED_LIBRARY="wesley",
                PREACHED_INDEX=str(index),
                PREACHED_ONNX_DIR=str(onnx_root),
            ),
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

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
                self.assertIn(library, result.stderr)

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
            self.assertIn("error:", symlink.stderr)
            renamed = subprocess.run(
                ["bash", str(script), str(out)],
                cwd=ROOT,
                env=self._env(PREACHED_LIBRARY="wesley", PREACHED_INDEX=str(church)),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(renamed.returncode, 0)
            self.assertIn("error:", renamed.stderr)

    def test_bundle_is_reproducible_and_serve_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, onnx_root, index = self._fixture_source(root)
            first = root / "one"
            second = root / "two"
            inputs = []
            for dest in (first, second):
                result = self._build(source, dest, onnx_root, index)
                self.assertEqual(result.returncode, 0, result.stderr)
                inputs.append([line for line in result.stdout.splitlines() if line.startswith("input ")])
            # The build inputs are printed, and two builds of the same inputs agree.
            self.assertEqual(inputs[0], inputs[1])
            for name in ("source", "index-file", "index-bundled", "model-revision", "python", "uv", "tar", "gzip"):
                self.assertTrue(any(line.startswith(f"input {name} ") for line in inputs[0]), (name, inputs[0]))
            manifest_a = (first / "MANIFEST.sha256").read_bytes()
            manifest_b = (second / "MANIFEST.sha256").read_bytes()
            self.assertEqual(manifest_a, manifest_b)
            self.assertEqual((Path(str(first) + ".tar.gz")).read_bytes(), (Path(str(second) + ".tar.gz")).read_bytes())
            # No comment or marker lines: every line is a hash and a path.
            self.assertNotIn("#", manifest_a.decode())
            self.assertNotIn("pins", manifest_a.decode())
            names = [line.split("  ", 1)[1] for line in manifest_a.decode().splitlines()]
            joined = "\n".join(names)
            self.assertIn(f"model/{GRANITE_REVISION}/model.fp32.onnx", names)
            self.assertIn("index/wesley.sqlite", names)
            self.assertIn("requirements-serve.txt", names)
            self.assertIn("app/server.py", names)
            self.assertIn("src/preached/libraries.py", names)
            # Merged from main (#17, #19): imported by app.server, so derived.
            self.assertIn("src/preached/audio_policy.py", names)
            self.assertIn("src/preached/privacy.py", names)
            self.assertIn("src/preached/privacy_data/lexicon.txt.gz", names)
            self.assertIn("scripts/serve.sh", names)
            self.assertIn("app/static/app.js", names)
            self.assertIn("ingest/manifest/spurgeon.provenance.json", names)
            self.assertIn("ingest/manifest/edwards.provenance.json", names)
            self.assertNotIn("model.int8.onnx", joined)
            self.assertNotIn("torch_embed.py", joined)
            self.assertNotIn("transcribe.py", joined)
            self.assertNotIn("src/preached/asr.py", joined)
            self.assertNotIn("src/preached/embed.py", joined)
            self.assertNotIn("__pycache__", joined)
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
            for directory in (first, first / "index"):
                self.assertEqual(directory.stat().st_mode & 0o022, 0)
            bundled = first / "index" / "wesley.sqlite"
            self.assertFalse(Path(str(bundled) + "-wal").exists())
            bundled.chmod(0o444)
            bundled.parent.chmod(0o555)
            first.chmod(0o555)
            try:
                opened = sqlite3.connect(f"{bundled.resolve().as_uri()}?mode=ro", uri=True)
                try:
                    count = opened.execute("SELECT count(*) FROM chunks").fetchone()[0]
                    journal = opened.execute("PRAGMA journal_mode").fetchone()[0]
                finally:
                    opened.close()
            finally:
                first.chmod(0o755)
                bundled.parent.chmod(0o755)
            self.assertEqual(count, 1)
            self.assertEqual(journal, "delete")

    def _build_with_tar(self, root: Path, tar_body: str, *, cwd: Path | None = None):
        """Build with a fake `tar` first on PATH. It runs the real tar, then
        behaves as `tar_body` says for the create (-cf) call only."""
        source, onnx_root, index = self._fixture_source(root)
        fake_bin = root / "fakebin"
        fake_bin.mkdir()
        real_tar = shutil.which("tar")
        fake = fake_bin / "tar"
        fake.write_text(
            "#!/bin/bash\n"
            f'case " $* " in *" -cf "*) ;; *) exec {real_tar} "$@";; esac\n'
            f'{real_tar} "$@"\n'
            "status=$?\n"
            f"{tar_body}\n"
            'exit "$status"\n'
        )
        fake.chmod(0o755)
        env = self._env(
            PREACHED_LIBRARY="wesley",
            PREACHED_INDEX=str(index),
            PREACHED_ONNX_DIR=str(onnx_root),
            PATH=f"{fake_bin}:{os.environ['PATH']}",
        )
        out = root / "bundle"
        result = subprocess.run(
            ["bash", str(source / "scripts" / "build-bundle.sh"), str(out)],
            cwd=cwd or source,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        return result, out

    def test_tar_exit_1_leaves_no_archive_and_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result, out = self._build_with_tar(root, "status=1")
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("no archive written", result.stderr)
            self.assertEqual(sorted(p.name for p in root.glob("bundle.tar*")), [])
            self.assertEqual(list(root.glob("*.partial*")), [])

    def test_failed_rebuild_removes_an_older_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale = root / "bundle.tar.gz"
            stale.write_bytes(b"from an earlier build")
            result, _ = self._build_with_tar(root, "status=1")
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(stale.exists())

    def test_tar_exit_1_once_is_retried_and_the_archive_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            counter = root / "calls"
            body = f'echo x >> "{counter}"; [ "$(wc -l < "{counter}")" -eq 1 ] && status=1'
            result, out = self._build_with_tar(root, body)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("retrying once", result.stderr)
            self.assertEqual(len(counter.read_text().splitlines()), 2)
            self._assert_archive_matches_manifest(root, out)

    def test_tar_exit_2_is_not_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            counter = root / "calls"
            result, _ = self._build_with_tar(root, f'echo x >> "{counter}"; status=2')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(counter.read_text().splitlines()), 1)
            self.assertEqual(list(root.glob("bundle.tar*")), [])

    def test_archive_that_disagrees_with_the_manifest_is_not_kept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # tar exits 0 but the archive holds a file the manifest does not list.
            source, onnx_root, index = self._fixture_source(root)
            fake_bin = root / "fakebin"
            fake_bin.mkdir()
            real_tar = shutil.which("tar")
            fake = fake_bin / "tar"
            fake.write_text(
                "#!/bin/bash\n"
                f'case " $* " in *" -cf "*) ;; *) exec {real_tar} "$@";; esac\n'
                'args=("$@")\n'
                'for ((i = 0; i < ${#args[@]}; i++)); do\n'
                '  if [ "${args[i]}" = -C ]; then echo extra > "${args[i+1]}/extra.txt"; fi\n'
                'done\n'
                f'exec {real_tar} "${{args[@]}}"\n'
            )
            fake.chmod(0o755)
            result = subprocess.run(
                ["bash", str(source / "scripts" / "build-bundle.sh"), str(root / "bundle")],
                cwd=source,
                env=self._env(
                    PREACHED_LIBRARY="wesley",
                    PREACHED_INDEX=str(index),
                    PREACHED_ONNX_DIR=str(onnx_root),
                    PATH=f"{fake_bin}:{os.environ['PATH']}",
                ),
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not match MANIFEST.sha256", result.stderr)
            self.assertEqual(list(root.glob("bundle.tar*")), [])

    def _assert_archive_matches_manifest(self, root: Path, out: Path) -> None:
        archive = Path(str(out) + ".tar.gz")
        self.assertTrue(archive.is_file())
        self.assertEqual(list(root.glob("*.partial*")), [])
        extracted = root / "extracted"
        extracted.mkdir()
        subprocess.run(["tar", "-xzf", str(archive), "-C", str(extracted)], check=True)
        check = subprocess.run(
            ["sha256sum", "--check", "--strict", "MANIFEST.sha256"],
            cwd=extracted,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertEqual(
            (extracted / "MANIFEST.sha256").read_bytes(), (out / "MANIFEST.sha256").read_bytes()
        )

    def test_success_archive_verifies_against_the_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, onnx_root, index = self._fixture_source(root)
            out = root / "bundle"
            result = self._build(source, out, onnx_root, index)
            self.assertEqual(result.returncode, 0, result.stderr)
            self._assert_archive_matches_manifest(root, out)

    def test_a_decoy_package_in_the_callers_cwd_is_not_imported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, onnx_root, index = self._fixture_source(root)
            decoy = root / "elsewhere"
            marker = root / "decoy-ran"
            for package in ("preached", "app", "scripts"):
                (decoy / package).mkdir(parents=True)
                (decoy / package / "__init__.py").write_text(
                    f"open({str(marker)!r}, 'a').write({package!r})\nraise SystemExit('decoy imported')\n"
                )
            result = subprocess.run(
                ["bash", str(source / "scripts" / "build-bundle.sh"), str(root / "bundle")],
                cwd=decoy,
                env=self._env(
                    PREACHED_LIBRARY="wesley",
                    PREACHED_INDEX=str(index),
                    PREACHED_ONNX_DIR=str(onnx_root),
                ),
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists(), marker.read_text() if marker.exists() else "")

    def test_int8_is_removed_from_the_bundled_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, onnx_root, index = self._fixture_source(root)
            folder = onnx_root / GRANITE_REVISION
            manifest = {
                "hf_id": "ibm-granite/granite-embedding-english-r2",
                "revision": GRANITE_REVISION,
                "variants": {"fp32": "model.fp32.onnx", "int8": "model.int8.onnx"},
                "files": {
                    "model.fp32.onnx": {"sha256": "ab" * 32},
                    "model.int8.onnx": {"sha256": "cd" * 32},
                },
            }
            (folder / "manifest.json").write_text(json.dumps(manifest))
            (folder / "model.int8.onnx").write_bytes(b"int8 stand-in\n")
            out = root / "out"
            result = self._build(source, out, onnx_root, index)
            self.assertEqual(result.returncode, 0, result.stderr)
            shipped = json.loads((out / "model" / GRANITE_REVISION / "manifest.json").read_text())
            self.assertNotIn("int8", shipped["variants"])
            self.assertNotIn("model.int8.onnx", shipped["files"])
            self.assertFalse((out / "model" / GRANITE_REVISION / "model.int8.onnx").exists())

    def test_build_checks_the_real_pins_with_no_switch(self) -> None:
        # Stand-in files do not match the pins in the real artifacts.py.
        # The old PREACHED_BUNDLE_SKIP_PINS no longer exists: set or not,
        # and with the unittest process as the direct parent, the build fails.
        for name in ("scripts/build-bundle.sh", "app/server.py", "scripts/bundle_manifest.py"):
            text = (ROOT / name).read_text()
            self.assertNotIn("SKIP_PINS", text, name)
            self.assertNotIn("pins-skipped", text, name)
        script = ROOT / "scripts" / "build-bundle.sh"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            onnx_root, index = self._stand_in(root)
            for extra in ({}, {"PREACHED_BUNDLE_SKIP_PINS": "1"}):
                with self.subTest(extra=extra):
                    out = root / ("out" + str(len(extra)))
                    result = subprocess.run(
                        ["bash", str(script), str(out)],
                        cwd=ROOT,
                        env=self._env(
                            PREACHED_LIBRARY="wesley",
                            PREACHED_INDEX=str(index),
                            PREACHED_ONNX_DIR=str(onnx_root),
                            **extra,
                        ),
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=60,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("pin", result.stderr)
                    self.assertFalse(out.exists())

    def test_serve_sh_drops_secret_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = root / "wesley.sqlite"
            connection = connect(index)
            _insert(connection, "By grace are ye saved through faith.")
            connection.commit()
            connection.close()
            onnx = root / "onnx"
            onnx.mkdir()
            log = root / "server.log"
            env = self._env(
                PREACHED_LIBRARY="wesley",
                PREACHED_INDEX=str(index),
                PREACHED_ONNX_DIR=str(onnx),
                PREACHED_HOST="127.0.0.1",
                PREACHED_PORT="0",
                PREACHED_HOSTS="127.0.0.1,localhost",
                FAKE_TOKEN="dummy",
                AWS_SECRET_ACCESS_KEY="dummy",
                SPRITE_TOKEN="dummy",
                SPRITES_TOKEN="dummy",
                OP_SERVICE_ACCOUNT_TOKEN="dummy",
                HF_TOKEN="dummy",
            )
            with log.open("w") as handle:
                proc = subprocess.Popen(
                    ["bash", str(ROOT / "scripts" / "serve.sh")],
                    cwd=ROOT,
                    env=env,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                )
            try:
                ready = False
                for _ in range(200):
                    if proc.poll() is not None:
                        break
                    text = log.read_text(errors="replace")
                    if "PREACHED_LISTENING" in text:
                        ready = True
                        break
                    time.sleep(0.1)
                self.assertTrue(ready, log.read_text(errors="replace")[-2000:])
                raw = Path(f"/proc/{proc.pid}/environ").read_bytes()
                names = [
                    entry.split(b"=", 1)[0].decode("ascii", "replace")
                    for entry in raw.split(b"\0")
                    if entry
                ]
                for forbidden in (
                    "FAKE_TOKEN",
                    "AWS_SECRET_ACCESS_KEY",
                    "SPRITE_TOKEN",
                    "SPRITES_TOKEN",
                    "OP_SERVICE_ACCOUNT_TOKEN",
                    "HF_TOKEN",
                ):
                    self.assertNotIn(forbidden, names)
                for required in ("PATH", "HOME", "PREACHED_CACHE", "PREACHED_EMBED_BACKEND"):
                    self.assertIn(required, names)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)

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
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("sample", result.stderr)
        self.assertNotIn(FP32_ONNX_SHA256, result.stderr)

    def test_copy_index_opens_the_source_read_only(self) -> None:
        from scripts.bundle_manifest import copy_index

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.sqlite"
            connection = connect(source)
            _insert(connection, "By grace are ye saved through faith.")
            connection.commit()
            connection.close()
            # A read-write open of a mode 0444 file fails. mode=ro must succeed.
            source.chmod(0o444)
            dest = root / "index" / "wesley.sqlite"
            copy_index(source, dest)
            self.assertEqual(source.stat().st_mode & 0o777, 0o444)
            opened = sqlite3.connect(f"{dest.resolve().as_uri()}?mode=ro", uri=True)
            try:
                count = opened.execute("SELECT count(*) FROM chunks").fetchone()[0]
                journal = opened.execute("PRAGMA journal_mode").fetchone()[0]
            finally:
                opened.close()
            self.assertEqual(count, 1)
            self.assertEqual(journal, "delete")
            self.assertFalse(Path(str(dest) + "-wal").exists())

    def test_deploy_doc_modes_and_the_review_rule(self) -> None:
        text = (ROOT / "docs" / "DEPLOY.md").read_text()
        self.assertNotIn("chmod u=rw,go=r", text)
        self.assertNotIn("repeats the chmod", text)
        self.assertIn("chmod 0755 /srv/preached/<manifest-sha>/scripts/serve.sh", text)
        self.assertIn("chmod 0444 /srv/preached/<manifest-sha>/index/*.sqlite", text)
        self.assertIn(
            "find /srv/preached/<manifest-sha>/model -type f -exec chmod 0444 {} +",
            text,
        )
        self.assertIn("whole recording", text)
        self.assertIn("0.870", text)
        self.assertNotIn("PREACHED_BUNDLE_SKIP_PINS", text)
        self.assertNotIn("pins-skipped", text)
        self.assertIn("refuses to start", text)
        self.assertIn("An index outside the bundle is refused.", text)
        # Round 4: the trust boundary and the release notes.
        self.assertIn("### `.venv` is a trust boundary", text)
        self.assertIn("120 requests per 60 seconds", text)
        for field in ("`disabled`", "`index_version`", "`model_sha256`"):
            self.assertIn(field, text[text.index("## Release notes"):])
        # Round 5: the direct-start guarantees, the import-by-string limit,
        # and the build inputs.
        self.assertIn("### What a direct start does and does not guarantee", text)
        self.assertIn("python -m app.server", text)
        self.assertIn("Known limit: this is a text check", text)
        self.assertIn("### Reproducing a bundle hash", text)
        script = (ROOT / "scripts" / "serve.sh").read_text()
        self.assertNotIn("chmod", script)
        self.assertGreaterEqual(script.count("env -i"), 2)

    def _serve_env(self, **extra: str) -> dict:
        env = os.environ.copy()
        for name in list(env):
            if name.startswith("PREACHED_"):
                env.pop(name)
        env.update(extra)
        return env

    def test_world_writable_bundle_is_refused_not_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "bundle"
            (bundle / "scripts").mkdir(parents=True)
            script = bundle / "scripts" / "serve.sh"
            script.write_bytes((ROOT / "scripts" / "serve.sh").read_bytes())
            script.chmod(0o755)
            (bundle / "src").symlink_to(ROOT / "src")
            (bundle / "app").symlink_to(ROOT / "app")
            (bundle / ".venv").symlink_to(ROOT / ".venv")
            index_dir = bundle / "index"
            index_dir.mkdir()
            index = index_dir / "wesley.sqlite"
            connection = connect(index)
            _insert(connection, "By grace are ye saved through faith.")
            connection.commit()
            connection.close()
            bundle.chmod(0o777)
            index_dir.chmod(0o777)
            index.chmod(0o666)
            before = (
                bundle.stat().st_mode & 0o777,
                index_dir.stat().st_mode & 0o777,
                index.stat().st_mode & 0o777,
            )
            result = subprocess.run(
                ["bash", str(script)],
                cwd=bundle,
                env=self._serve_env(PREACHED_LIBRARY="wesley", PREACHED_HOST="127.0.0.1", PREACHED_PORT="0"),
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            after = (
                bundle.stat().st_mode & 0o777,
                index_dir.stat().st_mode & 0o777,
                index.stat().st_mode & 0o777,
            )
            self.assertEqual(before, (0o777, 0o777, 0o666))
            self.assertEqual(after, before)
            self.assertNotEqual(result.returncode, 0, result.stderr)
            # No build stamp, so app/bundle.py refuses first; either way it
            # is refused and the modes are left as they were.
            self.assertRegex(result.stderr, "writable|refusing to serve")

    def test_preflight_uses_the_scrubbed_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "bundle"
            (bundle / "scripts").mkdir(parents=True)
            script = bundle / "scripts" / "serve.sh"
            script.write_bytes((ROOT / "scripts" / "serve.sh").read_bytes())
            script.chmod(0o755)
            bindir = bundle / ".venv" / "bin"
            bindir.mkdir(parents=True)
            dump = root / "names.txt"
            wrapper = bindir / "python"
            wrapper.write_text(
                "#!/usr/bin/python3\n"
                "import os\n"
                f"open({str(dump)!r}, 'w').write('\\n'.join(sorted(os.environ)))\n"
                "raise SystemExit(86)\n"
            )
            wrapper.chmod(0o755)
            index = bundle / "index" / "wesley.sqlite"
            index.parent.mkdir()
            index.write_bytes(b"not-opened")
            result = subprocess.run(
                ["bash", str(script)],
                cwd=bundle,
                env=self._serve_env(
                    PREACHED_LIBRARY="wesley",
                    FAKE_TOKEN="dummy",
                    AWS_SECRET_ACCESS_KEY="dummy",
                    SPRITE_TOKEN="dummy",
                    SPRITES_TOKEN="dummy",
                    OP_SERVICE_ACCOUNT_TOKEN="dummy",
                    HF_TOKEN="dummy",
                ),
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            self.assertTrue(dump.is_file(), result.stderr)
            names = dump.read_text().splitlines()
            for forbidden in (
                "FAKE_TOKEN",
                "AWS_SECRET_ACCESS_KEY",
                "SPRITE_TOKEN",
                "SPRITES_TOKEN",
                "OP_SERVICE_ACCOUNT_TOKEN",
                "HF_TOKEN",
            ):
                self.assertNotIn(forbidden, names)
            for required in ("PATH", "HOME", "PREACHED_CACHE", "PYTHONPATH", "PREACHED_EMBED_BACKEND"):
                self.assertIn(required, names)
            self.assertNotEqual(result.returncode, 0)

    def _start(self, bundle: Path, **extra: str) -> tuple[bool, int | None, str]:
        """Run the bundle's serve.sh; (listening, exit code or None, output)."""
        log = bundle.parent / f"{bundle.name}.log"
        env = self._serve_env(
            PREACHED_LIBRARY="wesley",
            PREACHED_HOST="127.0.0.1",
            PREACHED_PORT="0",
            **extra,
        )
        with log.open("w") as handle:
            proc = subprocess.Popen(
                ["bash", str(bundle / "scripts" / "serve.sh")],
                cwd=bundle,
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
        try:
            for _ in range(300):
                if proc.poll() is not None:
                    break
                if "PREACHED_LISTENING" in log.read_text(errors="replace"):
                    return True, None, log.read_text(errors="replace")
                time.sleep(0.1)
            return False, proc.poll(), log.read_text(errors="replace")
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)

    def _built_bundle(self, root: Path) -> Path:
        source, onnx_root, index = self._fixture_source(root)
        out = root / "out"
        result = self._build(source, out, onnx_root, index)
        self.assertEqual(result.returncode, 0, result.stderr)
        (out / ".venv").symlink_to(ROOT / ".venv")
        return out

    def _copy(self, bundle: Path, name: str) -> Path:
        dest = bundle.parent / name
        shutil.copytree(bundle, dest, symlinks=True)
        return dest

    def test_bundle_serves_only_with_its_own_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self._built_bundle(root)
            index = out / "index" / "wesley.sqlite"
            self.assertIsNone(bundle_problem(index, root=out))
            listening, _code, log = self._start(out)
            self.assertTrue(listening, log[-2000:])

            missing = self._copy(out, "missing")
            (missing / "MANIFEST.sha256").unlink()
            listening, code, log = self._start(missing)
            self.assertFalse(listening, log[-2000:])
            self.assertNotEqual(code, 0)
            self.assertIn("MANIFEST.sha256 is missing", log)

            outside = root / "elsewhere" / "index" / "wesley.sqlite"
            outside.parent.mkdir(parents=True)
            shutil.copy2(index, outside)
            listening, code, log = self._start(out, PREACHED_INDEX=str(outside))
            self.assertFalse(listening, log[-2000:])
            self.assertNotEqual(code, 0)
            self.assertIn("outside the bundle", log)

    def test_manifest_variants_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self._built_bundle(root)
            text = (out / "MANIFEST.sha256").read_text()
            first = text.splitlines()[0]
            edits = {
                "old marker line": text + "# preached-pins-skipped: 0\n",
                "marker, other spelling": text + "#Preached-Pins-Skipped: 01\n",
                "blank line": text + "\n",
                "trailing space": text.replace(first, first + " ", 1),
                "one space": text.replace(first, first.replace("  ", " ", 1), 1),
                "upper-case hash": text.replace(first, first[:64].upper() + first[64:], 1),
                "no final newline": text[:-1],
                "empty": "",
                "not utf-8": None,
                "repeated line": first + "\n" + text,
                "dot-dot path": text + "0" * 64 + "  ../escape\n",
            }
            for name, body in edits.items():
                with self.subTest(case=name):
                    case = self._copy(out, "case-" + name.replace(" ", "-").replace(",", ""))
                    manifest = case / "MANIFEST.sha256"
                    if body is None:
                        manifest.write_bytes(b"\xff\xfe" + text.encode())
                    else:
                        manifest.write_text(body)
                    problem = bundle_problem(case / "index" / "wesley.sqlite", root=case)
                    self.assertIsNotNone(problem)
                    self.assertIn("refusing to serve", problem)

            tampered = self._copy(out, "tampered")
            (tampered / "search" / "models.toml").write_text("# changed\n")
            problem = bundle_problem(tampered / "index" / "wesley.sqlite", root=tampered)
            self.assertIn("does not match", problem or "")

            extra = self._copy(out, "extra")
            (extra / "src" / "preached" / "sitecustomize.py").write_text("")
            problem = bundle_problem(extra / "index" / "wesley.sqlite", root=extra)
            self.assertIn("not in", problem or "")

            linked = self._copy(out, "linked")
            (linked / "index" / "other.sqlite").symlink_to(out / "index" / "wesley.sqlite")
            problem = bundle_problem(linked / "index" / "other.sqlite", root=linked)
            self.assertIsNotNone(problem)

            # A checkout (no bundle markers) is not checked here.
            self.assertIsNone(bundle_problem(out / "index" / "wesley.sqlite", root=ROOT))

    def test_bundle_import_check_uses_the_bundle_only(self) -> None:
        # Drop a module the server imports. The check runs from the bundle
        # with python -I, so PYTHONPATH at the source tree cannot hide it.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self._built_bundle(root)
            checker = ROOT / "scripts" / "bundle_files.py"
            ok = subprocess.run(
                [sys.executable, "-I", "-B", str(checker), "check", str(out)],
                cwd=out,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(ok.returncode, 0, ok.stderr)
            (out / "src" / "preached" / "audio_policy.py").unlink()
            broken = subprocess.run(
                [sys.executable, "-I", "-B", str(checker), "check", str(out)],
                cwd=out,
                env={**os.environ, "PYTHONPATH": f"{ROOT / 'src'}:{ROOT}"},
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertNotEqual(broken.returncode, 0)
            self.assertIn("audio_policy", broken.stderr)

    # Round 4 (21-W3-DEPLOY-FIX4).

    def _plant_bytecode(
        self, bundle: Path, canary: Path, rel: str = "src/preached/paths.py", target: bytes | None = None, code: bytes | None = None
    ) -> Path:
        """Compile a same-size edit of a shipped module into __pycache__, then
        restore the source with its size and mtime. Returns the .pyc."""
        import py_compile

        source = bundle / rel
        original = source.read_bytes()
        st = source.stat()
        if target is None:
            target = b"# Large data never lives in the git tree. HF_HOME is set in preached.env"
        self.assertIn(target, original)
        if code is None:
            # Relative: a long $TMPDIR path would not fit the comment. The
            # probes run from the directory that holds the canary.
            code = b"open('canary', 'w').close()  #"
        self.assertLessEqual(len(code), len(target))
        modified = original.replace(target, code + b"x" * (len(target) - len(code)), 1)
        self.assertEqual(len(modified), len(original))
        source.chmod(0o644)
        source.write_bytes(modified)
        os.utime(source, ns=(st.st_atime_ns, st.st_mtime_ns))
        # The in-tree path, not importlib.util.cache_from_source: importing
        # app.server sets sys.pycache_prefix in this process too.
        pyc = source.parent / "__pycache__" / f"{source.stem}.{sys.implementation.cache_tag}.pyc"
        py_compile.compile(str(source), cfile=str(pyc), doraise=True)
        source.write_bytes(original)
        os.utime(source, ns=(st.st_atime_ns, st.st_mtime_ns))
        source.chmod(st.st_mode & 0o777)
        return pyc

    def test_planted_bytecode_does_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self._built_bundle(root)
            canary = root / "canary"
            self._plant_bytecode(out, canary)
            probe = [str(ROOT / ".venv" / "bin" / "python"), "-c", "import preached.paths"]
            base = {"PATH": os.environ["PATH"], "PYTHONPATH": f"{out / 'src'}:{out}"}
            # Control: without a cache prefix the planted bytecode does run.
            subprocess.run(probe, cwd=root, env=base, check=True, timeout=60)
            self.assertTrue(canary.exists())
            canary.unlink()
            # serve.sh's PYTHONPYCACHEPREFIX alone stops it.
            prefix = root / "pycache-prefix"
            prefix.mkdir()
            subprocess.run(probe, cwd=root, env={**base, "PYTHONPYCACHEPREFIX": str(prefix)}, check=True, timeout=60)
            self.assertFalse(canary.exists())
            # And the bundle check refuses the tree before anything imports.
            problem = bundle_problem(out / "index" / "wesley.sqlite", root=out)
            self.assertIn("bytecode", problem or "")
            listening, code, log = self._start(out)
            self.assertFalse(listening, log[-2000:])
            self.assertNotEqual(code, 0)
            self.assertIn("bytecode", log)
            self.assertFalse(canary.exists())
            self.assertFalse((out / "canary").exists())
            # A lone .pyc with no __pycache__ directory is refused too.
            loose = self._copy_without_bytecode(out)
            (loose / "src" / "preached" / "paths.pyc").write_bytes(b"")
            self.assertIn("not in", bundle_problem(loose / "index" / "wesley.sqlite", root=loose) or "")

    # Round 5 (30-W3-DEPLOY-FIX5).

    def _direct_start(self, bundle: Path, command: list[str]) -> tuple[bool, int | None, str]:
        """Start app/server.py without serve.sh: no PYTHONPYCACHEPREFIX, no
        stdlib pre-check. (listening, exit code or None, output)."""
        log = bundle.parent / f"{bundle.name}-direct.log"
        env = {
            "PATH": os.environ["PATH"],
            "HOME": os.environ.get("HOME", "/tmp"),
            "PREACHED_CACHE": str(bundle),
            "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
            "UV_OFFLINE": "1",
        }
        args = ["app/server.py", "--index", str(bundle / "index" / "wesley.sqlite"), "--port", "0", "--bm25-only"]
        with log.open("w") as handle:
            proc = subprocess.Popen(command + args, cwd=bundle, env=env, stdout=handle, stderr=subprocess.STDOUT)
        try:
            for _ in range(300):
                if proc.poll() is not None:
                    break
                if "PREACHED_LISTENING" in log.read_text(errors="replace"):
                    return True, None, log.read_text(errors="replace")
                time.sleep(0.1)
            return False, proc.poll(), log.read_text(errors="replace")
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)

    def test_sigterm_during_startup_imports_removes_bytecode_dir(self) -> None:
        # A shadow argparse (first import after the prefix is made) sends the
        # process SIGTERM, as systemd would during a slow start.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shim = root / "shim"
            shim.mkdir()
            (shim / "argparse.py").write_text("import os, signal, time\nos.kill(os.getpid(), signal.SIGTERM)\ntime.sleep(30)\n")
            scratch = root / "tmp"
            scratch.mkdir()
            env = {"PATH": os.environ["PATH"], "PYTHONPATH": str(shim), "TMPDIR": str(scratch)}
            proc = subprocess.run(
                [sys.executable, str(ROOT / "app" / "server.py")], cwd=root, env=env, capture_output=True, timeout=60
            )
            self.assertEqual(proc.returncode, 143, proc.stderr[-2000:])
            self.assertEqual(list(scratch.glob("preached-pycache-*")), [])

    def test_direct_start_ignores_planted_bundle_bytecode(self) -> None:
        # Bytecode for app/bundle.py whose bundle_problem returns None. A
        # direct start imports app.bundle before main() runs the check, so
        # this must not be read.
        python = str(ROOT / ".venv" / "bin" / "python")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self._built_bundle(root)
            canary = out / "canary"
            target = b'    kind = layout(root)\n    if kind == "checkout":\n        return None\n    root = root.resolve()'
            code = b"    return open('canary', 'w').close()  #"
            pyc = self._plant_bytecode(out, canary, rel="app/bundle.py", target=target, code=code)
            self.assertTrue(pyc.is_file())
            # Control: a plain import does load the planted bytecode.
            probe = [python, "-B", "-c", "from app.bundle import bundle_problem; import sys; sys.exit(bundle_problem(sys.argv[1]) is not None)"]
            subprocess.run(probe + [str(out / "index" / "wesley.sqlite")], cwd=out, env={"PATH": os.environ["PATH"]}, check=True, timeout=60)
            self.assertTrue(canary.exists())
            canary.unlink()
            commands = {"python": [python], "python -B": [python, "-B"]}
            if shutil.which("uv"):
                commands["uv run"] = ["uv", "run", "--frozen", "--no-sync", "--no-dev", "--no-default-groups"]
            for name, command in commands.items():
                with self.subTest(launcher=name):
                    listening, code_, log = self._direct_start(out, command)
                    self.assertFalse(listening, log[-2000:])
                    self.assertNotEqual(code_, 0, log[-2000:])
                    self.assertIn("bytecode", log)
                    self.assertFalse(canary.exists())
            # The planted file is still there: the server read none of it and
            # wrote nothing of its own into the tree.
            self.assertTrue(pyc.is_file())
            self.assertEqual(sorted(p.name for p in (out / "app" / "__pycache__").iterdir()), [pyc.name])

    def test_direct_start_bundle_serves_and_leaves_no_temp_dir(self) -> None:
        # Control for the test above: the same clean bundle does start
        # directly, and the per-process bytecode prefix is removed at exit
        # (SIGTERM included).
        python = str(ROOT / ".venv" / "bin" / "python")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self._built_bundle(root)
            scratch = root / "tmp"
            scratch.mkdir()
            with mock.patch.dict(os.environ, {"TMPDIR": str(scratch)}):
                listening, _code, log = self._direct_start(out, [python])
            self.assertTrue(listening, log[-2000:])
            self.assertEqual(list(scratch.iterdir()), [])
            self.assertFalse((out / "app" / "__pycache__").exists())

    def test_server_sets_its_own_bytecode_prefix_before_any_bundle_import(self) -> None:
        text = (ROOT / "app" / "server.py").read_text()
        prefix = text.index("sys.pycache_prefix = ")
        self.assertLess(text.index("sys.dont_write_bytecode = True"), text.index("from app.bundle import"))
        self.assertLess(prefix, text.index("from app.bundle import"))
        self.assertLess(prefix, text.index("from preached"))
        self.assertLess(prefix, text.index("sys.path.insert"))

    def test_serve_sh_leaves_no_temp_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self._built_bundle(root)
            scratch = root / "tmp"
            scratch.mkdir()
            listening, _code, log = self._start(out, TMPDIR=str(scratch))
            self.assertTrue(listening, log[-2000:])
            self.assertEqual(list(scratch.iterdir()), [])
            # A refused start (preflight fails) cleans up too.
            listening, code, log = self._start(out, TMPDIR=str(scratch), PREACHED_ONNX_DIR=str(root))
            self.assertFalse(listening, log[-2000:])
            self.assertNotEqual(code, 0)
            self.assertEqual(list(scratch.iterdir()), [])

    def test_frozen_is_wired_from_main(self) -> None:
        # main passes frozen=True from a bundle and False from a checkout.
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "wesley.sqlite"
            connection = connect(index)
            _insert(connection, "By grace are ye saved through faith.")
            connection.commit()
            connection.close()
            for bundle in (True, False):
                with self.subTest(bundle=bundle):
                    seen = {}

                    def capture(app, host, port):
                        seen["frozen"] = app.frozen
                        raise KeyboardInterrupt

                    with mock.patch("app.server.is_bundle", return_value=bundle), mock.patch(
                        "app.server.bundle_problem", return_value=None
                    ), mock.patch("app.server.onnx_dir_problem", return_value=None), mock.patch(
                        "app.server.make_server", side_effect=capture
                    ), mock.patch.dict(os.environ, {}):
                        with self.assertRaises(KeyboardInterrupt):
                            main(["--index", str(index), "--bm25-only", "--port", "0"])
                    self.assertIs(seen["frozen"], bundle)

    def test_bundle_ships_license_and_notice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self._built_bundle(root)
            names = [line.split("  ", 1)[1] for line in (out / "MANIFEST.sha256").read_text().splitlines()]
            for name in ("LICENSE", "NOTICE"):
                self.assertIn(name, names)
                self.assertEqual((out / name).read_bytes(), (ROOT / name).read_bytes())

    def _copy_without_bytecode(self, bundle: Path) -> Path:
        dest = bundle.parent / f"clean-{len(list(bundle.parent.iterdir()))}"
        shutil.copytree(bundle, dest, symlinks=True, ignore=shutil.ignore_patterns("__pycache__"))
        return dest

    def test_serve_sh_sets_a_fresh_pycache_prefix(self) -> None:
        text = (ROOT / "scripts" / "serve.sh").read_text()
        self.assertIn('PYCACHE=$(mktemp -d', text)
        self.assertIn('"PYTHONPYCACHEPREFIX=${PYCACHE}" "$PY"', text)
        # Removed before the exec; the server sets its own (app/server.py).
        self.assertNotIn("pass PYTHONPYCACHEPREFIX", text)
        self.assertLess(text.index('rm -rf -- "$PYCACHE"\ntrap - EXIT'), text.index('exec env -i'))
        # The stdlib check runs, isolated, before the preflight imports app.server.
        check = text.index('-I -B "$ROOT/app/bundle.py"')
        self.assertLess(check, text.index("from app.server import check_servable"))
        server = (ROOT / "app" / "bundle.py").read_text()
        imports = {
            line.split()[1].split(".")[0]
            for line in server.splitlines()
            if line.startswith(("import ", "from "))
        }
        self.assertLessEqual(imports, {"__future__", "hashlib", "os", "re", "stat", "sys", "pathlib"})

    def test_bundle_needs_its_listed_stamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self._built_bundle(root)
            self.assertTrue((out / "PREACHED_BUNDLE").is_file())
            self.assertIn("  PREACHED_BUNDLE\n", (out / "MANIFEST.sha256").read_text())

            no_stamp = self._copy(out, "no-stamp")
            (no_stamp / "PREACHED_BUNDLE").unlink()
            problem = bundle_problem(no_stamp / "index" / "wesley.sqlite", root=no_stamp)
            self.assertIn("no build stamp", problem or "")
            listening, code, log = self._start(no_stamp)
            self.assertFalse(listening, log[-2000:])
            self.assertIn("no build stamp", log)

            # Every marker gone: still not a checkout, because there is no .git.
            bare = self._copy(out, "bare")
            for name in ("PREACHED_BUNDLE", "MANIFEST.sha256", "requirements-serve.txt"):
                (bare / name).unlink()
            shutil.rmtree(bare / "model")
            index = root / "loose" / "wesley.sqlite"
            index.parent.mkdir()
            shutil.move(bare / "index" / "wesley.sqlite", index)
            (bare / "index").rmdir()
            problem = bundle_problem(index, root=bare)
            self.assertIn("not a git checkout", problem or "")
            listening, code, log = self._start(bare, PREACHED_INDEX=str(index))
            self.assertFalse(listening, log[-2000:])
            self.assertIn("not a git checkout", log)

            # .git plus a bundle marker is not a checkout either.
            mixed = self._copy(out, "mixed")
            (mixed / "PREACHED_BUNDLE").unlink()
            (mixed / ".git").mkdir()
            self.assertIn("no build stamp", bundle_problem(mixed / "index" / "wesley.sqlite", root=mixed) or "")

            unlisted = self._copy(out, "unlisted")
            manifest = unlisted / "MANIFEST.sha256"
            manifest.write_text(
                "".join(line for line in manifest.read_text().splitlines(keepends=True) if not line.endswith("  PREACHED_BUNDLE\n"))
            )
            self.assertIn("is not in", bundle_problem(unlisted / "index" / "wesley.sqlite", root=unlisted) or "")

            edited = self._copy(out, "edited")
            (edited / "PREACHED_BUNDLE").write_text("something else\n")
            self.assertIn("does not match", bundle_problem(edited / "index" / "wesley.sqlite", root=edited) or "")

    def test_bundle_refuses_another_onnx_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = self._built_bundle(root)
            self.assertIsNone(onnx_dir_problem(out, None))
            self.assertIsNone(onnx_dir_problem(out, str(out / "model")))
            other = root / "rollback"
            shutil.copytree(out / "model", other)
            self.assertIn("own model directory", onnx_dir_problem(out, str(other)) or "")
            # A checkout may point anywhere.
            self.assertIsNone(onnx_dir_problem(ROOT, str(other)))
            listening, code, log = self._start(out, PREACHED_ONNX_DIR=str(other))
            self.assertFalse(listening, log[-2000:])
            self.assertNotEqual(code, 0)
            self.assertIn("own model directory", log)
            listening, _code, log = self._start(out, PREACHED_ONNX_DIR=str(out / "model"))
            self.assertTrue(listening, log[-2000:])

    def test_build_fails_on_import_by_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, onnx_root, index = self._fixture_source(root)
            lister = [sys.executable, "-I", "-B", str(source / "scripts" / "bundle_files.py"), "list", str(source)]
            ok = subprocess.run(lister, capture_output=True, text=True, check=False, timeout=60)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            rank = source / "src" / "preached" / "rank.py"
            original = rank.read_text()
            for name, line in {
                "import importlib": "import importlib\n",
                "from importlib": "from importlib import import_module\n",
                "__import__": "def _late():\n    return __import__('preached.embed')\n",
                "builtins attr": "import builtins\n_load = builtins.__import__\n",
            }.items():
                with self.subTest(case=name):
                    rank.write_text(original + "\n" + line)
                    bad = subprocess.run(lister, capture_output=True, text=True, check=False, timeout=60)
                    self.assertNotEqual(bad.returncode, 0)
                    self.assertIn("imports by string", bad.stderr)
                    self.assertIn("rank.py", bad.stderr)
            rank.write_text(original + "\nimport importlib\n")
            result = self._build(source, root / "out", onnx_root, index)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("imports by string", result.stderr)

    def test_identity_is_taken_before_the_hash(self) -> None:
        # A swap of the index while the bundle is being hashed is caught by
        # the identity check: the identity was read before bundle_problem.
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "wesley.sqlite"
            connection = connect(index)
            _insert(connection, "By grace are ye saved through faith.")
            connection.commit()
            connection.close()
            replacement = Path(tmp) / "other.sqlite"
            shutil.copy2(index, replacement)

            def swap(_index, root=None):
                os.replace(replacement, index)
                return None

            with mock.patch("app.server.bundle_problem", side_effect=swap), mock.patch(
                "app.server.make_server", side_effect=AssertionError("served a swapped index")
            ):
                with self.assertRaises(SystemExit) as caught:
                    main(["--index", str(index), "--bm25-only", "--port", "0"])
            self.assertIn("replaced", str(caught.exception.code))


class UnreadBodyTests(unittest.TestCase):
    def test_unread_body_is_not_parsed_as_a_request(self) -> None:
        port, _app, _server = RateAndKillTests._serve(self)
        smuggled = b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"

        def read_until_close(payload: bytes) -> tuple[bytes, bool]:
            with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
                sock.sendall(payload)
                sock.settimeout(2)
                data = b""
                closed = False
                while True:
                    try:
                        block = sock.recv(4096)
                    except socket.timeout:
                        break
                    if not block:
                        closed = True
                        break
                    data += block
                return data, closed

        def statuses(data: bytes) -> list[bytes]:
            return [line for line in data.split(b"\r\n") if line.startswith(b"HTTP/1.1 ")]

        post = (
            b"POST /healthz HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Length: " + str(len(smuggled)).encode("ascii") + b"\r\n"
            b"\r\n" + smuggled
        )
        data, closed = read_until_close(post)
        found = statuses(data)
        self.assertEqual(len(found), 1, data)
        self.assertTrue(found[0].startswith(b"HTTP/1.1 405"), data)
        self.assertIn(b"Connection: close", data)
        self.assertTrue(closed, data)
        self.assertNotIn(b"HTTP/1.1 200", data)

        early = (
            b"POST /healthz HTTP/1.1\r\n"
            b"Host: evil.example\r\n"
            b"Content-Length: " + str(len(smuggled)).encode("ascii") + b"\r\n"
            b"\r\n" + smuggled
        )
        data, closed = read_until_close(early)
        found = statuses(data)
        self.assertEqual(len(found), 1, data)
        self.assertTrue(found[0].startswith(b"HTTP/1.1 421"), data)
        self.assertIn(b"Connection: close", data)
        self.assertTrue(closed, data)
        self.assertNotIn(b"HTTP/1.1 200", data)

        too_big = (
            b"GET /healthz HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Length: 99999\r\n"
            b"\r\n" + smuggled
        )
        data, closed = read_until_close(too_big)
        found = statuses(data)
        self.assertEqual(len(found), 1, data)
        self.assertTrue(found[0].startswith(b"HTTP/1.1 413"), data)
        self.assertIn(b"Connection: close", data)
        self.assertTrue(closed, data)
        self.assertNotIn(b"HTTP/1.1 200", data)


class FramingTests(unittest.TestCase):
    """Raw-socket desync cases: each must get one reply and a closed socket."""

    SMUGGLED = b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"

    def _exchange(self, port: int, payload: bytes) -> tuple[list[bytes], bytes, bool]:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            sock.sendall(payload)
            sock.settimeout(2)
            data = b""
            closed = False
            while True:
                try:
                    block = sock.recv(4096)
                except socket.timeout:
                    break
                if not block:
                    closed = True
                    break
                data += block
        # A pipelined reply follows the previous body with no CRLF, so count
        # status lines anywhere in the stream.
        found = re.findall(rb"HTTP/1\.1 [0-9]{3}", data)
        return found, data, closed

    def test_plain_zero_length_keeps_the_connection(self) -> None:
        # Control: the smuggled request IS parsed when the framing is clean,
        # so the refusals below are not an artifact of the test.
        port, _app, _server = RateAndKillTests._serve(self)
        payload = (
            b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\n\r\n" + self.SMUGGLED
        )
        found, data, _closed = self._exchange(port, payload)
        self.assertEqual(len(found), 2, data)
        self.assertTrue(all(line.startswith(b"HTTP/1.1 200") for line in found), data)

    def test_ambiguous_framing_is_refused_and_closed(self) -> None:
        port, _app, _server = RateAndKillTests._serve(self)
        cases = {
            "duplicate content-length": b"Content-Length: 0\r\nContent-Length: 0\r\n",
            "duplicate content-length, different": b"Content-Length: 0\r\nContent-Length: 45\r\n",
            "plus sign": b"Content-Length: +0\r\n",
            "minus sign": b"Content-Length: -0\r\n",
            "comma list": b"Content-Length: 0, 0\r\n",
            "hex": b"Content-Length: 0x0\r\n",
            "underscore": b"Content-Length: 0_0\r\n",
            "empty content-length": b"Content-Length:\r\n",
            "empty transfer-encoding": b"Transfer-Encoding:\r\n",
            "chunked": b"Transfer-Encoding: chunked\r\n",
            "identity": b"Transfer-Encoding: identity\r\n",
            "lower-case transfer-encoding": b"transfer-encoding: chunked\r\n",
            "transfer-encoding and length": b"Transfer-Encoding: chunked\r\nContent-Length: 0\r\n",
            "space before colon": b"Content-Length : 0\r\n",
            "obs-fold": b"X-Note: a\r\n Content-Length: 0\r\n",
        }
        for method in (b"GET", b"POST", b"BREW"):
            for name, header in cases.items():
                with self.subTest(method=method, case=name):
                    payload = (
                        method + b" /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\n" + header + b"\r\n" + self.SMUGGLED
                    )
                    found, data, closed = self._exchange(port, payload)
                    self.assertEqual(len(found), 1, data)
                    self.assertTrue(
                        found[0].startswith(b"HTTP/1.1 400") or found[0].startswith(b"HTTP/1.1 501"),
                        data,
                    )
                    self.assertIn(b"Connection: close", data)
                    self.assertTrue(closed, data)
                    self.assertNotIn(b"HTTP/1.1 200", data)


class FrozenIndexTests(unittest.TestCase):
    """A bundle's App (frozen=True) refuses an index changed after start."""

    def _write(self, app: App) -> None:
        path = app.connection.execute("PRAGMA database_list").fetchone()[2]
        other = sqlite3.connect(path)
        other.execute(
            """
            INSERT INTO chunks (chunk_id, sermon_id, sermon_title, text, sermon_number, word_count)
            VALUES ('wesley-002-c0000', 'wesley-002', 'Added', 'zealboundary added later', 2, 3)
            """
        )
        other.commit()
        other.close()

    def test_bundle_refuses_an_index_change_until_restart(self) -> None:
        port, app, _server = RateAndKillTests._serve(self, frozen=True)
        status, _, _ = _request(port, "/healthz")
        self.assertEqual(status, 200)
        status, _, _ = _request(port, "/api/search?q=zealboundary")
        self.assertEqual(status, 200)
        self._write(app)
        for path in ("/healthz", "/api/search?q=zealboundary", "/healthz"):
            status, _, body = _request(port, path)
            self.assertEqual(status, 503, (path, body))
            self.assertNotIn("restart", body.decode() if isinstance(body, bytes) else str(body))
        self.assertIsNone(app.searcher)

    def test_bundle_refuses_an_in_place_chunk_edit(self) -> None:
        # Same row count, same chunks_sha256 meta row: index_stamp does not
        # change. Only PRAGMA data_version sees this commit.
        port, app, _server = RateAndKillTests._serve(self, frozen=True)
        status, _, _ = _request(port, "/api/search?q=zealboundary")
        self.assertEqual(status, 200)
        stamp = app._stamp
        path = app.connection.execute("PRAGMA database_list").fetchone()[2]
        other = sqlite3.connect(path)
        other.execute("UPDATE chunks SET text = 'zealboundary edited in place'")
        other.commit()
        other.close()
        self.assertEqual(app._capture_stamp(), stamp)
        status, _, body = _request(port, "/api/search?q=zealboundary")
        self.assertEqual(status, 503, body)
        self.assertIsNone(app.searcher)

    def test_checkout_reloads_an_index_change(self) -> None:
        # Control: the same write is reloaded when not serving from a bundle.
        port, app, _server = RateAndKillTests._serve(self)
        self._write(app)
        status, _, _ = _request(port, "/healthz")
        self.assertEqual(status, 200)
        status, _, body = _request(port, "/api/search?q=added")
        self.assertEqual(status, 200)
        self.assertIn("wesley-002", body.decode() if isinstance(body, bytes) else str(body))


class ControlCharacterTests(unittest.TestCase):
    """RFC 9110 5.5: no NUL or control characters in headers or the request line."""

    def test_controls_are_refused_and_closed(self) -> None:
        port, _app, _server = RateAndKillTests._serve(self)
        exchange = FramingTests._exchange
        cases = {
            "NUL in header value": b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Note: a\x00b\r\n\r\n",
            "SOH in header value": b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Note: a\x01b\r\n\r\n",
            "VT in header value": b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Note: a\x0bb\r\n\r\n",
            "DEL in header value": b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Note: a\x7fb\r\n\r\n",
            "NUL in Host": b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\x00\r\n\r\n",
            "bare CR in header value": b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Note: a\rb\r\n\r\n",
            "NUL in target": b"GET /healthz\x00 HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
            "TAB in target": b"GET /health\tz HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
            "NUL in method": b"G\x00ET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
            "ESC in version": b"GET /healthz HTTP/1.1\x1b\r\nHost: 127.0.0.1\r\n\r\n",
            "bare CR in request line": b"GET /healthz\rX HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n",
        }
        for name, payload in cases.items():
            with self.subTest(case=name):
                found, data, closed = exchange(self, port, payload + FramingTests.SMUGGLED)
                self.assertEqual(len(found), 1, data)
                self.assertTrue(found[0].startswith(b"HTTP/1.1 400"), data)
                self.assertTrue(closed, data)

    def test_tab_and_obs_text_in_a_value_are_allowed(self) -> None:
        port, _app, _server = RateAndKillTests._serve(self)
        payload = b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Note: a\tb \xe9\r\n\r\n"
        found, data, _closed = FramingTests._exchange(self, port, payload)
        self.assertEqual(len(found), 1, data)
        self.assertTrue(found[0].startswith(b"HTTP/1.1 200"), data)


if __name__ == "__main__":
    unittest.main()
