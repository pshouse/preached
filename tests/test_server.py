"""HTTP API, static allowlist, headers, and the BM25 fallback."""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import json
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

from app.server import (
    CSP,
    FALLBACK_NOTE,
    INDEX_READ_NOTE,
    STALE_NOTE,
    MAX_BODY,
    MAX_TARGET,
    REQUEST_TIMEOUT_S,
    STATIC_DIR,
    App,
    Searcher,
    build_app,
    hit_dict,
    load_search,
    make_server,
)
from preached.models import MODELS
from preached.store import connect, save_embedding_info, write_embeddings

FIXTURE_FP = "fixture-fingerprint"

COLUMNS = (
    "chunk_id",
    "sermon_id",
    "sermon_title",
    "text",
    "start_s",
    "end_s",
    "sermon_number",
    "scripture",
    "source_url",
    "word_count",
    "word_start",
    "word_end",
    "librivox_id",
)

AUDIO = "https://archive.org/download/sermonsfirstseries_1307_librivox/example.mp3"
CCEL = "https://ccel.org/ccel/wesley/sermons/sermons.v.i.html"
RESULT_KEYS = {
    "chunk_id",
    "chunk_ids",
    "sermon_id",
    "sermon_number",
    "sermon_title",
    "scripture",
    "text",
    "start_s",
    "end_s",
    "audio_url",
    "reader",
    "text_source",
    "source_url",
    "score",
}


def _insert(connection, **overrides) -> None:
    row = {
        "chunk_id": "wesley-001-c0000",
        "sermon_id": "wesley-001",
        "sermon_title": "Salvation by Faith",
        "text": "By grace are ye saved through faith.",
        "start_s": None,
        "end_s": None,
        "sermon_number": 1,
        "scripture": "Eph 2:8",
        "source_url": CCEL,
        "word_count": 6,
        "word_start": 0,
        "word_end": 6,
        "librivox_id": "sermonsfirstseries_1307_librivox",
    }
    row.update(overrides)
    names = ", ".join(COLUMNS)
    places = ", ".join(":" + name for name in COLUMNS)
    connection.execute(f"INSERT INTO chunks ({names}) VALUES ({places})", row)


def _shared() -> str:
    return " ".join(f"shared{i}" for i in range(12))


def build_rich_index(path: Path) -> None:
    connection = connect(path)
    shared = _shared()
    _insert(
        connection,
        chunk_id="keep",
        text=("zealboundary " * 8) + "alpha passage about grace. " + shared,
        word_start=0,
        word_end=100,
        word_count=40,
    )
    _insert(
        connection,
        chunk_id="neighbor",
        text=shared + " beta passage continues the same sermon zealboundary.",
        word_start=80,
        word_end=160,
        word_count=30,
    )
    _insert(
        connection,
        chunk_id="later",
        text="zealboundary gamma passage stands apart in this sermon.",
        word_start=400,
        word_end=480,
        word_count=8,
    )
    _insert(
        connection,
        chunk_id="other",
        sermon_id="wesley-002",
        sermon_number=2,
        sermon_title="The Almost Christian",
        scripture="Acts 26:28",
        text="zealboundary delta passage is a different sermon entirely.",
        word_start=0,
        word_end=80,
        word_count=8,
    )
    _insert(
        connection,
        chunk_id="null-time",
        text="nulltimingtoken and the printed words have no clock yet.",
        start_s=None,
        end_s=None,
        word_start=500,
        word_end=540,
    )
    _insert(
        connection,
        chunk_id="timed",
        sermon_id="wesley-002",
        sermon_number=2,
        sermon_title="The Almost Christian",
        text="timedtoken begins at a known second in the reading.",
        start_s=95,
        end_s=140,
        word_start=200,
        word_end=240,
    )
    _insert(
        connection,
        chunk_id="markup",
        text='markuptoken He said <script>alert(1)</script> & "more".',
        word_start=600,
        word_end=620,
    )
    connection.commit()
    # connect() creates audio_url, reader and text_source (W1-C).
    connection.execute(
        "UPDATE chunks SET audio_url = ?, reader = ?, text_source = ? WHERE chunk_id = ?",
        (AUDIO, "A. Volunteer", "canonical", "null-time"),
    )
    connection.execute(
        "UPDATE chunks SET audio_url = ?, reader = ?, text_source = ? WHERE chunk_id = ?",
        (AUDIO, "A. Volunteer", "asr", "timed"),
    )
    connection.commit()
    rows = connection.execute("SELECT rowid FROM chunks ORDER BY rowid").fetchall()
    matrix = np.zeros((len(rows), 4), dtype=np.float32)
    for index, _row in enumerate(rows):
        matrix[index, index % 4] = 1.0
    write_embeddings(connection, "fixture", [int(row[0]) for row in rows], matrix)
    save_embedding_info(connection, "fixture", {"fingerprint": FIXTURE_FP})
    # Granite vectors from an older revision: the fingerprint no longer matches models.toml.
    write_embeddings(connection, "granite-english-r2", [int(row[0]) for row in rows], matrix)
    save_embedding_info(connection, "granite-english-r2", {"fingerprint": "older-revision"})
    connection.close()


