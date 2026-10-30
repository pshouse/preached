"""The abstain rule, its calibration file, and the fields GET /api/search adds."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from preached import abstain
from preached.abstain import Signals, decide, fit_floor, floor_for
from preached.models import MODELS
from preached.search import Searcher

from test_server import (
    FALLBACK_NOTE,
    FIXTURE_FP,
    STATIC_DIR,
    App,
    Running,
    build_app,
    build_rich_index,
    encode_fixture,
    load_search,
    reopen,
)


def sig(dense_top, agreement, bm25_hits=10) -> Signals:
    return Signals(bm25_hits=bm25_hits, dense_top=dense_top, agreement=agreement)


class DecideTests(unittest.TestCase):
    def test_levels(self) -> None:
        self.assertEqual(decide(sig(0.90, True), 0.80).level, "strong")
        self.assertEqual(decide(sig(0.90, False), 0.80).level, "weak")
        self.assertEqual(decide(sig(0.80, True), 0.80).level, "weak")  # on the floor counts as low
        none = decide(sig(0.79, False, bm25_hits=0), 0.80)
        self.assertEqual(none.level, "none")
        self.assertTrue(none.abstain)
        self.assertEqual(none.note, abstain.NONE_NOTE)

    def test_uncalibrated_never_abstains(self) -> None:
        result = decide(sig(0.10, False, bm25_hits=0), None)
        self.assertEqual(result.level, "weak")
        self.assertFalse(result.abstain)
        self.assertFalse(result.calibrated)
        self.assertEqual(decide(sig(0.10, True), None).level, "strong")

    def test_bm25_only_is_unrated_or_none(self) -> None:
        self.assertEqual(decide(sig(None, False), 0.8).level, "unrated")
        self.assertIsNone(decide(sig(None, False), 0.8).note)
        self.assertEqual(decide(sig(None, False, bm25_hits=0), None, has_results=False).level, "none")

    def test_as_dict(self) -> None:
        payload = decide(sig(0.9, False), 0.8).as_dict()
        self.assertEqual(set(payload), {"level", "calibrated", "note", "signals"})
        self.assertEqual(payload["note"], abstain.WEAK_NOTE)
        self.assertEqual(payload["signals"], {"bm25_hits": 10, "dense_top": 0.9, "agreement": False})
        json.dumps(payload)


class FitTests(unittest.TestCase):
    def test_floor_is_the_highest_unsupported_negative(self) -> None:
        rows = [
            (sig(0.70, False), False),
            (sig(0.75123, False), False),
            (sig(0.90, True), False),  # has agreement: cannot be caught, does not set the floor
            (sig(0.85, True), True),
        ]
        self.assertEqual(fit_floor(rows), 0.7513)  # rounded up, so 0.75123 <= floor
        self.assertEqual(decide(rows[1][0], fit_floor(rows)).level, "none")

    def test_floor_never_hides_a_labelled_answer(self) -> None:
        rows = [
            (sig(0.80, False), False),
            (sig(0.78, False), True),  # answerable, no agreement, below the negatives
        ]
        floor = fit_floor(rows)
        self.assertLess(floor, 0.78)
        self.assertNotEqual(decide(rows[1][0], floor).level, "none")

    def test_nothing_to_fit(self) -> None:
        self.assertIsNone(fit_floor([(sig(0.9, True), True), (sig(0.9, True), False)]))


class CalibrationFileTests(unittest.TestCase):
    def write(self, entries: dict) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "abstain.toml"
        path.write_text(abstain.calibration_toml(entries))
        return path

    def test_floor_needs_matching_fingerprints(self) -> None:
        spec = MODELS["granite-english-r2"]
        good = {
            "dense_floor": 0.81,
            "fingerprint": spec.fingerprint(),
            "query_fingerprint": abstain.query_fingerprint(spec),
            "backend": "torch",
            "variant": spec.dtype_cpu,
        }
        self.assertEqual(floor_for("granite-english-r2", self.write({"granite-english-r2": good})), 0.81)
        stale_docs = {**good, "fingerprint": "older-revision"}
        self.assertIsNone(floor_for("granite-english-r2", self.write({"granite-english-r2": stale_docs})))
        stale_query = {**good, "query_fingerprint": "other-prefix"}
        self.assertIsNone(floor_for("granite-english-r2", self.write({"granite-english-r2": stale_query})))

    def test_missing_model_or_file(self) -> None:
        self.assertIsNone(floor_for("embeddinggemma-2", self.write({})))
        self.assertIsNone(floor_for("granite-english-r2", Path("/nonexistent/abstain.toml")))
        self.assertIsNone(floor_for(None))

    def test_query_fingerprint_differs_by_prefix(self) -> None:
        self.assertNotEqual(
            abstain.query_fingerprint(MODELS["granite-english-r2"]),
            abstain.query_fingerprint(MODELS["embeddinggemma-2"]),
        )

    def test_committed_file_is_per_model(self) -> None:
        entries = abstain.load_calibrations()
        for key, entry in entries.items():
            self.assertIn(key, MODELS)
            self.assertIsInstance(entry["dense_floor"], float)
            self.assertTrue(0 < entry["dense_floor"] < 1)
            self.assertIn("fingerprint", entry)
            self.assertIn("query_fingerprint", entry)
            self.assertEqual(entry["backend"], "torch")
            self.assertEqual(entry["variant"], MODELS[key].dtype_cpu)

    def test_floor_is_keyed_on_backend_and_variant(self) -> None:
        # int8 ONNX lowers the top cosine 0.008-0.053 with the same document
        # fingerprint, so a torch fp32 floor must not apply to it.
        spec = MODELS["granite-english-r2"]
        good = {
            "dense_floor": 0.81,
            "fingerprint": spec.fingerprint(),
            "query_fingerprint": abstain.query_fingerprint(spec),
            "backend": "torch",
            "variant": "fp32",
        }
        path = self.write({"granite-english-r2": good})
        self.assertEqual(floor_for("granite-english-r2", path), 0.81)
        self.assertEqual(floor_for("granite-english-r2", path, backend="torch", variant="fp32"), 0.81)
        self.assertIsNone(floor_for("granite-english-r2", path, backend="onnx", variant="int8"))
        self.assertIsNone(floor_for("granite-english-r2", path, backend="onnx", variant="fp32"))
        unkeyed = {key: value for key, value in good.items() if key not in ("backend", "variant")}
        self.assertIsNone(floor_for("granite-english-r2", self.write({"granite-english-r2": unkeyed})))


def good_entry() -> dict:
    spec = MODELS["granite-english-r2"]
    return {
        "dense_floor": 0.5,
        "fingerprint": spec.fingerprint(),
        "query_fingerprint": abstain.query_fingerprint(spec),
        "backend": "torch",
        "variant": spec.dtype_cpu,
    }


def entry_toml(**overrides) -> str:
    entry = {**good_entry(), **overrides}
    return "[models.granite-english-r2]\n" + "".join(f"{key} = {value}\n" for key, value in (
        (key, json.dumps(value) if isinstance(value, str) else value) for key, value in entry.items()))


# CTO review of PR #11: each of these used to crash server startup or be
# accepted as a floor. Each must leave the server up with abstain off.
BAD_FILES = {
    "truncated TOML": entry_toml().encode()[:60],
    "models = 5": b"models = 5\n",
    "entry not a table": b"[models]\n\"granite-english-r2\" = 0.5\n",
    "not UTF-8": entry_toml().encode().replace(b"[models.", b"\xff\xfe[models.", 1),
    "nan floor": entry_toml(dense_floor="NAN").replace('"NAN"', "nan").encode(),
    "floor 5.0": entry_toml(dense_floor=5.0).encode(),
    "floor -inf": entry_toml(dense_floor="X").replace('"X"', "-inf").encode(),
    "floor is a string": entry_toml(dense_floor="0.5").encode(),
}


class BadCalibrationFileTests(unittest.TestCase):
    """A malformed search/abstain.toml disables the floor; the server starts."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.index = self.dir / "rich.sqlite"
        build_rich_index(self.index)

    def calibration(self, data: bytes) -> Path:
        path = self.dir / "abstain.toml"
        path.write_bytes(data)
        return path

    def start(self, path: Path) -> Running:
        def loader(connection, _model_key):
            return Searcher(connection, model="fixture", fingerprint=FIXTURE_FP), encode_fixture

        with mock.patch.object(abstain, "calibration_path", return_value=path):
            app = build_app(reopen(self.index), model_key="granite-english-r2", bm25_only=False,
                            hosts={"127.0.0.1"}, static_dir=STATIC_DIR, loader=loader)
        running = Running(app)
        self.addCleanup(running.close)
        return running

    def test_good_file_sets_the_floor(self) -> None:
        # Control: the same harness does pick up a valid floor.
        running = self.start(self.calibration(entry_toml().encode()))
        health = json.loads(running.request("GET", "/healthz")[2])
        self.assertTrue(health["abstain_calibrated"])

    def test_bad_files_disable_abstain(self) -> None:
        for name, data in BAD_FILES.items():
            with self.subTest(name):
                path = self.calibration(data)
                with self.assertLogs("preached.abstain", level="WARNING"):
                    self.assertIsNone(floor_for("granite-english-r2", path))
                running = self.start(path)
                health = json.loads(running.request("GET", "/healthz")[2])
                self.assertTrue(health["ok"])
                self.assertTrue(health["dense"])
                self.assertFalse(health["abstain_calibrated"])
                status, _, body = running.request("GET", "/api/search?q=nosuchwordanywhere&mode=hybrid&k=10")
                self.assertEqual(status, 200)
                payload = json.loads(body)
                self.assertFalse(payload["abstain"])
                self.assertFalse(payload["confidence"]["calibrated"])
                self.assertGreater(len(payload["results"]), 0)


