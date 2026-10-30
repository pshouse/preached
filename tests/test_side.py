"""Side-by-side search: one library per column, one church mark, empty side."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from app.server import CSP, STATIC_DIR, App, Searcher, build_app, make_server, prepare_church
from preached.abstain import Signals, church_confidence, decide
from preached.library import (
    CHURCH_EMPTY,
    church_index_matches,
    find_church_index,
    get_meta,
    is_your_church,
    mark_your_church,
    mark_your_church_exclusive,
    resolve_church_path,
)
from preached.store import connect, open_readonly, save_embedding_info, write_embeddings

FIXTURE_FP = "fixture-fingerprint"
CLASSIC_AUDIO = "https://archive.org/download/sermonsfirstseries_1307_librivox/example.mp3"
CHURCH_AUDIO = "https://www.youtube.com/watch?v=samplevid01&t=11s"
CCEL = "https://ccel.org/ccel/wesley/sermons/sermons.v.i.html"
WATCH = "https://www.youtube.com/watch?v=samplevid01"
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
SIDE_KEYS = {
    "library",
    "label",
    "sample",
    "present",
    "empty",
    "message",
    "mode",
    "results",
    "note",
    "abstain",
    "confidence",
}
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
    "audio_url",
    "reader",
    "text_source",
)


def encode_fixture(_query: str) -> np.ndarray:
    return np.array([1, 0, 0, 0], dtype=np.float32)


def _insert(connection, **overrides) -> None:
    row = {
        "chunk_id": "wesley-001-c0000",
        "sermon_id": "wesley-001",
        "sermon_title": "Salvation by Faith",
        "text": "By grace are ye saved through faith.",
        "start_s": 32.81,
        "end_s": 40.0,
        "sermon_number": 1,
        "scripture": "Eph 2:8",
        "source_url": CCEL,
        "word_count": 6,
        "word_start": 0,
        "word_end": 6,
        "librivox_id": "sermonsfirstseries_1307_librivox",
        "audio_url": CLASSIC_AUDIO,
        "reader": "A. Volunteer",
        "text_source": "canonical",
    }
    row.update(overrides)
    names = ", ".join(COLUMNS)
    places = ", ".join(":" + name for name in COLUMNS)
    connection.execute(f"INSERT INTO chunks ({names}) VALUES ({places})", row)


def build_library(path: Path, rows: list[dict], vectors: list[list[float]], *, church: bool = False, sample: bool = False) -> None:
    connection = connect(path)
    for row in rows:
        _insert(connection, **row)
    connection.commit()
    rowids = [int(row[0]) for row in connection.execute("SELECT rowid FROM chunks ORDER BY rowid")]
    matrix = np.array(vectors, dtype=np.float32)
    write_embeddings(connection, "fixture", rowids, matrix)
    save_embedding_info(connection, "fixture", {"fingerprint": FIXTURE_FP})
    if church:
        mark_your_church(connection, sample=sample)
        connection.commit()
    connection.close()


def reopen(path: Path):
    connection = open_readonly(path, check_same_thread=False)
    return connection


def classic_rows() -> tuple[list[dict], list[list[float]]]:
    rows = [
        {
            "chunk_id": "classic-a",
            "sermon_id": "wesley-001",
            "sermon_title": "Salvation by Faith",
            "text": "classiconlytoken alpha from the classic library.",
            "word_start": 0,
            "word_end": 8,
        },
        {
            "chunk_id": "classic-b",
            "sermon_id": "wesley-002",
            "sermon_number": 2,
            "sermon_title": "The Almost Christian",
            "text": "classiconlytoken beta from the classic library.",
            "word_start": 100,
            "word_end": 108,
        },
        {
            "chunk_id": "classic-shared",
            "sermon_id": "wesley-003",
            "sermon_number": 3,
            "sermon_title": "Awake Thou That Sleepest",
            "text": "sharedpulpit faith from the classic library.",
            "word_start": 200,
            "word_end": 208,
        },
    ]
    return rows, [[1, 0, 0, 0], [1, 0, 0, 0], [1, 0, 0, 0]]


def church_rows() -> tuple[list[dict], list[list[float]]]:
    rows = [
        {
            "chunk_id": "church-only",
            "sermon_id": "samplevid01",
            "sermon_number": None,
            "sermon_title": "On Mercy",
            "text": "churchonlytoken mercy from the sample church.",
            "scripture": None,
            "source_url": WATCH,
            "start_s": 12.2,
            "end_s": 20.0,
            "audio_url": CHURCH_AUDIO,
            "reader": None,
            "text_source": "asr",
            "librivox_id": None,
            "word_start": 0,
            "word_end": 8,
        },
        {
            "chunk_id": "church-shared",
            "sermon_id": "samplevid02",
            "sermon_number": None,
            "sermon_title": "On Hope",
            "text": "sharedpulpit hope from the sample church.",
            "scripture": None,
            "source_url": "https://www.youtube.com/watch?v=samplevid02",
            "start_s": 40.0,
            "end_s": 55.0,
            "audio_url": "https://www.youtube.com/watch?v=samplevid02&t=39s",
            "reader": None,
            "text_source": "asr",
            "librivox_id": None,
            "word_start": 0,
            "word_end": 8,
        },
    ]
    return rows, [[0, 1, 0, 0], [0, 1, 0, 0]]


def make_app(classic_path: Path, church_path: Path | None, *, floor: float | None = 0.5) -> App:
    classic = reopen(classic_path)
    church = reopen(church_path) if church_path is not None else None
    return App(
        connection=classic,
        searcher=Searcher(classic, model="fixture", fingerprint=FIXTURE_FP),
        encode=encode_fixture,
        fallback_note=None,
        model_name="fixture",
        hosts={"127.0.0.1", "localhost"},
        static_dir=STATIC_DIR,
        library="wesley",
        floor=floor,
        church_connection=church,
        church_searcher=Searcher(church, model="fixture", fingerprint=FIXTURE_FP) if church is not None else None,
        church_library="sample" if church is not None else None,
        church_label="Your church" if church is not None else None,
    )


class Running:
    def __init__(self, app: App):
        self.server = make_server(app, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def get(self, path: str) -> tuple[int, dict, bytes]:
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()


def texts(payload: dict) -> str:
    return " ".join(hit["text"] for hit in payload["results"])


def sermon_ids(payload: dict) -> set[str]:
    return {hit["sermon_id"] for hit in payload["results"]}


class MarkTests(unittest.TestCase):
    def test_one_mark_is_found_and_two_marks_are_not_a_guess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "sample.sqlite"
            second = root / "other.sqlite"
            rows, vectors = church_rows()
            build_library(first, rows[:1], vectors[:1], church=True, sample=True)
            build_library(second, rows[:1], vectors[:1], church=True, sample=False)
            self.assertEqual(find_church_index(root), None)
            self.assertEqual(len(church_index_matches(root)), 2)
            mark_your_church_exclusive(first, root, sample=True)
            found = find_church_index(root)
            self.assertEqual(found, first)
            marked = open_readonly(first)
            cleared = open_readonly(second)
            try:
                self.assertTrue(is_your_church(marked))
                self.assertEqual(get_meta(marked, "sample"), "1")
                self.assertFalse(is_your_church(cleared))
            finally:
                marked.close()
                cleared.close()
            # The classic file is not a church side even if it shares the directory.
            wesley = root / "wesley.sqlite"
            build_library(wesley, *classic_rows())
            self.assertEqual(find_church_index(root, exclude=wesley), first)
            self.assertIsNone(resolve_church_path(root, classic=wesley, church_index=wesley))
            self.assertIsNone(resolve_church_path(root, classic=wesley, church_library="missing"))
            self.assertEqual(resolve_church_path(root, classic=wesley, church_library="sample"), first)

    def test_classic_copy_bytes_are_unchanged_and_a_sibling_is_cleared_without_wal(self) -> None:
        """A mistaken mark must not migrate wesley or turn on WAL.

        store.connect rewrites the schema and sets journal_mode=WAL. Clearing
        a sibling uses a plain sqlite3 connection. wesley, spurgeon, edwards,
        and a canonical classic path are not opened.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            classics = {
                name: root / f"{name}.sqlite" for name in ("wesley", "spurgeon", "edwards")
            }
            for path in classics.values():
                _plain_marked(path)
            before = {name: path.read_bytes() for name, path in classics.items()}
            other = root / "other.sqlite"
            _plain_marked(other)
            sample = root / "sample.sqlite"
            rows, vectors = church_rows()
            build_library(sample, rows[:1], vectors[:1])
            # A marked wesley copy is not a candidate, so it is not opened.
            self.assertEqual(church_index_matches(root), [other])
            mark_your_church_exclusive(sample, root, sample=True)
            for name, path in classics.items():
                self.assertEqual(path.read_bytes(), before[name], name)
                self.assertFalse(path.with_name(path.name + "-wal").exists(), name)
                self.assertFalse(path.with_name(path.name + "-journal").exists(), name)
                kept = sqlite3.connect(path)
                try:
                    self.assertEqual(
                        kept.execute("SELECT value FROM meta WHERE key = 'role'").fetchone()[0],
                        "church",
                    )
                    self.assertEqual(kept.execute("PRAGMA journal_mode").fetchone()[0], "delete")
                finally:
                    kept.close()
            cleared = sqlite3.connect(other)
            try:
                self.assertIsNone(
                    cleared.execute("SELECT value FROM meta WHERE key = 'role'").fetchone()
                )
                self.assertEqual(cleared.execute("PRAGMA journal_mode").fetchone()[0], "delete")
                tables = {row[0] for row in cleared.execute("SELECT name FROM sqlite_master")}
            finally:
                cleared.close()
            self.assertNotIn("chunks_fts", tables)
            self.assertNotIn("embeddings", tables)
            self.assertFalse(other.with_name(other.name + "-wal").exists())
            marked = open_readonly(sample)
            try:
                self.assertTrue(is_your_church(marked))
            finally:
                marked.close()
            # Marking the wesley copy itself must not rewrite it either.
            with self.assertRaises(ValueError):
                mark_your_church_exclusive(classics["wesley"], root)
            self.assertEqual(classics["wesley"].read_bytes(), before["wesley"])

            canonical = root / "archive.sqlite"
            _plain_marked(canonical)
            canonical_before = canonical.read_bytes()
            with patch("preached.paths.INDEX_PATH", canonical):
                mark_your_church_exclusive(sample, root, sample=True)
            self.assertEqual(canonical.read_bytes(), canonical_before)
            self.assertFalse(canonical.with_name(canonical.name + "-wal").exists())


