"""N1: chunks the publish gate hides must not change anything a search returns.

Two church files, identical except that one also holds an unapproved sermon
(coverage NULL, no approval) whose words and vector match the probes. Every
field of /api/search but ``took_ms`` must come out the same from both.
"""

from __future__ import annotations

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


def build(path: Path, *, hidden: bool) -> None:
    connection = connect(path)
    ensure_library(connection)
    rows = [(church_row("visible001", "grace upon grace for the weary heart"), [1, 0, 0, 0], "approved")]
    rows.append((church_row("visible002", "grace and mercy in the morning"), [0.9, 0.1, 0, 0], "approved"))
    if hidden:
        # Unapproved, coverage never checked: visible_sql hides it.
        rows.append((church_row("hidden0001", "righteousness grace righteousness of God"), [0, 1, 0, 0], "pending"))
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

    def test_bm25_score_is_a_rank_in_a_gated_file(self) -> None:
        # SQLite's bm25() counts every indexed row; "grace" occurs in the hidden
        # sermon too, so its raw value would differ between the two files.
        scores = [r["score"] for r in self.apps[True].search("grace", 10, "bm25")["results"]]
        self.assertEqual(scores, [1.0, 0.5])

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
