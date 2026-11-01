"""#12 must-fix 4 (PR #10 is on main): hidden rows stay hidden across every #10 reload.

#10's App rebuilds its Searcher when the index stamp changes
(``_reload_cached_index``), drops to BM25 when vectors go away or the stamp
cannot be read (``_serve_keyword_only``). Each rebuilt Searcher must keep the
gate and the slug; visibility is still decided per request in SQL and the
Searcher still follows ``PRAGMA data_version``. Every name below is invented.
"""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import sqlite3
from unittest.mock import patch

import numpy as np

from app.server import STATIC_DIR, App
from preached.search import Searcher
from preached.store import connect
from preached.youtube.library import MODEL_KEY
from test_privacy_wire import ID_A, ID_B, Base, embedder

# Only in sermon B (unapproved) and only in sermon A (approved).
ONLY_B = "children"
ONLY_A = "soup"


class HiddenAfterReloadTests(Base):
    def setUp(self) -> None:
        super().setUp()
        self.assertEqual(self.importer()[0], 0)
        self.assertEqual(self.cli(["--library", "wire", "--ack-review", ID_A])[0], 0)  # B stays unapproved
        self.connection = connect(self.index)
        self.connection.row_factory = sqlite3.Row
        self.addCleanup(self.connection.close)

        def encode(query: str) -> np.ndarray:
            return embedder([""], [query])[0]

        encode.backend = "onnx"
        self.app = App(connection=self.connection, searcher=Searcher(self.connection, model=MODEL_KEY), encode=encode,
                       fallback_note=None, model_name=MODEL_KEY, hosts={"127.0.0.1"}, static_dir=STATIC_DIR,
                       backend="onnx", library="wire")

    def sermons(self, query: str) -> set[str]:
        found = set()
        for mode in ("bm25", "dense", "hybrid"):
            found |= {r["sermon_id"] for r in self.app.search(query, 50, mode)["results"]}
        return found

    def visible_rows(self) -> int:
        return self.connection.execute("SELECT count(*) FROM chunks WHERE video_id = ?", (ID_A,)).fetchone()[0]

    def assert_b_hidden(self, label: str) -> None:
        with self.subTest(after=label):
            self.assertTrue(self.app.searcher.gated)
            self.assertEqual(self.app.searcher.library, "wire")
            self.assertNotIn(ID_B, self.sermons(ONLY_B))
            self.assertNotIn(ID_B, self.sermons("God faithful mercy"))
            self.assertIn(ID_A, self.sermons(ONLY_A))
            self.assertIsNone(self.app.sermon(ID_B))
            health = self.app.health()
            self.assertEqual(health["chunks"], self.visible_rows())
            self.assertEqual(health["pending_review"], 1)

    def bump_stamp(self, value: str) -> None:
        self.connection.execute(
            "INSERT INTO meta (key, value) VALUES ('chunks_sha256', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (value,))
        self.connection.commit()

    def test_hidden_rows_stay_hidden_after_every_reload(self) -> None:
        self.assert_b_hidden("start")
        first = self.app.searcher

        self.bump_stamp("reload-1")  # _reload_cached_index: a new dense Searcher
        self.app.search("x", 1, "bm25")
        self.assertIsNot(self.app.searcher, first)
        self.assertEqual(self.app.searcher.model, MODEL_KEY)
        self.assert_b_hidden("stamp reload (dense)")

        with patch("app.server.index_stamp", side_effect=sqlite3.OperationalError("locked")):
            self.app.search("x", 1, "bm25")  # _serve_keyword_only(INDEX_READ_NOTE)
            self.assertIsNone(self.app.encode)
            self.assertTrue(self.app.searcher.gated)
            self.assertEqual(self.app.searcher.library, "wire")
            self.assertNotIn(ID_B, {r["sermon_id"] for r in self.app.search(ONLY_B, 50, "bm25")["results"]})
        self.app.search("x", 1, "bm25")  # read works again: reloaded
        self.assert_b_hidden("status-read failure and recovery")

        self.connection.execute("DELETE FROM embeddings")
        self.connection.execute("DELETE FROM meta WHERE key LIKE 'embeddings:%'")
        self.connection.commit()
        self.app.search("x", 1, "dense")  # _serve_keyword_only(STALE_NOTE)
        self.assertIsNone(self.app.encode)
        self.assert_b_hidden("vectors removed (BM25 fallback)")

    def test_approval_after_a_reload_applies_on_the_next_request(self) -> None:
        """The gate is still per request: an approval made after a reload is served without another reload."""
        self.bump_stamp("reload-1")
        self.app.search("x", 1, "bm25")
        self.assert_b_hidden("reload")
        searcher = self.app.searcher
        self.assertEqual(self.cli(["--library", "wire", "--ack-review", ID_B])[0], 0)
        self.assertIn(ID_B, {r["sermon_id"] for r in self.app.search(ONLY_B, 50, "bm25")["results"]})
        self.assertIs(self.app.searcher, searcher)  # no stamp change, no reload: the SQL gate did it
        self.assertIsNotNone(self.app.sermon(ID_B))
        self.assertNotIn("pending_review", {k for k, v in self.app.health().items() if v})
