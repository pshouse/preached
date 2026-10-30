"""Serve-time footprint, health identity, and the deploy bundle."""

from __future__ import annotations

import json
import os
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
    RateLimiter,
    main,
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
            raw.recv(400)
            raw.close()
        joined = "\n".join(logs.output)
        self.assertIn("\\x01", joined)
        self.assertNotIn("\x01", joined)
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
        connection = connect(index)
        _insert(connection, "By grace are ye saved through faith.")
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
            # Stand-in models skip the pin check, and the manifest says so.
            # sha256sum -c ignores the comment line.
            self.assertIn("# preached-pins-skipped: 1\n", manifest_a.decode())
            names = [
                line.split("  ", 1)[1].strip()
                for line in manifest_a.decode().splitlines()
                if "  " in line and not line.startswith("#")
            ]
            joined = "\n".join(names)
            self.assertIn(f"model/{GRANITE_REVISION}/model.fp32.onnx", names)
            self.assertIn("index/wesley.sqlite", names)
            self.assertIn("requirements-serve.txt", names)
            self.assertIn("app/server.py", names)
            self.assertIn("src/preached/libraries.py", names)
            self.assertIn("ingest/manifest/spurgeon.provenance.json", names)
            self.assertIn("ingest/manifest/edwards.provenance.json", names)
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

    def test_int8_is_removed_from_the_bundled_manifest(self) -> None:
        script = ROOT / "scripts" / "build-bundle.sh"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            onnx_root, index = self._stand_in(root)
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
            result = subprocess.run(
                ["bash", str(script), str(out)],
                cwd=ROOT,
                env=self._env(
                    PREACHED_LIBRARY="wesley",
                    PREACHED_INDEX=str(index),
                    PREACHED_ONNX_DIR=str(onnx_root),
                ),
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            shipped = json.loads((out / "model" / GRANITE_REVISION / "manifest.json").read_text())
            self.assertNotIn("int8", shipped["variants"])
            self.assertNotIn("model.int8.onnx", shipped["files"])
            self.assertFalse((out / "model" / GRANITE_REVISION / "model.int8.onnx").exists())

    def test_skip_pins_is_ignored_outside_the_tests(self) -> None:
        script = ROOT / "scripts" / "build-bundle.sh"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            onnx_root, index = self._stand_in(root)
            out = root / "out"
            # Parent of the build script is bash, not the unittest process.
            # `set -e` keeps the build script's status; a trailing `true`
            # stops bash from exec-replacing itself with the script, which
            # would make PPID the unittest process and skip the pins.
            result = subprocess.run(
                ["bash", "-c", 'set -e; bash "$1" "$2"; true', "bash", str(script), str(out)],
                cwd=ROOT,
                env=self._env(
                    PREACHED_LIBRARY="wesley",
                    PREACHED_INDEX=str(index),
                    PREACHED_ONNX_DIR=str(onnx_root),
                    PREACHED_BUNDLE_SKIP_PINS="1",
                ),
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pin", result.stderr)

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
        self.assertIn("preached-pins-skipped", text)
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
            self.assertIn("writable", result.stderr)

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

    def test_skipped_pins_are_recorded_and_refused_outside_the_tests(self) -> None:
        from app.server import check_servable
        from preached.store import open_readonly

        script = ROOT / "scripts" / "build-bundle.sh"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            onnx_root, index = self._stand_in(root)
            out = root / "out"
            # Parent cmdline contains "unittest" but the parent is bash -c,
            # not the test runner. That is enough to skip the pins today.
            # The manifest has to record the skip, and a server that is not
            # the test process has to refuse the bundle.
            built = subprocess.run(
                [
                    "bash",
                    "-c",
                    'set -e; bash "$1" "$2"; true',
                    "python -m unittest test_deploy",
                    str(script),
                    str(out),
                ],
                cwd=ROOT,
                env=self._env(
                    PREACHED_LIBRARY="wesley",
                    PREACHED_INDEX=str(index),
                    PREACHED_ONNX_DIR=str(onnx_root),
                    PREACHED_BUNDLE_SKIP_PINS="1",
                ),
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(built.returncode, 0, built.stderr)
            manifest = (out / "MANIFEST.sha256").read_text()
            self.assertIn("# preached-pins-skipped: 1\n", manifest)
            checked = subprocess.run(
                ["sha256sum", "-c", "MANIFEST.sha256"],
                cwd=out,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            bundled = out / "index" / "wesley.sqlite"
            # This process is the unit-test runner, so the gate allows it.
            connection = open_readonly(bundled, check_same_thread=False)
            try:
                check_servable(connection, "wesley", bundled)
            finally:
                connection.close()
            probe = (
                "import sys\n"
                "from pathlib import Path\n"
                "root = Path(sys.argv[1])\n"
                "sys.path[:0] = [str(root), str(root / 'src')]\n"
                "from app.server import check_servable\n"
                "from preached.store import open_readonly\n"
                "index = Path(sys.argv[2])\n"
                "connection = open_readonly(index, check_same_thread=False)\n"
                "try:\n"
                "    check_servable(connection, 'wesley', index)\n"
                "finally:\n"
                "    connection.close()\n"
                "print('served')\n"
            )
            refused = subprocess.run(
                [sys.executable, "-c", probe, str(ROOT), str(bundled)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertNotEqual(refused.returncode, 0, refused.stderr)
            self.assertIn("pins", refused.stderr)
            self.assertNotIn("served", refused.stdout)
            (out / ".venv").symlink_to(ROOT / ".venv")
            served = subprocess.run(
                ["bash", str(out / "scripts" / "serve.sh")],
                cwd=out,
                env=self._serve_env(
                    PREACHED_LIBRARY="wesley",
                    PREACHED_HOST="127.0.0.1",
                    PREACHED_PORT="0",
                ),
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertNotEqual(served.returncode, 0, served.stderr)
            self.assertIn("preached-pins-skipped", served.stderr)
            self.assertNotIn("PREACHED_LISTENING", served.stdout + served.stderr)


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


if __name__ == "__main__":
    unittest.main()
