"""N1: chunks the publish gate hides must not change anything a search returns.

Two church files, identical except that one also holds an unapproved sermon
(coverage NULL, no approval) whose words and vector match the probes. Every
field of /api/search but ``took_ms`` must come out the same from both.
"""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.server import STATIC_DIR, App, Searcher  # noqa: E402
from preached.abstain import compute_signals  # noqa: E402
from preached.search import api_search  # noqa: E402
from preached.store import connect, open_readonly, save_embedding_info, write_embeddings  # noqa: E402
from preached.youtube.library import ensure_library  # noqa: E402
from test_side import _insert  # noqa: E402

FIXTURE_FP = "fixture-fingerprint"
VECTORS = {
    "righteousness": [0, 1, 0, 0],
    "grace": [1, 0, 0, 0],
    "zzyzxnonsense": [0, 0, 0, 1],
}


def encode(query: str) -> np.ndarray:
    return np.array(VECTORS.get(query, [0, 0, 1, 0]), dtype=np.float32)


def church_row(video_id: str, text: str) -> dict:
    return {
        "chunk_id": f"{video_id}-c0000",
        "sermon_id": video_id,
        "sermon_number": None,
        "sermon_title": "Sunday",
        "text": text,
        "scripture": None,
        "source_url": f"https://www.youtube.com/watch?v={video_id}",
        "start_s": 10.0,
        "end_s": 20.0,
        "audio_url": f"https://www.youtube.com/watch?v={video_id}&t=9s",
        "reader": None,
        "text_source": "asr",
        "librivox_id": None,
        "word_start": 0,
        "word_end": 8,
    }


def build(path: Path, *, hidden: bool, extra: list[tuple[dict, list[float], str]] = ()) -> None:
    connection = connect(path)
    ensure_library(connection)
    rows = [(church_row("visible001", "grace upon grace for the weary heart"), [1, 0, 0, 0], "approved")]
    rows.append((church_row("visible002", "grace and mercy in the morning"), [0.9, 0.1, 0, 0], "approved"))
    if hidden:
        # Unapproved, coverage never checked: visible_sql hides it.
        rows.append((church_row("hidden0001", "righteousness grace righteousness of God"), [0, 1, 0, 0], "pending"))
    rows.extend(row for row in extra if hidden or row[2] == "approved")
    for row, _, state in rows:
        _insert(connection, **row)
        connection.execute("UPDATE chunks SET video_id = ? WHERE chunk_id = ?", (row["sermon_id"], row["chunk_id"]))
        approved = state == "approved"
        connection.execute(
            "INSERT INTO videos (video_id, title, status, review_sha256, approved_sha256, coverage_gaps) "
            "VALUES (?, 'Sunday', 'ok', 'sha', ?, ?)",
            (row["sermon_id"], "sha" if approved else None, "[]" if approved else None),
        )
    connection.commit()
    rowids = [int(r[0]) for r in connection.execute("SELECT rowid FROM chunks ORDER BY rowid")]
    write_embeddings(connection, "fixture", rowids, np.array([v for _, v, _ in rows], dtype=np.float32))
    save_embedding_info(connection, "fixture", {"fingerprint": FIXTURE_FP})
    connection.commit()
    connection.close()


# BM25 order: visible A says "lantern" three times, visible B "harbor" twice.
# With equal term statistics A ranks first. Eight hidden sermons that say
# "lantern" make it a common word, and B would rank first if they counted.
ORDER_ROWS = [
    (church_row("ordera0001", "lantern lantern lantern stood by the old stone wall tonight"), [0, 0, 1, 0], "approved"),
    (church_row("orderb0001", "harbor harbor near the old stone wall again tonight here"), [0, 0, 1, 0], "approved"),
    *((church_row(f"orderh{i:04d}", "lantern on the hill"), [0, 0, 1, 0], "pending") for i in range(8)),
]
ORDER_QUERY = "lantern harbor beacon compass anchor"  # five terms: an OR query


class HiddenChunksTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.apps = {}
        for hidden in (False, True):
            path = Path(tmp.name) / f"church-{hidden}.sqlite"
            build(path, hidden=hidden)
            connection = open_readonly(path, check_same_thread=False)
            self.addCleanup(connection.close)
            self.apps[hidden] = App(
                connection=connection,
                searcher=Searcher(connection, model="fixture", fingerprint=FIXTURE_FP),
                encode=encode,
                fallback_note=None,
                model_name="fixture",
                hosts={"127.0.0.1"},
                static_dir=STATIC_DIR,
                library="church",
                floor=0.5,
            )

    def test_the_hidden_sermon_is_there_and_matches(self) -> None:
        app = self.apps[True]
        raw = app.connection.execute(
            "SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH 'righteousness'"
        ).fetchone()[0]
        self.assertEqual(raw, 1)

    def test_signals_ignore_hidden_chunks(self) -> None:
        for query in VECTORS:
            for hidden in (False, True):
                app = self.apps[hidden]
                hits = api_search(app.searcher, query, encode(query), "hybrid", 10)
                with self.subTest(query=query, hidden=hidden):
                    signals = compute_signals(app.searcher, query, encode(query), hits)
                    clean = compute_signals(self.apps[False].searcher, query, encode(query), hits)
                    self.assertEqual(signals, clean)
        signals = compute_signals(self.apps[True].searcher, "righteousness", encode("righteousness"), [])
        self.assertEqual(signals.bm25_hits, 0)
        self.assertLess(signals.dense_top, 0.5)  # the hidden chunk's cosine is 1.0

    def test_search_response_is_identical(self) -> None:
        for query in VECTORS:
            for mode in ("bm25", "dense", "hybrid"):
                with self.subTest(query=query, mode=mode):
                    without, with_hidden = (self.apps[h].search(query, 10, mode) for h in (False, True))
                    without.pop("took_ms")
                    with_hidden.pop("took_ms")
                    self.assertEqual(with_hidden, without)

    def test_hidden_rows_do_not_move_the_bm25_order(self) -> None:
        # SQLite's bm25() takes term statistics from every indexed row; the
        # gated searcher scores over the visible rows only.
        with tempfile.TemporaryDirectory() as tmp:
            orders = {}
            for hidden in (False, True):
                path = Path(tmp) / f"order-{hidden}.sqlite"
                build(path, hidden=hidden, extra=ORDER_ROWS)
                connection = open_readonly(path)
                try:
                    searcher = Searcher(connection, model="fixture", fingerprint=FIXTURE_FP)
                    hits = searcher.bm25(ORDER_QUERY, 10)
                    orders[hidden] = [(hit.sermon_id, hit.score) for hit in hits]
                    # The raw FTS index would put B first: the leak this guards against.
                    raw = connection.execute(
                        "SELECT c.sermon_id FROM chunks_fts JOIN chunks c ON c.rowid = chunks_fts.rowid "
                        "WHERE chunks_fts MATCH 'lantern OR harbor' AND c.sermon_id GLOB 'order[ab]*' "
                        "ORDER BY bm25(chunks_fts)"
                    ).fetchall()
                    if hidden:
                        self.assertEqual([r[0] for r in raw], ["orderb0001", "ordera0001"])
                finally:
                    connection.close()
            self.assertEqual(orders[True], orders[False])
            self.assertEqual([sid for sid, _ in orders[True]], ["ordera0001", "orderb0001"])

    def test_visible_index_follows_an_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "church.sqlite"
            build(path, hidden=True)
            connection = open_readonly(path, check_same_thread=False)
            try:
                searcher = Searcher(connection, gated=True, library="church")
                self.assertEqual(searcher.bm25("righteousness", 10), [])
                writer = sqlite3.connect(path)
                writer.execute("UPDATE videos SET approved_sha256 = 'sha', coverage_gaps = '[]'")
                writer.commit()
                writer.close()
                self.assertEqual([h.sermon_id for h in searcher.bm25("righteousness", 10)], ["hidden0001"])
            finally:
                connection.close()

    def test_healthz_counts_only_visible_chunks(self) -> None:
        without, with_hidden = (self.apps[h].health() for h in (False, True))
        self.assertEqual(with_hidden["chunks"], without["chunks"])
        # By design: a count of sermons awaiting approval, never ids or titles.
        self.assertEqual((without["pending_review"], with_hidden["pending_review"]), (0, 1))
        without.pop("pending_review")
        with_hidden.pop("pending_review")
        self.assertEqual(with_hidden, without)

    def test_sermon_endpoint_does_not_serve_hidden(self) -> None:
        self.assertIsNone(self.apps[True].sermon("hidden0001"))


if __name__ == "__main__":
    unittest.main()