def reopen(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def encode_fixture(_query: str) -> np.ndarray:
    return np.array([1, 0, 0, 0], dtype=np.float32)


class Running:
    def __init__(self, app: App):
        self.server = make_server(app, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        deadline = time.monotonic() + 5
        while True:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/healthz", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.02)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def request(self, method: str, path: str, headers: dict | None = None, host: str | None = None):
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        if host is None:
            conn.request(method, path, headers=headers or {})
        else:
            conn.putrequest(method, path, skip_host=True)
            conn.putheader("Host", host)
            for key, value in (headers or {}).items():
                conn.putheader(key, value)
            conn.endheaders()
        response = conn.getresponse()
        body = response.read()
        header_map = {key: value for key, value in response.getheaders()}
        status = response.status
        conn.close()
        return status, header_map, body


def header(headers: dict, name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    raise AssertionError(f"missing header {name}")


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.rich_path = root / "rich.sqlite"
        cls.plain_path = root / "plain.sqlite"
        build_rich_index(cls.rich_path)
        plain = connect(cls.plain_path)
        _insert(plain, chunk_id="plain", text="plainword without any audio columns at all.")
        plain.commit()
        plain.close()

        rich = reopen(cls.rich_path)
        cls.rich_app = App(
            connection=rich,
            searcher=Searcher(rich, model="fixture", fingerprint=FIXTURE_FP),
            encode=encode_fixture,
            fallback_note=None,
            model_name="fixture",
            hosts={"127.0.0.1", "localhost"},
            static_dir=STATIC_DIR,
        )
        cls.rich = Running(cls.rich_app)

        failed = reopen(cls.rich_path)

        def boom(_connection, _model_key):
            raise RuntimeError("SECRET weights path")

        searcher, encode, note = load_search(failed, "granite-english-r2", loader=boom)
        cls.fallback_note = note
        cls.fallback_encode = encode
        cls.fallback_app = App(
            connection=failed,
            searcher=searcher,
            encode=encode,
            fallback_note=note,
            model_name="granite-english-r2",
            hosts={"127.0.0.1", "localhost"},
            static_dir=STATIC_DIR,
        )
        cls.fallback = Running(cls.fallback_app)

        plain_conn = reopen(cls.plain_path)
        cls.plain_app = build_app(
            plain_conn,
            model_key="granite-english-r2",
            bm25_only=True,
            hosts={"127.0.0.1", "localhost"},
            static_dir=STATIC_DIR,
        )
        cls.plain = Running(cls.plain_app)

    @classmethod
    def tearDownClass(cls) -> None:
        for running in (cls.rich, cls.fallback, cls.plain):
            running.close()
        cls.tmp.cleanup()

    def get(self, path: str, running: Running | None = None, host: str | None = None):
        return (running or self.rich).request("GET", path, host=host)

    def assert_secure(self, headers: dict) -> None:
        csp = header(headers, "Content-Security-Policy")
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("default-src 'self'", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertNotIn("unsafe-eval", csp)
        self.assertEqual(header(headers, "X-Content-Type-Options"), "nosniff")
        self.assertEqual(header(headers, "Referrer-Policy"), "no-referrer")
        self.assertEqual(header(headers, "X-Frame-Options"), "DENY")
        server = header(headers, "Server")
        self.assertEqual(server, "Preached")
        self.assertNotIn("Python", server)

    def test_health_and_page(self) -> None:
        status, headers, body = self.get("/healthz")
        self.assertEqual(status, 200)
        self.assert_secure(headers)
        health = json.loads(body)
        self.assertTrue(health["ok"])
        self.assertEqual(health["library"], "wesley")
        self.assertGreater(health["chunks"], 0)
        self.assertTrue(health["dense"])
        self.assertFalse(health["fallback"])
        self.assertIn("index_version", health)
        self.assertIn("model_sha256", health)
        for value in health.values():
            if isinstance(value, str):
                self.assertNotIn("/", value)
                self.assertNotIn("\\", value)
                self.assertNotIn(".sqlite", value)

        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"text/html", header(headers, "Content-Type").encode())
        self.assertIn(b"Preached finds passages", body)
        self.assert_secure(headers)

    def test_result_schema_and_modes(self) -> None:
        status, headers, body = self.get("/api/search?q=zealboundary&k=5&mode=bm25&library=wesley")
        self.assertEqual(status, 200)
        self.assert_secure(headers)
        self.assertIn("application/json", header(headers, "Content-Type"))
        payload = json.loads(body)
        self.assertEqual(set(payload), {"query", "mode", "took_ms", "results", "note", "abstain", "confidence"})
        self.assertEqual(payload["query"], "zealboundary")
        self.assertEqual(payload["mode"], "bm25")
        self.assertIsNone(payload["note"])
        self.assertIsInstance(payload["took_ms"], int)
        self.assertGreaterEqual(payload["took_ms"], 0)
        self.assertGreaterEqual(len(payload["results"]), 1)
        for result in payload["results"]:
            self.assertEqual(set(result), RESULT_KEYS)

        status, _, body = self.get("/api/search?q=zealboundary&mode=hybrid")
        hybrid = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(hybrid["mode"], "hybrid")
        self.assertIsNone(hybrid["note"])
        self.assertGreaterEqual(len(hybrid["results"]), 1)

        status, _, body = self.get("/api/search?q=zealboundary&mode=dense&k=3")
        dense = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(dense["mode"], "dense")
        self.assertLessEqual(len(dense["results"]), 3)

    def test_defaults_and_validation(self) -> None:
        status, _, body = self.get("/api/search?q=zealboundary")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["mode"], "hybrid")
        self.assertLessEqual(len(payload["results"]), 10)

        cases = [
            "/api/search",
            "/api/search?q=",
            "/api/search?q=%20%20",
            "/api/search?q=" + ("a" * 301),
            "/api/search?q=zealboundary&k=0",
            "/api/search?q=zealboundary&k=26",
            "/api/search?q=zealboundary&k=1.5",
            "/api/search?q=zealboundary&k=no",
            "/api/search?q=zealboundary&mode=semantic",
            "/api/search?q=zealboundary&mode=Hybrid",
            "/api/search?q=zealboundary&library=spurgeon",
            "/api/search?q=bad%0Aline",
        ]
        for path in cases:
            status, headers, body = self.get(path)
            self.assertEqual(status, 400, path)
            self.assert_secure(headers)
            self.assertIn("error", json.loads(body))
            self.assertNotIn(b"Traceback", body)

        status, _, body = self.get("/api/search?q=" + ("e" * 300) + "&k=1&mode=bm25")
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["results"], [])

    def test_null_timestamps_and_markup(self) -> None:
        status, _, body = self.get("/api/search?q=nulltimingtoken&mode=bm25")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["results"]), 1)
        hit = payload["results"][0]
        self.assertIsNone(hit["start_s"])
        self.assertIsNone(hit["end_s"])
        self.assertEqual(hit["audio_url"], AUDIO)
        self.assertEqual(hit["reader"], "A. Volunteer")
        self.assertEqual(hit["text_source"], "canonical")
        self.assertEqual(hit["source_url"], CCEL)

        status, _, body = self.get("/api/search?q=timedtoken&mode=bm25")
        timed = json.loads(body)["results"][0]
        self.assertEqual(timed["start_s"], 95)
        self.assertEqual(timed["end_s"], 140)
        self.assertEqual(timed["text_source"], "asr")
        self.assertEqual(timed["audio_url"], AUDIO)

        status, _, body = self.get("/api/search?q=markuptoken&mode=bm25")
        text = json.loads(body)["results"][0]["text"]
        self.assertIn("<script>alert(1)</script>", text)

    def test_missing_audio_columns_are_null(self) -> None:
        status, _, body = self.plain.request("GET", "/api/search?q=plainword&mode=bm25")
        self.assertEqual(status, 200)
        hit = json.loads(body)["results"][0]
        self.assertIsNone(hit["start_s"])
        self.assertIsNone(hit["end_s"])
        self.assertIsNone(hit["audio_url"])
        self.assertIsNone(hit["reader"])
        self.assertIsNone(hit["text_source"])
        self.assertEqual(hit["sermon_number"], 1)

    def test_dedupe_on_the_api(self) -> None:
        status, _, body = self.get("/api/search?q=zealboundary&k=10&mode=bm25")
        ids = [hit["chunk_id"] for hit in json.loads(body)["results"]]
        self.assertEqual(status, 200)
        self.assertIn("keep", ids)
        self.assertIn("later", ids)
        self.assertIn("other", ids)
        self.assertNotIn("neighbor", ids)

    def test_sermon_metadata(self) -> None:
        status, headers, body = self.get("/api/sermon/wesley-001")
        self.assertEqual(status, 200)
        self.assert_secure(headers)
        meta = json.loads(body)
        self.assertEqual(meta["sermon_id"], "wesley-001")
        self.assertEqual(meta["sermon_number"], 1)
        self.assertEqual(meta["sermon_title"], "Salvation by Faith")
        self.assertEqual(meta["scripture"], "Eph 2:8")
        self.assertEqual(meta["source_url"], CCEL)
        self.assertEqual(meta["audio_url"], AUDIO)
        self.assertEqual(meta["reader"], "A. Volunteer")

        status, _, body = self.get("/api/sermon/wesley-999")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "not found")

        for path in ("/api/sermon/../pyproject.toml", "/api/sermon/Wesley-001", "/api/sermon/%2e%2e"):
            status, _, body = self.get(path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"pyproject", body.lower())

    def test_static_allowlist_and_traversal(self) -> None:
        status, headers, body = self.get("/static/app.js")
        self.assertEqual(status, 200)
        self.assert_secure(headers)
        self.assertIn("javascript", header(headers, "Content-Type"))
        self.assertIn(b"textContent", body)
        self.assertNotIn(b"innerHTML", body)

        status, _, body = self.get("/static/app.css")
        self.assertEqual(status, 200)
        self.assertIn(b"360px", body)

        status, _, body = self.get("/static/favicon.svg")
        self.assertEqual(status, 200)
        self.assertIn(b"<svg", body)

        blocked = [
            "/static/",
            "/static",
            "/static/index.html",
            "/static/../pyproject.toml",
            "/static/..%2fpyproject.toml",
            "/static/%2e%2e/pyproject.toml",
            "/static/%2e%2e%2fserver.py",
            "/static/app.js/../../pyproject.toml",
            "/static/./app.js",
            "/static/app.js%00",
            "/static/%252e%252e%252fserver.py",
            "/static/App.js",
            "/static/app.js%2f%2e%2e%2fserver.py",
        ]
        for path in blocked:
            status, headers, body = self.get(path)
            self.assertEqual(status, 404, path)
            self.assert_secure(headers)
            lowered = body.lower()
            self.assertNotIn(b"pyproject", lowered)
            self.assertNotIn(b"dependencies", lowered)
            self.assertNotIn(b"[project]", body)

    def test_page_copy_and_no_inline_script(self) -> None:
        page = (STATIC_DIR / "index.html").read_text()
        script = (STATIC_DIR / "app.js").read_text()
        style = (STATIC_DIR / "app.css").read_text()
        self.assertIn("Nothing found in these sermons", script)  # zero hits only
        self.assertNotIn("Nothing strong found", script)  # low confidence shows results, not this
        self.assertIn("heuristic", script)
        self.assertIn("Hide low-confidence results", page)
        self.assertIn("Audio timing coming soon", script)
        self.assertIn("LibriVox volunteer", script)
        self.assertIn("Read by ", script)
        self.assertNotIn("<script>", page.replace('<script src="/static/app.js" defer></script>', ""))
        for text in (page, script, style):
            self.assertNotIn("innerHTML", text)
            self.assertNotIn("cdn.", text.lower())
            self.assertNotIn("fonts.googleapis", text.lower())
            self.assertNotIn("unsafe-inline", text)

    def test_credits_on_the_page(self) -> None:
        page = (STATIC_DIR / "index.html").read_text()
        self.assertIn('id="credits-heading"', page)
        self.assertIn("Sermons on Several Occasions</cite> (public domain)", page)
        self.assertIn('href="https://ccel.org/ccel/wesley/sermons"', page)
        self.assertIn('href="https://librivox.org/"', page)
        self.assertIn("(public domain)", page.split("LibriVox</a>", 1)[1])

    def test_hit_dict_audio_url_matches_the_page_allow_list(self) -> None:
        from preached.search import Hit

        def hit(audio_url):
            return Hit(
                rowid=1, score=1.0, chunk_id="c", sermon_id="wesley-001", sermon_title="T",
                text="grace", start_s=1.0, end_s=2.0, source_url=None, scripture=None,
                audio_url=audio_url,
            )

        archive = "https://archive.org/download/x/y.mp3"
        self.assertEqual(hit_dict(hit(archive))["audio_url"], archive)
        self.assertEqual(hit_dict(hit("/fixture/a.mp3"))["audio_url"], "/fixture/a.mp3")
        self.assertIsNone(hit_dict(hit(None))["audio_url"])
        for blocked in (
            "javascript:alert(1)",
            "data:audio/mp3;base64,AAAA",
            "http://archive.org/download/x/y.mp3",
            "file:///etc/passwd",
            "//evil.example/a.mp3",
            "https://www.youtube.com/watch?v=abcdefghijk&v=",
            "https://www.youtube.com:abc/watch?v=abcdefghijk",
            "https://evil.com@ccel.org/file.mp3",
            "https://user:pass@ccel.org/file.mp3",
            "https://user:pass@archive.org/download/x/y.mp3",
        ):
            with self.subTest(url=blocked):
                self.assertIsNone(hit_dict(hit(blocked))["audio_url"])
        hostile = (
            "https://www.youtube.com/watch?v=abcdefghijk"
            "&t=javascript:alert(1)&redirect=https://evil.example"
        )
        self.assertEqual(
            hit_dict(hit(hostile))["audio_url"],
            "https://www.youtube.com/watch?v=abcdefghijk",
        )
        extra = "https://m.youtube.com/watch?v=abcdefghijk&t=11s&redirect=https://evil.example"
        cleaned = hit_dict(hit(extra))["audio_url"]
        self.assertEqual(cleaned, "https://www.youtube.com/watch?v=abcdefghijk&t=11s")
        self.assertNotIn("redirect", cleaned)

    def test_excerpt_hides_paragraph_numbers(self) -> None:
        from preached.search import Hit

        raw = 'to myself justice!" 8. Nearly related'
        hit = Hit(
            rowid=1, score=1.0, chunk_id="c", sermon_id="wesley-001", sermon_title="T",
            text=raw, start_s=None, end_s=None, source_url=None, scripture=None,
        )
        self.assertEqual(hit_dict(hit)["text"], 'to myself justice!" Nearly related')
        self.assertEqual(hit.text, raw)

    def test_methods_host_and_body_limits(self) -> None:
        status, headers, body = self.rich.request("POST", "/api/search?q=zealboundary")
        self.assertEqual(status, 405)
        self.assert_secure(headers)
        self.assertIn("GET", header(headers, "Allow"))
        self.assertEqual(json.loads(body)["error"], "method not allowed")

        status, headers, body = self.get("/healthz", host="evil.example")
        self.assertEqual(status, 421)
        self.assert_secure(headers)
        self.assertNotIn(b"Traceback", body)

        status, headers, _body = self.get("/healthz", host="localhost")
        self.assertEqual(status, 200)
        self.assert_secure(headers)

        status, headers, body = self.rich.request(
            "GET",
            "/healthz",
            headers={"Content-Length": "99999"},
        )
        self.assertEqual(status, 413)
        self.assert_secure(headers)
        self.assertNotIn(b"Traceback", body)

        status, _, body = self.get("/no/such/page")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "not found")

        status, headers, body = self.get("/api/search?q=zealboundary&pad=" + ("x" * 3000))
        self.assertEqual(status, 414)
        self.assert_secure(headers)
        self.assertNotIn(b"Traceback", body)
        self.assertEqual(self.rich.server.RequestHandlerClass.timeout, REQUEST_TIMEOUT_S)
        self.assertEqual(MAX_TARGET, 2048)
        self.assertLessEqual(MAX_BODY, 4096)

    def test_internal_error_hides_the_exception(self) -> None:
        original = self.rich_app.search

        def boom(*_args, **_kwargs):
            raise RuntimeError("SECRET_TRACEBACK_TOKEN")

        self.rich_app.search = boom
        try:
            status, headers, body = self.get("/api/search?q=zealboundary&k=1")
        finally:
            self.rich_app.search = original
        self.assertEqual(status, 500)
        self.assert_secure(headers)
        self.assertEqual(json.loads(body)["error"], "internal error")
        self.assertNotIn(b"SECRET_TRACEBACK_TOKEN", body)
        self.assertNotIn(b"Traceback", body)

    def test_real_fts_failure_is_a_clean_500_and_releases_the_lock(self) -> None:
        # PR #2 makes an FTS5 error raise instead of returning "nothing found".
        # Force a real SQLite MATCH syntax error through the shipped path.
        import preached.store as store

        original = store.to_fts_query
        store.to_fts_query = lambda _query: '"UNTERMINATED_MATCH_TOKEN'
        try:
            for mode in ("bm25", "hybrid"):
                status, headers, body = self.rich.request("GET", f"/api/search?q=zealboundary&k=3&mode={mode}")
                self.assertEqual(status, 500, mode)
                self.assert_secure(headers)
                self.assertEqual(json.loads(body), {"error": "internal error"})
                self.assertNotIn(b"UNTERMINATED_MATCH_TOKEN", body)
                self.assertNotIn(b"Traceback", body)
        finally:
            store.to_fts_query = original
        status, _headers, _body = self.rich.request("GET", "/api/search?q=zealboundary&k=3&mode=bm25")
        self.assertEqual(status, 200)

    def test_stale_vectors_fall_back_to_bm25_before_loading_weights(self) -> None:
        connection = reopen(self.rich_path)
        try:
            self.assertNotEqual(MODELS["granite-english-r2"].fingerprint(), "older-revision")
            # The real loader: the fingerprint check refuses before load_model runs.
            searcher, encode, note = load_search(connection, "granite-english-r2")
            self.assertIsNone(encode)
            self.assertEqual(note, STALE_NOTE)
            self.assertIsNone(searcher.model)
        finally:
            connection.close()

    def test_search_reloads_when_the_chunk_hash_or_embeddings_change(self) -> None:
        spec = MODELS["granite-english-r2"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.sqlite"
            connection = connect(path)
            _insert(
                connection,
                chunk_id="c1",
                text="By grace are ye saved through faith.",
                start_s=10,
                end_s=20,
            )
            connection.commit()
            rowid = int(connection.execute("SELECT rowid FROM chunks").fetchone()[0])
            matrix = np.ones((1, 4), dtype=np.float32)
            write_embeddings(connection, spec.key, [rowid], matrix)
            save_embedding_info(
                connection,
                spec.key,
                {"fingerprint": spec.fingerprint(), "backend": "onnx", "variant": "fp32"},
            )
            connection.execute(
                "INSERT INTO meta (key, value) VALUES ('chunks_sha256', 'aaa')"
            )
            connection.commit()

            def encode(_query: str) -> np.ndarray:
                return np.ones(4, dtype=np.float32)

            encode.backend = "onnx"
            app = App(
                connection=connection,
                searcher=Searcher(connection, model=spec.key),
                encode=encode,
                fallback_note=None,
                model_name=spec.key,
                hosts={"127.0.0.1"},
                static_dir=STATIC_DIR,
                backend="onnx",
            )
            first = app.search("grace", 5, "dense")
            self.assertEqual(first["mode"], "dense")
            self.assertIn("grace", first["results"][0]["text"])
            connection.execute(
                "UPDATE chunks SET text = ? WHERE chunk_id = 'c1'",
                ("A prayer for the whole church.",),
            )
            connection.execute(
                "UPDATE meta SET value = 'bbb' WHERE key = 'chunks_sha256'"
            )
            connection.commit()
            second = app.search("prayer", 5, "bm25")
            self.assertTrue(any("prayer" in hit["text"] for hit in second["results"]))
            connection.execute("DELETE FROM embeddings")
            connection.execute("DELETE FROM meta WHERE key LIKE 'embeddings:%'")
            connection.commit()
            third = app.search("prayer", 5, "dense")
            self.assertEqual(third["mode"], "bm25")
            self.assertEqual(third["note"], STALE_NOTE)
            self.assertFalse(app.health()["dense"])

    def test_failed_index_read_reloads_on_the_next_success(self) -> None:
        import app.server as server_module

        spec = MODELS["granite-english-r2"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.sqlite"
            connection = connect(path)
            _insert(
                connection,
                chunk_id="c1",
                text="By grace are ye saved through faith.",
                start_s=10,
                end_s=20,
            )
            connection.commit()
            rowid = int(connection.execute("SELECT rowid FROM chunks").fetchone()[0])
            write_embeddings(connection, spec.key, [rowid], np.ones((1, 4), dtype=np.float32))
            save_embedding_info(
                connection,
                spec.key,
                {"fingerprint": spec.fingerprint(), "backend": "onnx", "variant": "fp32"},
            )
            connection.execute("INSERT INTO meta (key, value) VALUES ('chunks_sha256', 'aaa')")
            connection.commit()

            def encode(_query: str) -> np.ndarray:
                return np.ones(4, dtype=np.float32)

            encode.backend = "onnx"
            encode.variant = "fp32"
            app = App(
                connection=connection,
                searcher=Searcher(connection, model=spec.key),
                encode=encode,
                fallback_note=None,
                model_name=spec.key,
                hosts={"127.0.0.1"},
                static_dir=STATIC_DIR,
                backend="onnx",
            )
            first = app.search("grace", 5, "dense")
            self.assertEqual(first["mode"], "dense")
            self.assertIn("grace", first["results"][0]["text"])

            real = server_module.index_stamp
            state = {"fail": True}

            def flaky(connection, model):
                if state["fail"]:
                    raise sqlite3.OperationalError("disk I/O error")
                return real(connection, model)

            server_module.index_stamp = flaky
            try:
                failed = app.search("grace", 5, "dense")
            finally:
                server_module.index_stamp = real
            self.assertEqual(failed["mode"], "bm25")
            self.assertEqual(failed["note"], INDEX_READ_NOTE)
            self.assertIn("grace", failed["results"][0]["text"])

            connection.execute(
                "UPDATE chunks SET text = ? WHERE chunk_id = 'c1'",
                ("A prayer for the whole church.",),
            )
            connection.execute("UPDATE meta SET value = 'bbb' WHERE key = 'chunks_sha256'")
            connection.commit()
            state["fail"] = False
            server_module.index_stamp = flaky
            try:
                second = app.search("prayer", 5, "bm25")
                restored = app.search("prayer", 5, "dense")
            finally:
                server_module.index_stamp = real
            self.assertTrue(any("prayer" in hit["text"] for hit in second["results"]))
            self.assertFalse(any("grace" in hit["text"] for hit in second["results"]))
            self.assertEqual(restored["mode"], "dense")
            self.assertIsNone(restored["note"])
            self.assertTrue(any("prayer" in hit["text"] for hit in restored["results"]))
            self.assertTrue(app.health()["dense"])

    def test_non_fp32_index_fingerprint_is_refused_on_reload(self) -> None:
        spec = MODELS["granite-english-r2"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.sqlite"
            connection = connect(path)
            _insert(
                connection,
                chunk_id="c1",
                text="By grace are ye saved through faith.",
                start_s=10,
                end_s=20,
            )
            connection.commit()
            rowid = int(connection.execute("SELECT rowid FROM chunks").fetchone()[0])
            write_embeddings(connection, spec.key, [rowid], np.ones((1, 4), dtype=np.float32))
            save_embedding_info(
                connection,
                spec.key,
                {"fingerprint": spec.fingerprint(), "backend": "onnx", "variant": "fp32"},
            )
            connection.execute("INSERT INTO meta (key, value) VALUES ('chunks_sha256', 'aaa')")
            connection.commit()

            def encode(_query: str) -> np.ndarray:
                return np.ones(4, dtype=np.float32)

            encode.backend = "onnx"
            encode.variant = "fp32"
            app = App(
                connection=connection,
                searcher=Searcher(connection, model=spec.key),
                encode=encode,
                fallback_note=None,
                model_name=spec.key,
                hosts={"127.0.0.1"},
                static_dir=STATIC_DIR,
                backend="onnx",
            )
            first = app.search("grace", 5, "dense")
            self.assertEqual(first["mode"], "dense")
            save_embedding_info(
                connection,
                spec.key,
                {"fingerprint": spec.fingerprint(), "backend": "onnx", "variant": "int8"},
            )
            second = app.search("grace", 5, "dense")
            self.assertEqual(second["mode"], "bm25")
            self.assertEqual(second["note"], STALE_NOTE)
            self.assertFalse(app.health()["dense"])

    def test_floor_survives_reload_and_is_skipped_on_bm25_fallback(self) -> None:
        spec = MODELS["granite-english-r2"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.sqlite"
            connection = connect(path)
            _insert(
                connection,
                chunk_id="c1",
                text="By grace are ye saved through faith.",
                start_s=10,
                end_s=20,
            )
            connection.commit()
            rowid = int(connection.execute("SELECT rowid FROM chunks").fetchone()[0])
            matrix = np.array([[1, 0, 0, 0]], dtype=np.float32)
            write_embeddings(connection, spec.key, [rowid], matrix)
            save_embedding_info(
                connection,
                spec.key,
                {"fingerprint": spec.fingerprint(), "backend": "onnx", "variant": "fp32"},
            )
            connection.execute(
                "INSERT INTO meta (key, value) VALUES ('chunks_sha256', 'aaa')"
            )
            connection.commit()

            def encode(_query: str) -> np.ndarray:
                return np.array([1, 0, 0, 0], dtype=np.float32)

            encode.backend = "onnx"
            encode.variant = "fp32"
            app = App(
                connection=connection,
                searcher=Searcher(connection, model=spec.key),
                encode=encode,
                fallback_note=None,
                model_name=spec.key,
                hosts={"127.0.0.1"},
                static_dir=STATIC_DIR,
                backend="onnx",
                floor=1.0,
            )
            # Dense top is 1.0, which sits on the floor, and this query has
            # no lexical hit, so the floor marks the list low-confidence.
            first = app.search("nosuchwordanywhere", 5, "hybrid")
            self.assertTrue(first["abstain"])
            self.assertEqual(first["confidence"]["level"], "none")
            self.assertTrue(first["confidence"]["calibrated"])
            self.assertTrue(app.health()["abstain_calibrated"])

            connection.execute(
                "UPDATE chunks SET text = ? WHERE chunk_id = 'c1'",
                ("A prayer for the whole church.",),
            )
            connection.execute(
                "UPDATE meta SET value = 'bbb' WHERE key = 'chunks_sha256'"
            )
            connection.commit()
            second = app.search("nosuchwordanywhere", 5, "hybrid")
            self.assertEqual(second["mode"], "hybrid")
            self.assertTrue(second["abstain"])
            self.assertTrue(second["confidence"]["calibrated"])
            self.assertEqual(app.backend, "onnx")
            self.assertTrue(app.health()["abstain_calibrated"])

            connection.execute("DELETE FROM embeddings")
            connection.execute("DELETE FROM meta WHERE key LIKE 'embeddings:%'")
            connection.commit()
            third = app.search("prayer", 5, "hybrid")
            self.assertEqual(third["mode"], "bm25")
            self.assertEqual(third["note"], STALE_NOTE)
            self.assertFalse(third["abstain"])
            self.assertEqual(third["confidence"]["level"], "unrated")
            self.assertFalse(third["confidence"]["calibrated"])
            empty = app.search("nosuchwordanywhere", 5, "hybrid")
            self.assertEqual(empty["results"], [])
            self.assertTrue(empty["abstain"])
            self.assertEqual(empty["confidence"]["level"], "none")
            self.assertFalse(empty["confidence"]["calibrated"])
            health = app.health()
            self.assertFalse(health["dense"])
            self.assertFalse(health["abstain_calibrated"])
            self.assertIsNone(health["backend"])

    def test_bm25_fallback_is_flagged(self) -> None:
        self.assertIsNone(self.fallback_encode)
        self.assertEqual(self.fallback_note, FALLBACK_NOTE)
        self.assertNotIn("SECRET", FALLBACK_NOTE)

        status, headers, body = self.fallback.request(
            "GET", "/api/search?q=zealboundary&mode=hybrid&k=5"
        )
        self.assertEqual(status, 200)
        self.assert_secure(headers)
        payload = json.loads(body)
        self.assertEqual(payload["mode"], "bm25")
        self.assertEqual(payload["note"], FALLBACK_NOTE)
        self.assertNotIn("SECRET", payload["note"])
        self.assertGreaterEqual(len(payload["results"]), 1)
        self.assertNotIn("neighbor", [hit["chunk_id"] for hit in payload["results"]])

        health = json.loads(self.fallback.request("GET", "/healthz")[2])
        self.assertTrue(health["fallback"])
        self.assertFalse(health["dense"])
        self.assertIsNone(health["model"])

    def test_readonly_index_rejects_writes(self) -> None:
        from preached.store import open_readonly

        connection = open_readonly(self.plain_path)
        with self.assertRaises(sqlite3.OperationalError):
            connection.execute("INSERT INTO meta (key, value) VALUES ('x', 'y')")
        connection.close()

    def test_head_has_headers_and_no_body(self) -> None:
        status, headers, body = self.rich.request("HEAD", "/healthz")
        self.assertEqual(status, 200)
        self.assert_secure(headers)
        self.assertEqual(body, b"")
        self.assertGreater(int(header(headers, "Content-Length")), 0)


class UrllibSmoke(unittest.TestCase):
    """The usual client path, not only the raw HTTPConnection used above."""

    def test_urllib_get(self) -> None:
        # Reuse the class server if it is up. setUp order is per class, so
        # start a tiny one here to stay independent.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "one.sqlite"
        connection = connect(path)
        _insert(connection, text="urllibtoken is enough for one hit.")
        connection.commit()
        connection.close()
        app = build_app(
            reopen(path),
            model_key="granite-english-r2",
            bm25_only=True,
            hosts={"127.0.0.1", "localhost"},
            static_dir=STATIC_DIR,
        )
        running = Running(app)
        self.addCleanup(running.close)
        with urllib.request.urlopen(
            f"http://127.0.0.1:{running.port}/api/search?q=urllibtoken&mode=bm25",
            timeout=5,
        ) as response:
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read())
        self.assertEqual(payload["results"][0]["chunk_id"], "wesley-001-c0000")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(
                f"http://127.0.0.1:{running.port}/api/search?q=",
                timeout=5,
            )
        self.assertEqual(caught.exception.code, 400)


class CspTests(unittest.TestCase):
    def test_media_stays_on_archive_org(self) -> None:
        self.assertEqual(
            CSP,
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
            "media-src 'self' https://archive.org https://*.archive.org; "
            "connect-src 'self'; font-src 'self'; object-src 'none'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
        )
        self.assertNotIn("youtube", CSP)
        self.assertNotIn("frame-src", CSP)
        self.assertNotIn("unsafe-inline", CSP)
        self.assertNotIn("unsafe-eval", CSP)


if __name__ == "__main__":
    unittest.main()