def _plain_marked(path: Path) -> None:
    """A church-marked file that did not go through store.connect (no WAL)."""
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO meta (key, value) VALUES ('role', 'church')")
        connection.execute("CREATE TABLE chunks (chunk_id TEXT, text TEXT)")
        connection.execute(
            "INSERT INTO chunks VALUES ('wesley-001-c0000', ?)",
            ("By grace are ye saved through faith. " * 20,),
        )
        connection.commit()
    finally:
        connection.close()


class SideApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.classic_path = root / "wesley.sqlite"
        cls.church_path = root / "sample.sqlite"
        build_library(cls.classic_path, *classic_rows())
        build_library(cls.church_path, *church_rows(), church=True, sample=True)
        cls.both = Running(make_app(cls.classic_path, cls.church_path))
        cls.classic_only = Running(make_app(cls.classic_path, None))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.both.close()
        cls.classic_only.close()
        cls.tmp.cleanup()

    def test_search_stays_inside_one_library(self) -> None:
        status, headers, body = self.both.get(
            "/api/search?q=classiconlytoken&library=wesley&mode=bm25&k=5"
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Security-Policy"], CSP)
        self.assertNotIn("unsafe-inline", headers["Content-Security-Policy"])
        payload = json.loads(body)
        self.assertGreaterEqual(len(payload["results"]), 1)
        self.assertLessEqual(len(payload["results"]), 5)
        self.assertIn("classiconlytoken", texts(payload))
        self.assertNotIn("churchonlytoken", texts(payload))
        self.assertTrue(sermon_ids(payload) <= {"wesley-001", "wesley-002", "wesley-003"})
        for hit in payload["results"]:
            self.assertEqual(set(hit), RESULT_KEYS)
            self.assertEqual(hit["audio_url"], CLASSIC_AUDIO)

        # A church slug is not an open library. Same 400 as a server with no church file.
        for slug in ("sample", "spurgeon"):
            status, _, body = self.both.get(f"/api/search?q=churchonlytoken&library={slug}&mode=bm25")
            self.assertEqual(status, 400, slug)
            self.assertEqual(json.loads(body)["error"], "library must be wesley")
            self.assert_no_church_payload(body)
            only_status, _, only_body = self.classic_only.get(
                f"/api/search?q=churchonlytoken&library={slug}&mode=bm25"
            )
            self.assertEqual(status, only_status)
            self.assertEqual(json.loads(body)["error"], json.loads(only_body)["error"])

        status, _, body = self.both.get("/api/search?q=churchonlytoken&library=wesley&mode=bm25")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["results"], [])
        self.assert_no_church_payload(body)

        status, _, body = self.both.get("/api/search?q=classiconlytoken&mode=bm25&k=1")
        self.assertEqual(status, 200)
        scoped = json.loads(body)
        self.assertEqual(len(scoped["results"]), 1)
        self.assertNotIn("churchonlytoken", texts(scoped))

    def test_side_by_side_abstains_per_side_and_labels_sample_data(self) -> None:
        status, headers, body = self.both.get("/api/side?q=classiconlytoken&mode=bm25&k=1")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Security-Policy"], CSP)
        payload = json.loads(body)
        self.assertEqual(set(payload), {"query", "mode", "k", "took_ms", "classic", "church"})
        self.assertEqual(payload["k"], 1)
        self.assertEqual(payload["mode"], "bm25")
        classic = payload["classic"]
        church = payload["church"]
        self.assertEqual(set(classic), SIDE_KEYS)
        self.assertEqual(set(church), SIDE_KEYS)
        self.assertEqual(classic["library"], "wesley")
        self.assertEqual(classic["label"], "John Wesley")
        self.assertFalse(classic["sample"])
        self.assertTrue(classic["present"])
        self.assertFalse(classic["empty"])
        self.assertIsNone(classic["message"])
        self.assertFalse(classic["abstain"])
        self.assertEqual(classic["confidence"]["level"], "unrated")
        self.assertEqual(len(classic["results"]), 1)
        self.assertIn("classiconlytoken", texts(classic))
        self.assertNotIn("churchonlytoken", texts(classic))
        self.assert_missing_church(church)
        self.assert_no_church_payload(json.dumps(church).encode())

        only_status, _, only_body = self.classic_only.get("/api/side?q=classiconlytoken&mode=bm25&k=1")
        self.assertEqual(only_status, 200)
        only = json.loads(only_body)
        self.assertEqual(_without_took(payload), _without_took(only))

        status, _, body = self.both.get("/api/side?q=churchonlytoken&mode=bm25&k=5")
        swapped = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(swapped["classic"]["abstain"])
        self.assertEqual(swapped["classic"]["results"], [])
        self.assert_missing_church(swapped["church"])
        self.assert_no_church_payload(body)

    def test_configured_church_matches_the_no_church_responses(self) -> None:
        """A fixture church file must not change /api/side, /api/search, or /healthz."""
        side_both = self.both.get("/api/side?q=sharedpulpit&mode=bm25&k=5")
        side_only = self.classic_only.get("/api/side?q=sharedpulpit&mode=bm25&k=5")
        self.assertEqual(side_both[0], 200)
        self.assertEqual(side_only[0], 200)
        both_payload = json.loads(side_both[2])
        only_payload = json.loads(side_only[2])
        self.assertEqual(_without_took(both_payload), _without_took(only_payload))
        self.assert_missing_church(both_payload["church"])
        self.assertFalse(both_payload["church"]["present"])
        self.assert_no_church_payload(side_both[2])

        health_both = json.loads(self.both.get("/healthz")[2])
        health_only = json.loads(self.classic_only.get("/healthz")[2])
        self.assertIsNone(health_both["church"])
        self.assertEqual(health_both, health_only)

    def test_low_confidence_is_per_side(self) -> None:
        status, _, body = self.both.get("/api/side?q=sharedpulpit&mode=hybrid&k=5")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        classic = payload["classic"]
        church = payload["church"]
        self.assertFalse(classic["abstain"])
        self.assertEqual(classic["confidence"]["level"], "strong")
        self.assert_missing_church(church)
        self.assertIn("sharedpulpit", texts(classic))
        self.assertTrue(all(hit["audio_url"] == CLASSIC_AUDIO for hit in classic["results"]))
        self.assert_no_church_payload(json.dumps(church).encode())
        only = json.loads(self.classic_only.get("/api/side?q=sharedpulpit&mode=hybrid&k=5")[2])
        self.assertEqual(_without_took(payload), _without_took(only))

    def test_missing_church_is_an_empty_side_not_an_error(self) -> None:
        status, _, body = self.classic_only.get("/api/side?q=classiconlytoken&mode=bm25")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        church = payload["church"]
        self.assertFalse(church["present"])
        self.assertTrue(church["empty"])
        self.assertIsNone(church["library"])
        self.assertEqual(church["message"], CHURCH_EMPTY)
        self.assertEqual(church["results"], [])
        self.assertFalse(church["abstain"])
        self.assertIsNone(church["confidence"])
        self.assertGreaterEqual(len(payload["classic"]["results"]), 1)

        status, _, body = self.classic_only.get("/api/side?q=classiconlytoken&library=sample&mode=bm25")
        self.assertEqual(status, 400)
        self.assertIn("library must be wesley", json.loads(body)["error"])

        status, _, body = self.both.get("/api/side")
        self.assertEqual(status, 400)

    def test_church_without_vectors_does_not_drop_the_classic_side(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            classic_path = root / "wesley.sqlite"
            bare_path = root / "sample.sqlite"
            build_library(classic_path, *classic_rows())
            bare = connect(bare_path)
            _insert(
                bare,
                chunk_id="bare",
                sermon_id="samplevid01",
                sermon_title="On Mercy",
                text="churchonlytoken mercy with no vectors yet.",
                audio_url=CHURCH_AUDIO,
                text_source="asr",
                reader=None,
                sermon_number=None,
            )
            bare.commit()
            bare.close()

            def loader(connection, _model_key):
                return Searcher(connection, model="fixture", fingerprint=FIXTURE_FP), encode_fixture

            app = build_app(
                reopen(classic_path),
                model_key="granite-english-r2",
                bm25_only=False,
                hosts={"127.0.0.1", "localhost"},
                static_dir=STATIC_DIR,
                loader=loader,
                floor=0.5,
                library="wesley",
                church_connection=reopen(bare_path),
                church_library="sample",
            )
            payload = app.side("churchonlytoken", 5, "hybrid")
            self.assert_missing_church(payload["church"])
            self.assert_no_church_payload(json.dumps(payload["church"]).encode())
            classic = app.side("classiconlytoken", 5, "hybrid")
            self.assertIn("classiconlytoken", texts(classic["classic"]))
            self.assertTrue(all(hit["audio_url"] == CLASSIC_AUDIO for hit in classic["classic"]["results"]))
            self.assert_missing_church(classic["church"])

    def assert_missing_church(self, church: dict) -> None:
        self.assertEqual(
            church,
            {
                "library": None,
                "label": "Your church",
                "sample": False,
                "present": False,
                "empty": True,
                "message": CHURCH_EMPTY,
                "mode": None,
                "results": [],
                "note": None,
                "abstain": False,
                "confidence": None,
            },
        )

    def assert_no_church_payload(self, body: bytes) -> None:
        """Church fixture text must not appear outside the echoed query."""
        payload = json.loads(body)
        scrubbed = json.dumps(_drop_query(payload), ensure_ascii=False).encode()
        self.assertNotIn(b"churchonlytoken", scrubbed)
        self.assertNotIn(b"samplevid01", scrubbed)
        self.assertNotIn(b"samplevid02", scrubbed)
        self.assertNotIn(b"youtube.com", scrubbed)
        self.assertNotIn(b"On Mercy", scrubbed)
        self.assertNotIn(b"On Hope", scrubbed)
        self.assertNotIn(WATCH.encode(), scrubbed)
        self.assertNotIn(CHURCH_AUDIO.encode(), scrubbed)


class SideCliTests(unittest.TestCase):
    def test_side_flag_prints_both_columns(self) -> None:
        module = _load_query()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            classic = root / "wesley.sqlite"
            church = root / "sample.sqlite"
            build_library(classic, *classic_rows())
            build_library(church, *church_rows(), church=True, sample=True)
            out = StringIO()
            with redirect_stdout(out):
                module.main(
                    [
                        "classiconlytoken",
                        "--mode",
                        "bm25",
                        "-k",
                        "5",
                        "--side",
                        "--index",
                        str(classic),
                        "--church-index",
                        str(church),
                    ]
                )
            text = out.getvalue()
            classic_body = _section(text, "Classic library: John Wesley")
            church_body = _section(text, "Your church")
            self.assertIn("classiconlytoken", classic_body)
            self.assertNotIn("churchonlytoken", classic_body)
            self.assertIn("confidence: unrated", classic_body)
            self.assertIn(CLASSIC_AUDIO, classic_body)
            self.assertIn(CHURCH_EMPTY, church_body)
            self.assertNotIn("confidence:", church_body)
            self.assertNotIn("sample data", church_body)
            self.assertNotIn("churchonlytoken", text)
            self.assertNotIn("youtube.com", text)
            self.assertNotIn(CHURCH_AUDIO, text)

            missing = StringIO()
            with redirect_stdout(missing):
                module.main(
                    [
                        "classiconlytoken",
                        "--mode",
                        "bm25",
                        "-k",
                        "5",
                        "--side",
                        "--index",
                        str(classic),
                        "--church-index",
                        str(root / "absent.sqlite"),
                    ]
                )
            absent = missing.getvalue()
            self.assertEqual(text, absent)
            self.assertIn("## Your church\n", absent)
            self.assertIn(CHURCH_EMPTY, _section(absent, "Your church"))

    def test_classic_church_slug_is_refused(self) -> None:
        module = _load_query()
        for slug in ("wesley", "spurgeon", "edwards"):
            with self.assertRaises(SystemExit) as caught:
                module.main(
                    [
                        "mercy",
                        "--mode",
                        "bm25",
                        "--side",
                        "--church-library",
                        slug,
                    ]
                )
            self.assertIn("classic", str(caught.exception))

    def test_church_confidence_is_unrated_not_the_wesley_floor(self) -> None:
        signals = Signals(bm25_hits=1, dense_top=0.2, agreement=True)
        self.assertEqual(decide(signals, 0.5, has_results=True).level, "weak")
        rated = church_confidence(signals, has_results=True)
        self.assertEqual(rated.level, "unrated")
        self.assertFalse(rated.calibrated)
        self.assertIsNone(rated.floor)
        self.assertFalse(rated.abstain)
        strong = Signals(bm25_hits=2, dense_top=0.9, agreement=True)
        self.assertEqual(decide(strong, 0.5, has_results=True).level, "strong")
        self.assertEqual(church_confidence(strong, has_results=True).level, "unrated")
        low = Signals(bm25_hits=0, dense_top=0.1, agreement=False)
        self.assertEqual(decide(low, 0.5, has_results=True).level, "none")
        self.assertEqual(church_confidence(low, has_results=True).level, "unrated")
        empty = church_confidence(signals, has_results=False)
        self.assertEqual(empty.level, "none")
        self.assertFalse(empty.calibrated)
        self.assertIsNone(empty.floor)

        module = _load_query()

        class FakeSearcher:
            def __init__(self, connection, model=None):
                self.connection = connection
                self._matrix = np.ones((1, 4), dtype=np.float32)
                self._rowids = [1]

            def hybrid(self, *_args, **_kwargs):
                return [object()]

            def dense(self, *_args, **_kwargs):
                return [object()]

            def bm25(self, *_args, **_kwargs):
                return [object()]

        args = SimpleNamespace(
            query="classiconlytoken",
            k=5,
            mode="hybrid",
            fusion="rrf",
            rrf_k=60,
            dense_weight=0.5,
        )
        floors: list = []

        def floor_for(*pos, **_kwargs):
            floors.append(pos)
            return 0.5

        vector = np.ones(4, dtype=np.float32)
        with (
            patch.object(module, "Searcher", FakeSearcher),
            patch.object(module, "compute_signals", lambda *_a, **_k: signals),
            patch.object(module, "floor_for", floor_for),
        ):
            _hits, confidence, *_rest = module.search_index(
                None, args, vector, "fixture", fallback_bm25=True, church=True
            )
        self.assertEqual(confidence.level, "unrated")
        self.assertEqual(floors, [])
        with (
            patch.object(module, "Searcher", FakeSearcher),
            patch.object(module, "compute_signals", lambda *_a, **_k: signals),
            patch.object(module, "floor_for", floor_for),
        ):
            _hits, wesley, *_rest = module.search_index(
                None, args, vector, "fixture", fallback_bm25=False, church=False
            )
        self.assertEqual(wesley.level, "weak")
        self.assertTrue(floors)


class ChurchRefusalTests(unittest.TestCase):
    def test_explicit_classic_slug_is_refused_and_a_marked_copy_is_not_opened(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            classic = root / "built.sqlite"
            build_library(classic, *classic_rows())
            for slug in ("wesley", "spurgeon", "edwards"):
                path = root / f"{slug}.sqlite"
                _plain_marked(path)
                before = path.read_bytes()
                with self.assertRaises(SystemExit) as caught:
                    prepare_church(root, classic=classic, church_index=None, church_library=slug)
                self.assertIn(slug, str(caught.exception))
                self.assertIn("classic", str(caught.exception))
                with self.assertRaises(SystemExit):
                    prepare_church(root, classic=classic, church_index=path, church_library=None)
                self.assertEqual(path.read_bytes(), before)
            # A missing classic name is still refused.
            absent = root / "gone" / "edwards.sqlite"
            with self.assertRaises(SystemExit):
                prepare_church(root, classic=classic, church_index=absent, church_library=None)
            titled = root / "Wesley.sqlite"
            _plain_marked(titled)
            titled_before = titled.read_bytes()
            with self.assertRaises(SystemExit) as titled_exit:
                prepare_church(root, classic=classic, church_index=titled, church_library=None)
            self.assertIn("classic", str(titled_exit.exception))
            self.assertEqual(titled.read_bytes(), titled_before)
            # Auto-detected mark on a wesley copy does not stop resolution.
            found = prepare_church(root, classic=classic, church_index=None, church_library=None)
            self.assertEqual(found, (None, None))
            sample = root / "sample.sqlite"
            rows, vectors = church_rows()
            build_library(sample, rows[:1], vectors[:1], church=True, sample=True)
            before = sample.read_bytes()
            path, slug = prepare_church(root, classic=classic, church_index=None, church_library="sample")
            self.assertEqual(path, sample)
            self.assertEqual(slug, "sample")
            self.assertEqual(sample.read_bytes(), before)


def _without_took(payload: dict) -> dict:
    copy = json.loads(json.dumps(payload))
    copy.pop("took_ms", None)
    return copy


def _drop_query(value):
    """Remove echoed ``query`` fields so a church-token query is not a hit."""
    if isinstance(value, dict):
        return {key: _drop_query(item) for key, item in value.items() if key != "query"}
    if isinstance(value, list):
        return [_drop_query(item) for item in value]
    return value


def _section(text: str, heading: str) -> str:
    marker = f"## {heading}"
    start = text.index(marker)
    rest = text[start + len(marker) :]
    nxt = rest.find("\n## ")
    return rest if nxt < 0 else rest[:nxt]


def _load_query():
    path = Path(__file__).resolve().parents[1] / "search" / "query.py"
    spec = importlib.util.spec_from_file_location("preached_query_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