class ApiConfidenceTests(unittest.TestCase):
    """Fixture vectors make every dense top cosine 1.0, so a floor of 1.0 is
    'low' and a floor of 0.5 is not."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        path = Path(cls.tmp.name) / "rich.sqlite"
        build_rich_index(path)
        cls.running = []

        def app(floor):
            connection = reopen(path)
            return App(
                connection=connection,
                searcher=Searcher(connection, model="fixture", fingerprint=FIXTURE_FP),
                encode=encode_fixture,
                fallback_note=None,
                model_name="fixture",
                hosts={"127.0.0.1"},
                static_dir=STATIC_DIR,
                floor=floor,
            )

        cls.high = Running(app(1.0))
        cls.low = Running(app(0.5))
        cls.uncalibrated = Running(app(None))
        failed = reopen(path)

        def boom(_connection, _model_key):
            raise RuntimeError("no weights")

        searcher, encode, note = load_search(failed, "granite-english-r2", loader=boom)
        cls.fallback = Running(App(failed, searcher, encode, note, "granite-english-r2", {"127.0.0.1"},
                                   STATIC_DIR, floor=0.99))
        cls.running = [cls.high, cls.low, cls.uncalibrated, cls.fallback]

    @classmethod
    def tearDownClass(cls) -> None:
        for running in cls.running:
            running.close()
        cls.tmp.cleanup()

    def search(self, running: Running, query: str, mode: str = "hybrid") -> dict:
        status, _, body = running.request("GET", f"/api/search?q={query}&mode={mode}&k=10")
        self.assertEqual(status, 200)
        return json.loads(body)

    def test_nothing_found_still_returns_the_closest(self) -> None:
        payload = self.search(self.high, "nosuchwordanywhere")
        self.assertTrue(payload["abstain"])
        self.assertEqual(payload["confidence"]["level"], "none")
        self.assertEqual(payload["confidence"]["note"], abstain.NONE_NOTE)
        self.assertTrue(payload["confidence"]["calibrated"])
        self.assertEqual(payload["confidence"]["signals"]["bm25_hits"], 0)
        self.assertFalse(payload["confidence"]["signals"]["agreement"])
        self.assertGreater(len(payload["results"]), 0)
        self.assertIsNone(payload["note"])

    def test_weak_and_strong(self) -> None:
        weak = self.search(self.high, "zealboundary")
        self.assertFalse(weak["abstain"])
        self.assertEqual(weak["confidence"]["level"], "weak")  # agreement, but dense top is on the floor
        strong = self.search(self.low, "zealboundary")
        self.assertEqual(strong["confidence"]["level"], "strong")
        self.assertIsNone(strong["confidence"]["note"])
        self.assertTrue(strong["confidence"]["signals"]["agreement"])

    def test_uncalibrated_model_does_not_abstain(self) -> None:
        payload = self.search(self.uncalibrated, "nosuchwordanywhere")
        self.assertFalse(payload["abstain"])
        self.assertEqual(payload["confidence"]["level"], "weak")
        self.assertFalse(payload["confidence"]["calibrated"])

    def test_bm25_fallback(self) -> None:
        found = self.search(self.fallback, "zealboundary")
        self.assertEqual(found["mode"], "bm25")
        self.assertEqual(found["note"], FALLBACK_NOTE)
        self.assertFalse(found["abstain"])
        self.assertEqual(found["confidence"]["level"], "unrated")
        self.assertFalse(found["confidence"]["calibrated"])  # the floor is ignored without vectors
        empty = self.search(self.fallback, "nosuchwordanywhere")
        self.assertTrue(empty["abstain"])
        self.assertEqual(empty["results"], [])
        self.assertEqual(empty["confidence"]["level"], "none")
        health = json.loads(self.fallback.request("GET", "/healthz")[2])
        self.assertFalse(health["abstain_calibrated"])

    def test_bm25_mode_ignores_the_floor(self) -> None:
        payload = self.search(self.high, "zealboundary", mode="bm25")
        self.assertEqual(payload["confidence"]["level"], "unrated")

    def test_merged_neighbour_is_one_result(self) -> None:
        payload = self.search(self.low, "zealboundary", mode="bm25")
        merged = [hit for hit in payload["results"] if hit["chunk_id"] == "keep"]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["chunk_ids"], ["keep", "neighbor"])
        self.assertEqual(merged[0]["text"].count("shared0"), 1)  # the overlap is not shown twice
        self.assertIn("beta passage", merged[0]["text"])


if __name__ == "__main__":
    unittest.main()
