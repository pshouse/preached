"""The church side of /api/side, /api/search and ``query.py --side``, served
only through #12's publish gate (40-W3-CHURCH-GATE-WIRE).

Every church file here is a synthetic fixture. No real church audio or
transcript is used.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import ExitStack, closing, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app.server as server  # noqa: E402
from app.server import STATIC_DIR, App, Searcher, build_app, load_church_searcher  # noqa: E402
from preached.library import ChurchRefused, church_file_problem, open_church_readonly  # noqa: E402
import preached.search as search_module  # noqa: E402
import preached.store as store  # noqa: E402
from preached.store import connect, save_embedding_info, write_embeddings  # noqa: E402
from preached.youtube.library import ensure_library  # noqa: E402
from test_side import (  # noqa: E402
    CHURCH_EMPTY,
    CLASSIC_AUDIO,
    FIXTURE_FP,
    Running,
    _insert,
    _load_query,
    _section,
    _without_took,
    build_library,
    classic_rows,
    encode_fixture,
    reopen,
)

PRIVACY = Path(__file__).resolve().parents[1] / "privacy.example.toml"
EVAL_ONLY = "arctic-embed-l"
# The deploy switch every server-side church test sets (PR #37 r1 should-fix 4).
CHURCH_ON = {"PREACHED_CHURCH_SIDE": "enabled"}

# One token per sermon. Only VISIBLE ones may ever leave the church file.
VISIBLE = {"approvedtoken": "churchvid01", "sharedpulpit": "churchvid02", "flaggedtoken": "churchvid03"}
HIDDEN = {
    "unapprovedtoken": "churchvid04",  # approved_sha256 NULL
    "stalereviewtoken": "churchvid05",  # approved an older review file
    "gaptoken": "churchvid06",  # ASR coverage found an open gap
    "uncheckedtoken": "churchvid07",  # coverage never checked (NULL)
    "failedtoken": "churchvid08",  # status is not 'ok'
    "orphantoken": None,  # chunk with no video_id
}
HIDDEN_TITLES = ("Unapproved Sermon", "Stale Review", "Gap Sermon", "Unchecked Sermon", "Failed Import", "Orphan")

VIDEOS = [
    # video_id, status, review_sha256, approved_sha256, coverage_gaps
    ("churchvid01", "ok", "r1", "r1", "[]"),
    ("churchvid02", "ok", "r2", "r2", "[]"),
    ("churchvid03", "ok", "r3", "r3", "[]"),
    ("churchvid04", "ok", "r4", None, "[]"),
    ("churchvid05", "ok", "r5-new", "r5-old", "[]"),
    ("churchvid06", "ok", "r6", "r6", "[[10.0, 25.0]]"),
    ("churchvid07", "ok", "r7", "r7", None),
    ("churchvid08", "error", "r8", "r8", "[]"),
]


def _watch(vid: str, t: int | None = None) -> str:
    return f"https://www.youtube.com/watch?v={vid}" + (f"&t={t}s" if t is not None else "")


def church_fixture_rows() -> tuple[list[dict], list[list[float]]]:
    def row(chunk_id, vid, title, text, start, end, words, **extra):
        base = {
            "chunk_id": chunk_id,
            "sermon_id": vid or "orphan-sermon",
            "sermon_number": None,
            "sermon_title": title,
            "text": text,
            "scripture": None,
            "source_url": _watch(vid or "orphanvid00"),
            "start_s": start,
            "end_s": end,
            "audio_url": _watch(vid or "orphanvid00", int(start)),
            "reader": None,
            "text_source": "asr",
            "librivox_id": None,
            "word_start": words[0],
            "word_end": words[1],
        }
        base.update(extra)
        return base

    rows = [
        row("c-approved", "churchvid01", "Approved Sermon", "approvedtoken mercy for the weary.", 30.0, 45.0, (0, 6)),
        row("c-shared", "churchvid02", "Shared Sermon", "sharedpulpit hope for the sample church.", 60.0, 75.0, (0, 6)),
        # Flagged chunk (a redacted name) and a far-away sibling in the same sermon.
        row("c-flagged", "churchvid03", "Flagged Sermon", "flaggedtoken prayer for [name] this week.", 100.0, 110.0, (0, 7)),
        row("c-flag-sib", "churchvid03", "Flagged Sermon", "siblingtoken a later word on grace.", 900.0, 915.0, (500, 507)),
        # A name at the very end of one chunk, and the chunk right after it: the
        # next card's pre-roll would play the name (PR #37 r1 should-fix 2).
        row("c-near-flag", "churchvid03", "Flagged Sermon", "nearflagtoken thanks to [name].", 200.0, 210.0, (100, 105)),
        row("c-adjacent", "churchvid03", "Flagged Sermon", "adjacenttoken the next words.", 210.0, 225.0, (105, 110)),
        row("c-unapproved", "churchvid04", "Unapproved Sermon", "unapprovedtoken sharedpulpit words.", 10.0, 20.0, (0, 4)),
        row("c-stale", "churchvid05", "Stale Review", "stalereviewtoken sharedpulpit words.", 10.0, 20.0, (0, 4)),
        row("c-gap", "churchvid06", "Gap Sermon", "gaptoken sharedpulpit words.", 10.0, 20.0, (0, 4)),
        row("c-unchecked", "churchvid07", "Unchecked Sermon", "uncheckedtoken sharedpulpit words.", 10.0, 20.0, (0, 4)),
        row("c-failed", "churchvid08", "Failed Import", "failedtoken sharedpulpit words.", 10.0, 20.0, (0, 4)),
        row("c-orphan", None, "Orphan", "orphantoken sharedpulpit words.", 10.0, 20.0, (0, 4)),
    ]
    # Hidden rows sit right on the query vector, so a leak through dense would win.
    vectors = [[0, 0.8, 0.6, 0], [0, 0.8, 0.6, 0], [0, 0.8, 0.6, 0], [0, 0.8, 0.6, 0], [0, 0, 0, 1], [0, 0, 0, 1]]
    vectors += [[1, 0, 0, 0]] * 6
    return rows, vectors


def build_church(path: Path, *, model: str = "fixture", fingerprint: str = FIXTURE_FP) -> None:
    """A synthetic church import: YouTube-shaped rows, the publish-gate columns, one flagged chunk."""
    rows, vectors = church_fixture_rows()
    connection = connect(path)
    ensure_library(connection)
    for item in rows:
        _insert(connection, **item)
    connection.execute("UPDATE chunks SET video_id = CASE WHEN sermon_id = 'orphan-sermon' THEN NULL ELSE sermon_id END")
    connection.execute("UPDATE chunks SET flag_end_s = 104.0 WHERE chunk_id = 'c-flagged'")
    connection.execute("UPDATE chunks SET flag_end_s = 209.8 WHERE chunk_id = 'c-near-flag'")
    connection.executemany(
        "INSERT INTO videos (video_id, status, review_sha256, approved_sha256, coverage_gaps) VALUES (?, ?, ?, ?, ?)",
        VIDEOS,
    )
    connection.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('role', 'church')")
    connection.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('sample', '1')")
    connection.commit()
    rowids = [int(r[0]) for r in connection.execute("SELECT rowid FROM chunks ORDER BY rowid")]
    write_embeddings(connection, model, rowids, np.array(vectors, dtype=np.float32))
    save_embedding_info(connection, model, {"fingerprint": fingerprint})
    connection.commit()
    # As --ack-review leaves it: DELETE mode, so the read-only open makes no -wal/-shm.
    assert connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
    connection.close()


def delete_mode(path: Path) -> Path:
    """Leave a fixture in DELETE journal mode, as --ack-review does."""
    with closing(sqlite3.connect(path)) as writer:
        assert writer.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def leaks(body) -> list[str]:
    """Hidden church tokens, titles or video ids found anywhere outside the echoed query."""
    payload = body if isinstance(body, (dict, list)) else json.loads(body)
    text = json.dumps(_drop_query(payload), ensure_ascii=False)
    found = [token for token in HIDDEN if token in text]
    found += [title for title in HIDDEN_TITLES if title in text]
    found += [vid for vid in HIDDEN.values() if vid and vid in text]
    return found


def _drop_query(value):
    if isinstance(value, dict):
        return {k: _drop_query(v) for k, v in value.items() if k != "query"}
    if isinstance(value, list):
        return [_drop_query(v) for v in value]
    return value


def church_app(classic_path: Path, church_path: Path | None, *, check=None, encode=encode_fixture) -> App:
    classic = reopen(classic_path)
    church = reopen(church_path) if church_path is not None else None
    return App(
        connection=classic,
        searcher=Searcher(classic, model="fixture", fingerprint=FIXTURE_FP),
        encode=encode,
        fallback_note=None,
        model_name="fixture",
        hosts={"127.0.0.1", "localhost"},
        static_dir=STATIC_DIR,
        library="wesley",
        floor=0.5,
        church_connection=church,
        # Built without the gate on purpose: App must turn it on.
        church_searcher=Searcher(church, model="fixture", fingerprint=FIXTURE_FP) if church is not None else None,
        church_library="sample" if church is not None else None,
        church_check=check,
    )


QUERIES = (
    "approvedtoken",
    "sharedpulpit",
    "flaggedtoken",
    "siblingtoken",
    *HIDDEN,
    "words",
)


class ChurchServedTests(unittest.TestCase):
    """Approved, visible church passages appear; nothing hidden ever does."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.classic_path = root / "wesley.sqlite"
        cls.church_path = root / "sample.sqlite"
        build_library(cls.classic_path, *classic_rows())
        build_church(cls.church_path)
        cls.church_sha = sha(cls.church_path)
        cls.both = Running(church_app(cls.classic_path, cls.church_path))
        cls.classic_only = Running(church_app(cls.classic_path, None))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.both.close()
        cls.classic_only.close()
        cls.tmp.cleanup()

    def get_json(self, running: Running, path: str) -> tuple[int, dict]:
        status, _headers, body = running.get(path)
        return status, json.loads(body)

    def test_approved_church_passages_appear_beside_the_classic_side(self) -> None:
        status, payload = self.get_json(self.both, "/api/side?q=approvedtoken&mode=bm25&k=5")
        self.assertEqual(status, 200)
        church = payload["church"]
        self.assertEqual(church["library"], "sample")
        self.assertEqual(church["label"], "Your church")
        self.assertTrue(church["sample"])
        self.assertTrue(church["present"])
        self.assertFalse(church["empty"])
        self.assertIsNone(church["message"])
        self.assertEqual(church["mode"], "bm25")
        self.assertFalse(church["abstain"])
        self.assertEqual(church["confidence"]["level"], "unrated")
        self.assertFalse(church["confidence"]["calibrated"])
        self.assertEqual([hit["chunk_id"] for hit in church["results"]], ["c-approved"])
        hit = church["results"][0]
        # Cited and playable from its own time (rebuilt watch link, pre-roll).
        self.assertEqual(hit["start_s"], 30.0)
        self.assertTrue(hit["audio_url"].startswith(_watch("churchvid01")))
        self.assertIn("&t=", hit["audio_url"])
        self.assertEqual(hit["source_url"], _watch("churchvid01"))
        # The classic side is the same as without a church.
        _, only = self.get_json(self.classic_only, "/api/side?q=approvedtoken&mode=bm25&k=5")
        self.assertEqual(payload["classic"], only["classic"])

        for mode in ("dense", "hybrid"):
            status, payload = self.get_json(self.both, f"/api/side?q=sharedpulpit&mode={mode}&k=5")
            self.assertEqual(status, 200)
            got = {hit["chunk_id"] for hit in payload["church"]["results"]}
            self.assertIn("c-shared", got, mode)
            self.assertEqual(payload["church"]["mode"], mode)
            self.assertEqual(leaks(payload), [], mode)

    def test_api_search_takes_the_church_slug_and_stays_gated(self) -> None:
        status, payload = self.get_json(self.both, "/api/search?q=sharedpulpit&library=sample&mode=bm25&k=10")
        self.assertEqual(status, 200)
        self.assertEqual({hit["chunk_id"] for hit in payload["results"]}, {"c-shared"})
        self.assertEqual(payload["confidence"]["level"], "unrated")
        self.assertEqual(leaks(payload), [])
        # A classic search never sees church rows, and an unknown slug is still a 400.
        status, payload = self.get_json(self.both, "/api/search?q=approvedtoken&library=wesley&mode=bm25")
        self.assertEqual((status, payload["results"]), (200, []))
        status, payload = self.get_json(self.both, "/api/search?q=approvedtoken&library=spurgeon&mode=bm25")
        self.assertEqual((status, payload["error"]), (400, "library must be wesley"))
        status, payload = self.get_json(self.classic_only, "/api/search?q=approvedtoken&library=sample&mode=bm25")
        self.assertEqual((status, payload["error"]), (400, "library must be wesley"))

    def test_unapproved_flagged_coverage_gap_and_unchecked_content_never_appears(self) -> None:
        for query in QUERIES:
            for mode in ("bm25", "dense", "hybrid"):
                for path in (
                    f"/api/side?q={query}&mode={mode}&k=25",
                    f"/api/search?q={query}&library=sample&mode={mode}&k=25",
                ):
                    with self.subTest(path=path):
                        status, _headers, body = self.both.get(path)
                        self.assertEqual(status, 200)
                        self.assertEqual(leaks(body), [])
        # A hidden sermon's word is not even counted: same confidence as a word nowhere.
        _, hidden = self.get_json(self.both, "/api/search?q=unapprovedtoken&library=sample&mode=bm25")
        _, nowhere = self.get_json(self.both, "/api/search?q=zzznotawordzzz&library=sample&mode=bm25")
        self.assertEqual(hidden["confidence"], nowhere["confidence"])
        self.assertEqual(hidden["results"], [])

    def test_flagged_passage_has_no_audio_and_its_sermon_no_untimed_link(self) -> None:
        _, payload = self.get_json(self.both, "/api/side?q=flaggedtoken&mode=bm25&k=5")
        (hit,) = payload["church"]["results"]
        self.assertEqual(hit["chunk_id"], "c-flagged")
        self.assertIn("[name]", hit["text"])
        self.assertIsNone(hit["audio_url"])
        self.assertIsNone(hit["start_s"])
        self.assertIsNone(hit["end_s"])
        self.assertIsNone(hit["source_url"])
        self.assertTrue(hit["audio_withheld"])
        _, payload = self.get_json(self.both, "/api/side?q=siblingtoken&mode=bm25&k=5")
        (sibling,) = payload["church"]["results"]
        # Same sermon, far from the name: only its own timed link, no source link from 0:00.
        self.assertIsNone(sibling["source_url"])
        self.assertIn("&t=", sibling["audio_url"])

    def test_the_chunk_right_after_a_flagged_name_has_no_audio(self) -> None:
        # PR #37 r1 should-fix 2: c-near-flag's name ends at 209.8 s and
        # c-adjacent starts at 210 s, so its pre-roll link would play it.
        _, payload = self.get_json(self.both, "/api/side?q=adjacenttoken&mode=bm25&k=5")
        (hit,) = payload["church"]["results"]
        self.assertEqual(hit["chunk_id"], "c-adjacent")
        self.assertNotIn("[name]", hit["text"])
        self.assertIsNone(hit["audio_url"])
        self.assertIsNone(hit["start_s"])
        self.assertIsNone(hit["source_url"])
        self.assertTrue(hit["audio_withheld"])
        _, searched = self.get_json(self.both, "/api/search?q=adjacenttoken&mode=bm25&k=5&library=sample")
        self.assertEqual(searched["results"], payload["church"]["results"])

    def test_approval_while_running_applies_to_the_next_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            classic_path = root / "wesley.sqlite"
            church_path = root / "sample.sqlite"
            build_library(classic_path, *classic_rows())
            build_church(church_path)
            app = church_app(classic_path, church_path)
            self.assertEqual(app.side("unapprovedtoken", 5, "bm25")["church"]["results"], [])
            with closing(sqlite3.connect(church_path)) as writer:
                writer.execute("UPDATE videos SET approved_sha256 = review_sha256 WHERE video_id = 'churchvid04'")
                writer.commit()
            got = [hit["chunk_id"] for hit in app.side("unapprovedtoken", 5, "bm25")["church"]["results"]]
            self.assertEqual(got, ["c-unapproved"])
            with closing(sqlite3.connect(church_path)) as writer:
                writer.execute("UPDATE videos SET coverage_gaps = '[[1.0, 2.0]]' WHERE video_id = 'churchvid01'")
                writer.commit()
            self.assertEqual(app.side("approvedtoken", 5, "bm25")["church"]["results"], [])

    def test_eval_only_vectors_are_never_used_for_the_church_side(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            church_path = root / "sample.sqlite"
            # Vectors stored only under an eval-only model key.
            build_church(church_path, model=EVAL_ONLY, fingerprint="eval-fp")
            church = reopen(church_path)
            try:
                with patch.object(server.logging, "exception"):
                    searcher, note = load_church_searcher(church, EVAL_ONLY, bm25_only=False)
                self.assertIsNone(searcher._matrix)
                self.assertIs(searcher.gated, True)
                self.assertEqual(note, server.STALE_NOTE)
                with patch.object(server.logging, "exception"):
                    searcher, note = load_church_searcher(church, "granite-english-r2", bm25_only=False)
                self.assertIsNone(searcher._matrix)
                self.assertEqual(note, server.STALE_NOTE)
            finally:
                church.close()
            classic_path = root / "wesley.sqlite"
            build_library(classic_path, *classic_rows())

            def loader(connection, _model):
                return Searcher(connection, model="fixture", fingerprint=FIXTURE_FP), encode_fixture

            with patch.object(server.logging, "exception"):
                app = build_app(
                    reopen(classic_path),
                    model_key="granite-english-r2",
                    bm25_only=False,
                    hosts={"127.0.0.1"},
                    static_dir=STATIC_DIR,
                    loader=loader,
                    floor=0.5,
                    church_connection=reopen(church_path),
                    church_library="sample",
                )
            side = app.side("sharedpulpit", 5, "hybrid")
            self.assertEqual(side["church"]["mode"], "bm25")
            self.assertEqual(side["church"]["note"], server.STALE_NOTE)
            self.assertEqual([hit["chunk_id"] for hit in side["church"]["results"]], ["c-shared"])
            self.assertEqual(leaks(side), [])

    def test_healthz_says_nothing_about_the_church(self) -> None:
        _, health_both = self.get_json(self.both, "/healthz")
        _, health_only = self.get_json(self.classic_only, "/healthz")
        self.assertIsNone(health_both["church"])
        self.assertEqual(health_both, health_only)
        self.assertNotIn("sample", json.dumps(health_both))

    def test_serving_writes_nothing_to_the_church_file(self) -> None:
        for query in ("approvedtoken", "sharedpulpit", "flaggedtoken"):
            self.both.get(f"/api/side?q={query}&mode=hybrid&k=5")
        self.assertEqual(sha(self.church_path), self.church_sha)


class GateOffMutationTests(unittest.TestCase):
    """The leak checks above are not vacuous: with the gate off they fire."""

    def run_mutated(self, *patches) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            classic_path = root / "wesley.sqlite"
            church_path = root / "sample.sqlite"
            build_library(classic_path, *classic_rows())
            build_church(church_path)
            for target in patches:
                stack.enter_context(target)
            app = church_app(classic_path, church_path)
            found: list[str] = []
            for query in HIDDEN:
                found += leaks(app.side(query, 25, "bm25"))
            return found

    def test_visible_sql_off_leaks(self) -> None:
        off = patch.object(search_module, "visible_sql", lambda *_a, **_k: None)
        self.assertTrue(self.run_mutated(off))

    def test_gate_on_skipped_refuses_the_church_side(self) -> None:
        """church_app builds its church Searcher ungated; App turns the gate on.

        With ``gate_on`` a no-op, App sees the gate still off and refuses the
        church side instead of serving it. (A church-shaped file is also gated
        by its schema in ``store.visible_sql``; this is the second lock.)
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            classic_path = root / "wesley.sqlite"
            church_path = root / "sample.sqlite"
            build_library(classic_path, *classic_rows())
            build_church(church_path)
            with patch.object(Searcher, "gate_on", lambda self: None), self.assertLogs(level="ERROR") as logs:
                app = church_app(classic_path, church_path)
            self.assertIn("publish gate did not turn on", "\n".join(logs.output))
            self.assertIsNone(app.church_searcher)
            self.assertFalse(app.side("unapprovedtoken", 25, "bm25")["church"]["present"])

    def test_coverage_condition_removed_leaks(self) -> None:
        real = store.visible_sql

        def no_coverage(*args, **kwargs):
            sql = real(*args, **kwargs)
            return sql.replace(" AND v.coverage_gaps = '[]'", "") if sql else sql

        found = self.run_mutated(patch.object(search_module, "visible_sql", no_coverage))
        self.assertIn("gaptoken", found)
        self.assertIn("uncheckedtoken", found)

    def test_unmutated_does_not_leak(self) -> None:
        self.assertEqual(self.run_mutated(), [])


class ChurchRefusalAtOpenTests(unittest.TestCase):
    """Any open, gate or sidecar problem: no church results, a logged refusal, the classic side serves."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.index_dir = self.root / "index"
        self.index_dir.mkdir()
        self.wesley = self.index_dir / "wesley.sqlite"
        build_library(self.wesley, *classic_rows())
        self.church = self.index_dir / "mychurch.sqlite"
        build_church(self.church)
        for target in (
            patch("preached.paths.INDEX_DIR", self.index_dir),
            patch("preached.paths.INDEX_PATH", self.wesley),
            patch.dict(os.environ, {"PREACHED_PRIVACY": str(PRIVACY), **CHURCH_ON}),
        ):
            target.start()
            self.addCleanup(target.stop)

    def refused(self, path: Path | None = None) -> str:
        path = self.church if path is None else path
        with self.assertLogs(level="ERROR") as logs:
            self.assertIsNone(
                server.open_church(path, slug=None, classic_library="wesley", classic_index=self.wesley)
            )
        (line,) = logs.output
        self.assertIn("church side refused", line)
        return line

    def test_a_good_church_file_opens_read_only(self) -> None:
        before = sha(self.church)
        with self.assertLogs(level="INFO") as logs:
            opened = server.open_church(self.church, slug=None, classic_library="wesley", classic_index=self.wesley)
        self.assertIsNotNone(opened)
        connection, slug, check = opened
        try:
            self.assertEqual(slug, "mychurch")
            self.assertIsNone(check(connection))
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("UPDATE videos SET approved_sha256 = 'x'")
        finally:
            connection.close()
        self.assertIn("through the publish gate", logs.output[-1])
        self.assertEqual(sha(self.church), before)

    def test_no_privacy_config(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PREACHED_PRIVACY", None)
            self.assertIn("privacy config", self.refused())

    def test_missing_file(self) -> None:
        self.assertIn("not found", self.refused(self.index_dir / "absent.sqlite"))

    def test_hardlinked_sidecar_to_wesley(self) -> None:
        wesley_before = sha(self.wesley)
        for suffix in ("-wal", "-shm", "-journal"):
            with self.subTest(suffix=suffix):
                sidecar = Path(f"{self.church}{suffix}")
                sidecar.unlink(missing_ok=True)
                os.link(self.wesley, sidecar)
                try:
                    self.assertIn("2 hard links", self.refused())
                finally:
                    sidecar.unlink()
                self.assertEqual(sha(self.wesley), wesley_before)

    def test_not_a_church_import(self) -> None:
        plain = self.index_dir / "plain.sqlite"
        build_library(plain, *classic_rows())
        self.assertIn("not a church import", self.refused(delete_mode(plain)))

    def test_no_publish_gate_columns(self) -> None:
        bare = self.index_dir / "bare.sqlite"
        with closing(sqlite3.connect(bare)) as writer:
            writer.execute("CREATE TABLE chunks (chunk_id TEXT, text TEXT, video_id TEXT)")
            writer.execute("CREATE TABLE videos (video_id TEXT PRIMARY KEY, status TEXT)")
            writer.commit()
        self.assertIn("no publish-gate columns", self.refused(bare))

    def test_the_classic_index_is_not_the_church(self) -> None:
        self.assertIn("classic", self.refused(self.wesley))

    def test_hardlinked_church_file(self) -> None:
        os.link(self.church, self.root / "other-name.sqlite")
        self.assertIn("2 hard links", self.refused())

    def test_world_writable_church_file(self) -> None:
        os.chmod(self.church, 0o666)
        self.assertIn("world-writable", self.refused())

    # PR #37 r1 must-fix 2: a symlink, and the real file's owner and directory.

    def shared_dir(self) -> Path:
        """A directory every local user can write, holding a church file."""
        shared = self.root / "shared"
        shared.mkdir()
        os.chmod(shared, 0o777)
        self.addCleanup(os.chmod, shared, 0o700)
        build_church(shared / "mychurch.sqlite")
        return shared

    def test_symlink_into_a_world_writable_directory_is_refused(self) -> None:
        # The CTO case: refused by name in the 0777 directory, but served
        # through a symlink from the 0755 index directory.
        real = self.shared_dir() / "mychurch.sqlite"
        self.assertIn("world-writable", self.refused(real))
        link = self.index_dir / "linked.sqlite"
        os.symlink(real, link)
        self.assertIsNone(server.writable_problem(link))  # the old check looked at the link's directory
        self.assertIn("linked.sqlite is a symlink", self.refused(link))

    def test_symlink_to_a_safe_church_file_is_refused_too(self) -> None:
        link = self.index_dir / "linked.sqlite"
        os.symlink(self.church, link)
        self.assertIn("linked.sqlite is a symlink", self.refused(link))
        with self.assertRaises(ChurchRefused) as caught:
            open_church_readonly(link, classic=self.wesley)
        self.assertIn("is a symlink", str(caught.exception))

    def test_real_directory_behind_a_symlinked_parent_is_checked(self) -> None:
        # The name is a plain file, but its directory is a symlink to a 0777 one.
        shared = self.shared_dir()
        via = self.index_dir / "via"
        os.symlink(shared, via)
        with self.assertRaises(ChurchRefused) as caught:
            open_church_readonly(via / "mychurch.sqlite", classic=self.wesley)
        self.assertIn(f"church file's directory {shared}", str(caught.exception))
        self.assertIn("world-writable", str(caught.exception))

    def test_church_file_owned_by_another_user_is_refused(self) -> None:
        with patch("preached.library.os.geteuid", return_value=os.geteuid() + 4242):
            line = self.refused()
        self.assertIn(f"church file {self.church.resolve()} is owned by uid {os.geteuid()}", line)

    def test_church_directory_owned_by_another_user_is_refused(self) -> None:
        real_stat = os.stat
        directory = self.church.resolve().parent

        def stat(target, *args, **kwargs):
            st = real_stat(target, *args, **kwargs)
            if Path(target) == directory:
                values = list(st)
                values[4] = st.st_uid + 4242  # st_uid
                return os.stat_result(values)
            return st

        with patch("preached.library.os.stat", side_effect=stat):
            line = self.refused()
        self.assertIn(f"church file's directory {directory} is owned by uid", line)

    # PR #37 r1 should-fix 6: a WAL-mode church file is not opened.

    def test_wal_mode_church_file_is_refused_and_no_sidecar_appears(self) -> None:
        with closing(sqlite3.connect(self.church)) as writer:
            self.assertEqual(writer.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        before = sha(self.church)
        self.assertIn("WAL journal mode", self.refused())
        for suffix in ("-wal", "-shm"):
            self.assertFalse(Path(f"{self.church}{suffix}").exists(), suffix)
        self.assertEqual(sha(self.church), before)

    def test_delete_mode_church_file_opens_with_no_sidecar(self) -> None:
        with self.assertLogs(level="INFO"):
            connection, _slug, check = server.open_church(
                self.church, slug=None, classic_library="wesley", classic_index=self.wesley
            )
        try:
            self.assertIsNone(check(connection))
            connection.execute("SELECT count(*) FROM chunks").fetchone()
            for suffix in ("-wal", "-shm", "-journal"):
                self.assertFalse(Path(f"{self.church}{suffix}").exists(), suffix)
        finally:
            connection.close()

    def test_symlink_owner_and_wal_are_refused_before_any_connect(self) -> None:
        link = self.index_dir / "linked.sqlite"
        os.symlink(self.church, link)
        wal = self.index_dir / "walchurch.sqlite"
        build_church(wal)
        with closing(sqlite3.connect(wal)) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
        cases = {
            "is a symlink": (link, {}),
            "is owned by uid": (self.church, {"return_value": os.geteuid() + 4242}),
            "WAL journal mode": (wal, {}),
        }
        for want, (path, euid) in cases.items():
            with self.subTest(want=want), ExitStack() as stack:
                stack.enter_context(patch("preached.library.open_readonly", side_effect=AssertionError("connected")))
                if euid:
                    stack.enter_context(patch("preached.library.os.geteuid", **euid))
                with self.assertRaises(ChurchRefused) as caught:
                    open_church_readonly(path, classic=self.wesley)
                self.assertIn(want, str(caught.exception))

    def test_open_church_readonly_raises_a_refusal_not_a_crash(self) -> None:
        with self.assertRaises(ChurchRefused):
            open_church_readonly(self.index_dir / "absent.sqlite")


class ChurchRefusalWhileServingTests(unittest.TestCase):
    """A problem found after start drops the church side; the classic side keeps serving."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.classic_path = root / "wesley.sqlite"
        self.church_path = root / "sample.sqlite"
        build_library(self.classic_path, *classic_rows())
        build_church(self.church_path)
        self.identity = (os.stat(self.church_path).st_dev, os.stat(self.church_path).st_ino)

    def app(self) -> App:
        path, identity = self.church_path, self.identity
        return church_app(
            self.classic_path, self.church_path, check=lambda conn: church_file_problem(conn, path, identity)
        )

    def assert_church_gone(self, app: App) -> None:
        with self.assertLogs(level="ERROR") as logs:
            side = app.side("approvedtoken", 5, "bm25")
        self.assertIn("church side refused", "\n".join(logs.output))
        self.assertFalse(side["church"]["present"])
        self.assertEqual(side["church"]["results"], [])
        self.assertIsNone(side["church"]["library"])
        classic = app.side("classiconlytoken", 5, "bm25")["classic"]
        self.assertIn("classiconlytoken", " ".join(hit["text"] for hit in classic["results"]))
        self.assertTrue(all(hit["audio_url"] == CLASSIC_AUDIO for hit in classic["results"]))
        # And it stays gone: the slug is no longer an open library.
        with self.assertRaises(server.BadRequest):
            app.search("approvedtoken", 5, "bm25", library="sample")

    def test_file_replaced_after_start(self) -> None:
        app = self.app()
        self.assertTrue(app.side("approvedtoken", 5, "bm25")["church"]["results"])
        replacement = self.church_path.with_name("new.sqlite")
        build_church(replacement)
        os.replace(replacement, self.church_path)
        self.assert_church_gone(app)

    def test_sidecar_planted_after_start(self) -> None:
        app = self.app()
        self.assertTrue(app.side("approvedtoken", 5, "bm25")["church"]["results"])
        sidecar = Path(f"{self.church_path}-journal")
        os.link(self.classic_path, sidecar)
        self.addCleanup(sidecar.unlink, missing_ok=True)
        self.assert_church_gone(app)

    def test_church_search_exception_leaves_the_classic_side(self) -> None:
        app = self.app()

        def boom(*_a, **_k):
            raise sqlite3.DatabaseError("disk image is malformed")

        with patch.object(server, "api_search", side_effect=lambda searcher, *a, **k: (
            boom() if searcher is app.church_searcher else search_module.api_search(searcher, *a, **k)
        )):
            with self.assertLogs(level="ERROR"):
                side = app.side("classiconlytoken", 5, "bm25")
        self.assertFalse(side["church"]["present"])
        self.assertTrue(side["classic"]["results"])

    def test_name_swapped_for_a_symlink_to_the_same_file_after_start(self) -> None:
        # Same inode, one link: only the symlink rule sees it.
        app = self.app()
        self.assertTrue(app.side("approvedtoken", 5, "bm25")["church"]["results"])
        moved = self.church_path.parent / "elsewhere"
        moved.mkdir()
        os.replace(self.church_path, moved / "sample.sqlite")
        os.symlink(moved / "sample.sqlite", self.church_path)
        self.assert_church_gone(app)

    def test_owner_change_after_start(self) -> None:
        app = self.app()
        self.assertTrue(app.side("approvedtoken", 5, "bm25")["church"]["results"])
        with patch("preached.library.os.geteuid", return_value=os.geteuid() + 4242):
            self.assert_church_gone(app)

    def test_wal_mode_while_serving_skips_the_request_without_dropping(self) -> None:
        app = self.app()
        self.assertTrue(app.side("approvedtoken", 5, "bm25")["church"]["results"])
        writer = sqlite3.connect(self.church_path)
        self.assertEqual(writer.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        with self.assertLogs(level="INFO") as logs:
            side = app.side("approvedtoken", 5, "bm25")
        self.assertIn("church side skipped for this request", "\n".join(logs.output))
        self.assertNotIn("ERROR", "\n".join(logs.output))
        self.assertFalse(side["church"]["present"])
        self.assertEqual(app.church_library, "sample")  # paused, not dropped
        for suffix in ("-wal", "-shm"):
            self.assertFalse(Path(f"{self.church_path}{suffix}").exists(), suffix)  # nothing read
        self.assertEqual(writer.execute("PRAGMA journal_mode=DELETE").fetchone()[0], "delete")
        writer.close()
        self.assertTrue(app.side("approvedtoken", 5, "bm25")["church"]["results"])

    def test_400_text_is_the_same_with_without_and_after_a_dropped_church(self) -> None:
        # PR #37 r1 should-fix 3: the 400 does not reveal a church side.
        both, none = Running(self.app()), Running(church_app(self.classic_path, None))
        self.addCleanup(both.close)
        self.addCleanup(none.close)

        def error(running, slug):
            status, _h, body = running.get(f"/api/search?q=approvedtoken&mode=bm25&library={slug}")
            self.assertEqual(status, 400, slug)
            return json.loads(body)["error"]

        want = error(none, "sample")
        self.assertEqual(want, "library must be wesley")
        self.assertEqual(error(none, "spurgeon"), want)
        self.assertEqual(error(both, "spurgeon"), want)
        status, _h, _body = both.get("/api/search?q=approvedtoken&mode=bm25&library=sample")
        self.assertEqual(status, 200)
        with closing(sqlite3.connect(self.church_path)) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            with self.assertLogs(level="INFO"):
                self.assertEqual(error(both, "sample"), want)  # paused for this request
            writer.execute("PRAGMA journal_mode=DELETE")
        status, _h, _body = both.get("/api/search?q=approvedtoken&mode=bm25&library=sample")
        self.assertEqual(status, 200)
        os.chmod(self.church_path, 0o666)
        with self.assertLogs(level="ERROR"):
            self.assertEqual(error(both, "sample"), want)  # dropped now
        self.assertEqual(error(both, "spurgeon"), want)

    def test_check_that_raises_is_a_refusal(self) -> None:
        app = church_app(self.classic_path, self.church_path, check=lambda conn: 1 / 0)
        self.assert_church_gone(app)

    def test_app_clears_a_slug_on_the_church_searcher(self) -> None:
        """A slug on the church searcher could earn the public-domain exemption
        (``store.public_domain_file``); App keeps it None."""
        classic = reopen(self.classic_path)
        church = reopen(self.church_path)
        self.addCleanup(classic.close)
        self.addCleanup(church.close)
        app = App(
            connection=classic,
            searcher=Searcher(classic),
            encode=None,
            fallback_note=None,
            model_name="fixture",
            hosts={"127.0.0.1"},
            static_dir=STATIC_DIR,
            church_connection=church,
            church_searcher=Searcher(church, gated=True, library="spurgeon"),
            church_library="sample",
        )
        self.assertIsNone(app.church_searcher.library)
        self.assertIs(app.church_searcher.gated, True)

    def test_mismatched_parts_are_refused(self) -> None:
        classic = reopen(self.classic_path)
        church = reopen(self.church_path)
        other = reopen(self.church_path)
        self.addCleanup(classic.close)
        self.addCleanup(church.close)
        self.addCleanup(other.close)
        for kwargs in (
            {"church_connection": church, "church_searcher": Searcher(other), "church_library": "sample"},
            {"church_connection": church, "church_searcher": Searcher(church), "church_library": "wesley"},
            {"church_connection": church, "church_searcher": Searcher(church), "church_library": "spurgeon"},
            {"church_connection": church, "church_searcher": None, "church_library": "sample"},
        ):
            with self.subTest(kwargs=kwargs["church_library"]), self.assertLogs(level="ERROR"):
                app = App(
                    connection=classic,
                    searcher=Searcher(classic),
                    encode=None,
                    fallback_note=None,
                    model_name="fixture",
                    hosts={"127.0.0.1"},
                    static_dir=STATIC_DIR,
                    **kwargs,
                )
            self.assertIsNone(app.church_searcher)
            self.assertFalse(app.side("approvedtoken", 5, "bm25")["church"]["present"])


class _Served(Exception):
    pass


class ServerMainTests(unittest.TestCase):
    """``app/server.py`` end to end, up to ``make_server``."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.index_dir = Path(tmp.name) / "index"
        self.index_dir.mkdir()
        self.wesley = self.index_dir / "wesley.sqlite"
        build_library(self.wesley, *classic_rows())
        self.church = self.index_dir / "mychurch.sqlite"
        build_church(self.church)
        self.apps: list[App] = []

        def no_server(app, *_a, **_k):
            self.apps.append(app)
            raise _Served

        for target in (
            patch("preached.paths.INDEX_DIR", self.index_dir),
            patch("preached.paths.INDEX_PATH", self.wesley),
            patch.object(server, "INDEX_DIR", self.index_dir),
            patch.object(server, "INDEX_PATH", self.wesley),
            patch.object(server, "bundle_problem", lambda _index: None),
            patch.object(server, "make_server", no_server),
            patch.dict(os.environ, {"PREACHED_PRIVACY": str(PRIVACY), **CHURCH_ON}),
        ):
            target.start()
            self.addCleanup(target.stop)

    def run_main(self, *extra: str) -> App:
        with self.assertRaises(_Served):
            server.main(["--bm25-only", "--port", "0", *extra])
        return self.apps[-1]

    def test_church_library_is_served_through_the_gate(self) -> None:
        before = sha(self.church)
        with self.assertLogs(level="INFO"):
            app = self.run_main("--church-library", "mychurch")
        self.addCleanup(app.church_connection.close)
        self.assertIs(app.church_searcher.gated, True)
        self.assertIsNone(app.church_searcher.library)
        side = app.side("sharedpulpit", 5, "bm25")
        self.assertEqual([hit["chunk_id"] for hit in side["church"]["results"]], ["c-shared"])
        self.assertEqual(side["church"]["library"], "mychurch")
        self.assertEqual(leaks(side), [])
        self.assertIsNone(app.health()["church"])
        self.assertEqual(sha(self.church), before)

    def test_church_index_is_served_through_the_gate(self) -> None:
        with self.assertLogs(level="INFO"):
            app = self.run_main("--church-index", str(self.church))
        self.addCleanup(app.church_connection.close)
        self.assertEqual(app.church_library, "mychurch")
        self.assertTrue(app.side("approvedtoken", 5, "bm25")["church"]["results"])

    def test_without_privacy_config_the_church_side_is_empty_and_wesley_serves(self) -> None:
        os.environ.pop("PREACHED_PRIVACY", None)
        with self.assertLogs(level="ERROR") as logs:
            app = self.run_main("--church-library", "mychurch")
        self.assertIn("church side refused", "\n".join(logs.output))
        self.assertIsNone(app.church_searcher)
        plain = self.run_main()
        self.assertEqual(_without_took(app.side("classiconlytoken", 5, "bm25")),
                         _without_took(plain.side("classiconlytoken", 5, "bm25")))
        self.assertEqual(app.health(), plain.health())

    def test_unsafe_church_sidecar_does_not_stop_wesley(self) -> None:
        sidecar = Path(f"{self.church}-shm")
        os.link(self.wesley, sidecar)
        self.addCleanup(sidecar.unlink, missing_ok=True)
        wesley_before = sha(self.wesley)
        with self.assertLogs(level="ERROR"):
            app = self.run_main("--church-library", "mychurch")
        self.assertIsNone(app.church_searcher)
        self.assertTrue(app.side("classiconlytoken", 5, "bm25")["classic"]["results"])
        self.assertEqual(sha(self.wesley), wesley_before)

    # PR #37 r1 should-fix 4: the church side is off unless the deploy config turns it on.

    def test_without_the_deploy_switch_the_church_is_not_opened_and_wesley_serves(self) -> None:
        before = sha(self.church)
        plain = self.run_main()
        for value in (None, "", "1", "true", "Enabled", "enabled "):
            with self.subTest(value=value), patch.dict(os.environ):
                if value is None:
                    os.environ.pop("PREACHED_CHURCH_SIDE", None)
                else:
                    os.environ["PREACHED_CHURCH_SIDE"] = value
                for flag, arg in (("--church-library", "mychurch"), ("--church-index", str(self.church))):
                    with patch.object(server, "open_church_readonly", side_effect=AssertionError("opened")):
                        with self.assertLogs(level="ERROR") as logs:
                            app = self.run_main(flag, arg)
                    self.assertIn("church side refused: PREACHED_CHURCH_SIDE is not 'enabled'", "\n".join(logs.output))
                    self.assertIsNone(app.church_searcher)
                    self.assertEqual(app.library_names(), ["wesley"])
                    self.assertEqual(_without_took(app.side("approvedtoken", 5, "bm25")),
                                     _without_took(plain.side("approvedtoken", 5, "bm25")))
        for suffix in ("-wal", "-shm", "-journal"):
            self.assertFalse(Path(f"{self.church}{suffix}").exists(), suffix)
        self.assertEqual(sha(self.church), before)

    def test_the_deploy_switch_is_not_passed_by_serve_sh(self) -> None:
        serve = (Path(__file__).resolve().parents[1] / "scripts" / "serve.sh").read_text()
        self.assertNotIn("PREACHED_CHURCH_SIDE", serve)
        self.assertNotIn("--church", serve)

    def test_classic_named_as_the_church_still_exits(self) -> None:
        for slug in ("wesley", "spurgeon", "edwards"):
            with self.assertRaises(SystemExit) as caught:
                server.main(["--bm25-only", "--port", "0", "--church-library", slug])
            self.assertIn("classic", str(caught.exception))

    def test_no_church_named_logs_nothing_about_a_church(self) -> None:
        with self.assertLogs(level="INFO") as logs:
            app = self.run_main()
        self.assertNotIn("church", "\n".join(logs.output))
        self.assertIsNone(app.church_searcher)


class CliSideTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.classic = root / "wesley.sqlite"
        self.church = root / "sample.sqlite"
        build_library(self.classic, *classic_rows())
        build_church(self.church)
        self.module = _load_query()
        privacy = patch.dict(os.environ, {"PREACHED_PRIVACY": str(PRIVACY)})
        privacy.start()
        self.addCleanup(privacy.stop)

    def run_cli(self, query: str, *extra: str) -> tuple[str, str]:
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.module.main([query, "--mode", "bm25", "-k", "25", "--side", "--index", str(self.classic), *extra])
        return out.getvalue(), err.getvalue()

    def test_approved_church_passages_print_and_hidden_ones_never_do(self) -> None:
        text, err = self.run_cli("sharedpulpit", "--church-index", str(self.church))
        self.assertEqual(err, "")
        church = _section(text, "Your church (sample data)")
        self.assertIn("sharedpulpit hope", church)
        self.assertIn("confidence: unrated", church)
        self.assertIn(_watch("churchvid02"), church)
        for query in QUERIES:
            text, _err = self.run_cli(query, "--church-index", str(self.church))
            body = text.split("\n", 1)[1]  # drop the echoed query line
            for token in [*HIDDEN, *HIDDEN_TITLES]:
                self.assertNotIn(token, body, query)

    def test_flagged_passage_prints_without_audio(self) -> None:
        text, _ = self.run_cli("flaggedtoken", "--church-index", str(self.church))
        church = _section(text, "Your church (sample data)")
        self.assertIn("audio withheld", church)
        self.assertNotIn("churchvid03", church)

    def test_the_chunk_right_after_a_flagged_name_prints_without_audio(self) -> None:
        text, _ = self.run_cli("adjacenttoken", "--church-index", str(self.church))
        church = _section(text, "Your church (sample data)")
        self.assertIn("adjacenttoken", church)
        self.assertIn("audio withheld", church)
        self.assertNotIn("churchvid03", church)

    def test_refused_church_prints_one_line_and_the_empty_section(self) -> None:
        none_text, none_err = self.run_cli("classiconlytoken")
        os.environ.pop("PREACHED_PRIVACY", None)
        text, err = self.run_cli("classiconlytoken", "--church-index", str(self.church))
        self.assertIn("church side refused", err)
        self.assertEqual(text, none_text)
        self.assertIn(CHURCH_EMPTY, _section(text, "Your church"))
        self.assertEqual(none_err, "")

    def test_gate_off_mutation_makes_the_cli_leak(self) -> None:
        with patch.object(search_module, "visible_sql", lambda *_a, **_k: None):
            text, _ = self.run_cli("unapprovedtoken", "--church-index", str(self.church))
        self.assertIn("unapprovedtoken sharedpulpit", text.split("\n", 1)[1])


if __name__ == "__main__":
    logging.basicConfig(level=logging.CRITICAL)
    unittest.main()
