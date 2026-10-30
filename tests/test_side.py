"""Side-by-side search: one library per column, one church mark, empty side."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.server import CSP, STATIC_DIR, App, Searcher, build_app, make_server
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

        status, _, body = self.both.get("/api/search?q=classiconlytoken&library=sample&mode=bm25")
        self.assertEqual(status, 200)
        empty = json.loads(body)
        self.assertEqual(empty["results"], [])
        self.assertNotIn(b"Salvation", body)

        status, _, body = self.both.get("/api/search?q=churchonlytoken&library=sample&mode=bm25")
        self.assertEqual(status, 200)
        church = json.loads(body)
        self.assertIn("churchonlytoken", texts(church))
        self.assertNotIn("classiconlytoken", texts(church))
        self.assertEqual(sermon_ids(church), {"samplevid01"})
        hit = church["results"][0]
        self.assertEqual(set(hit), RESULT_KEYS)
        self.assertEqual(hit["audio_url"], CHURCH_AUDIO)
        self.assertEqual(hit["text_source"], "asr")
        self.assertEqual(hit["start_s"], 12.2)
        self.assertEqual(hit["source_url"], WATCH)

        status, _, body = self.both.get("/api/search?q=churchonlytoken&library=wesley&mode=bm25")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["results"], [])
        self.assertNotIn(b"On Mercy", body)

        status, _, body = self.both.get("/api/search?q=sharedpulpit&library=spurgeon&mode=bm25")
        self.assertEqual(status, 400)
        self.assertIn("library must be wesley or sample", json.loads(body)["error"])
        self.assertNotIn(b"sharedpulpit", body)

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
        self.assertTrue(church["sample"])
        self.assertEqual(church["label"], "Your church")
        self.assertTrue(church["present"])
        self.assertTrue(church["empty"])
        self.assertEqual(church["message"], CHURCH_EMPTY)
        self.assertEqual(church["results"], [])
        self.assertTrue(church["abstain"])
        self.assertEqual(church["confidence"]["level"], "none")
        self.assertNotIn(b"classiconlytoken", json.dumps(church).encode())

        status, _, body = self.both.get("/api/side?q=churchonlytoken&mode=bm25&k=5")
        swapped = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(swapped["classic"]["abstain"])
        self.assertEqual(swapped["classic"]["results"], [])
        self.assertFalse(swapped["church"]["abstain"])
        self.assertIn("churchonlytoken", texts(swapped["church"]))
        self.assertNotIn("classiconlytoken", texts(swapped["church"]))
        self.assertTrue(sermon_ids(swapped["classic"]).isdisjoint(sermon_ids(swapped["church"])))

    def test_low_confidence_is_per_side(self) -> None:
        status, _, body = self.both.get("/api/side?q=sharedpulpit&mode=hybrid&k=5")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        classic = payload["classic"]
        church = payload["church"]
        self.assertFalse(classic["abstain"])
        self.assertEqual(classic["confidence"]["level"], "strong")
        self.assertFalse(church["abstain"])
        self.assertEqual(church["confidence"]["level"], "weak")
        self.assertIn("sharedpulpit", texts(classic))
        self.assertIn("sharedpulpit", texts(church))
        self.assertTrue(sermon_ids(classic).isdisjoint(sermon_ids(church)))
        self.assertTrue(all(hit["audio_url"] == CLASSIC_AUDIO for hit in classic["results"]))
        self.assertTrue(all("youtube.com" in hit["audio_url"] for hit in church["results"]))

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
            self.assertIn("churchonlytoken", texts(payload["church"]))
            self.assertEqual(payload["church"]["mode"], "bm25")
            self.assertIn("BM25", payload["church"]["note"])
            self.assertNotIn("churchonlytoken", texts(payload["classic"]))
            self.assertTrue(all(hit["audio_url"] == CLASSIC_AUDIO for hit in payload["classic"]["results"]))
            self.assertTrue(all("youtube.com" in hit["audio_url"] for hit in payload["church"]["results"]))


class SideCliTests(unittest.TestCase):
    def test_side_flag_prints_both_columns(self) -> None:
        module = _load_query()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            classic = root / "wesley.sqlite"
            church = root / "sample.sqlite"
            build_library(classic, *classic_rows())
            build_library(church, *church_rows(), church=True, sample=True)
            with patch.object(module, "ensure_chunks", lambda connection: None):
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
            church_body = _section(text, "Your church (sample data)")
            self.assertIn("classiconlytoken", classic_body)
            self.assertNotIn("churchonlytoken", classic_body)
            self.assertIn("confidence: unrated", classic_body)
            self.assertIn(CLASSIC_AUDIO, classic_body)
            self.assertIn(CHURCH_EMPTY, church_body)
            self.assertIn("confidence: none", church_body)
            self.assertNotIn("classiconlytoken", church_body)
            self.assertNotIn("churchonlytoken", church_body)

            missing = StringIO()
            with patch.object(module, "ensure_chunks", lambda connection: None):
                with redirect_stdout(missing):
                    module.main(
                        [
                            "classiconlytoken",
                            "--mode",
                            "bm25",
                            "--side",
                            "--index",
                            str(classic),
                            "--church-index",
                            str(root / "absent.sqlite"),
                        ]
                    )
            absent = missing.getvalue()
            self.assertIn("## Your church\n", absent)
            self.assertIn(CHURCH_EMPTY, _section(absent, "Your church"))
            self.assertNotIn("sample data", _section(absent, "Your church"))


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
