"""W3-OBS-GAPS: the reload fallbacks and the clean stop are logged, once, with the strings the alerts match."""

from __future__ import annotations

import logging
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app.server as server  # noqa: E402
from app.server import STATIC_DIR, STALE_NOTE, INDEX_READ_NOTE, App, Searcher  # noqa: E402
from preached.models import MODELS  # noqa: E402
from preached.store import connect, save_embedding_info, write_embeddings  # noqa: E402
from test_server import _insert  # noqa: E402

import numpy as np  # noqa: E402

MISMATCH = "ERROR:root:stored vectors do not match search/models.toml; serving BM25 only"
UNAVAILABLE = "ERROR:root:embedding model unavailable; serving BM25 only"
STATUS_UNREADABLE = "ERROR:root:index status unreadable after reload; serving BM25 only"


class ReloadFallbackLogTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        spec = MODELS["granite-english-r2"]
        self.connection = connect(Path(tmp.name) / "index.sqlite")
        self.addCleanup(self.connection.close)
        _insert(self.connection, chunk_id="c1", text="By grace are ye saved through faith.", start_s=10, end_s=20)
        self.connection.commit()
        rowid = int(self.connection.execute("SELECT rowid FROM chunks").fetchone()[0])
        write_embeddings(self.connection, spec.key, [rowid], np.ones((1, 4), dtype=np.float32))
        save_embedding_info(self.connection, spec.key, {"fingerprint": spec.fingerprint(), "backend": "onnx", "variant": "fp32"})
        self.connection.execute("INSERT INTO meta (key, value) VALUES ('chunks_sha256', 'aaa')")
        self.connection.commit()

        def encode(_query: str) -> np.ndarray:
            return np.ones(4, dtype=np.float32)

        encode.backend = "onnx"
        encode.variant = "fp32"
        self.app = App(
            connection=self.connection, searcher=Searcher(self.connection, model=spec.key), encode=encode,
            fallback_note=None, model_name=spec.key, hosts={"127.0.0.1"}, static_dir=STATIC_DIR, backend="onnx",
        )
        self.assertEqual(self.app.search("grace", 5, "dense")["mode"], "dense")

    def requests(self, n: int = 3) -> list[str]:
        with self.assertLogs(level="INFO") as logs:
            for _ in range(n):
                self.app.search("grace", 5, "dense")
            logging.info("marker")  # assertLogs fails on no output; the mismatch case may log nothing else
        return [line for line in logs.output if line != "INFO:root:marker"]

    def test_stored_vectors_that_no_longer_match_log_one_error_line(self) -> None:
        self.connection.execute("DELETE FROM embeddings")
        self.connection.execute("DELETE FROM meta WHERE key LIKE 'embeddings:%'")
        self.connection.commit()
        lines = self.requests()
        self.assertEqual(lines, [MISMATCH])
        self.assertEqual(self.app.fallback_note, STALE_NOTE)

    def test_an_unreadable_index_status_logs_one_error_line_per_transition(self) -> None:
        with patch("app.server.index_stamp", side_effect=sqlite3.OperationalError("disk I/O error")):
            lines = self.requests()
        self.assertEqual(lines.count(STATUS_UNREADABLE), 1)  # three requests, one transition
        self.assertNotIn(UNAVAILABLE, lines)  # the model is fine; do not say it is not
        self.assertEqual(self.app.fallback_note, INDEX_READ_NOTE)
        # Recovery clears it; a second failure is a new transition and logs again.
        self.connection.execute("UPDATE meta SET value = 'bbb' WHERE key = 'chunks_sha256'")
        self.connection.commit()
        self.app.search("grace", 5, "dense")
        self.assertIsNone(self.app.fallback_note)
        with patch("app.server.index_stamp", side_effect=sqlite3.OperationalError("disk I/O error")):
            again = self.requests(2)
        self.assertEqual(again.count(STATUS_UNREADABLE), 1)

    def test_the_stamp_traceback_is_logged_once_per_outage(self) -> None:
        stamp_lines = lambda: [l for l in self.requests() if "could not read the index stamp" in l]  # noqa: E731
        with patch("app.server.index_stamp", side_effect=sqlite3.OperationalError("disk I/O error")):
            self.assertEqual(len(stamp_lines()), 1)  # three requests, one ERROR
            self.assertEqual(stamp_lines(), [])  # still down: DEBUG only
        self.connection.execute("UPDATE meta SET value = 'bbb' WHERE key = 'chunks_sha256'")
        self.connection.commit()
        self.app.search("grace", 5, "dense")  # recovers
        with patch("app.server.index_stamp", side_effect=sqlite3.OperationalError("disk I/O error")):
            self.assertEqual(len(stamp_lines()), 1)  # a new outage logs again


class Bm25OnlyStatusReadTests(unittest.TestCase):
    """A server with no weights is BM25 by design: a status-read failure pages nobody."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.connection = connect(Path(tmp.name) / "index.sqlite")
        self.addCleanup(self.connection.close)
        _insert(self.connection, chunk_id="c1", text="By grace are ye saved through faith.", start_s=10, end_s=20)
        self.connection.execute("INSERT INTO meta (key, value) VALUES ('chunks_sha256', 'aaa')")
        self.connection.commit()
        self.app = App(
            connection=self.connection, searcher=Searcher(self.connection), encode=None, fallback_note=None,
            model_name=None, hosts={"127.0.0.1"}, static_dir=STATIC_DIR,
        )

    def test_a_status_read_failure_logs_no_d1_or_d2_line_and_healthz_recovers(self) -> None:
        with self.assertLogs(level="DEBUG") as logs:
            with patch("app.server.index_stamp", side_effect=sqlite3.OperationalError("disk I/O error")):
                for _ in range(3):
                    self.app.search("grace", 5, "bm25")
            logging.info("marker")
        errors = [l for l in logs.output if l.startswith(("ERROR", "WARNING"))]
        self.assertEqual(len(errors), 1)  # only the stamp traceback (S2), never a D1/D2 string
        self.assertNotIn(UNAVAILABLE, logs.output)
        self.assertNotIn(STATUS_UNREADABLE, logs.output)
        self.assertNotIn(MISMATCH, logs.output)
        self.assertEqual(self.app.fallback_note, INDEX_READ_NOTE)
        # Recovery: the startup note (None for --bm25-only) comes back.
        self.connection.execute("UPDATE meta SET value = 'bbb' WHERE key = 'chunks_sha256'")
        self.connection.commit()
        self.app.search("grace", 5, "bm25")
        self.assertIsNone(self.app.fallback_note)


class StoppedCleanlyTests(unittest.TestCase):
    def run_stop(self, stuck: list) -> list[str]:
        class Conn:
            def close(self) -> None:
                pass

        class Srv:
            refusals = None

            def drain(self):
                return stuck

            def server_close(self) -> None:
                pass

        app = type("A", (), {})()
        app.church_connection = Conn()
        app.close_embedder = lambda: None
        server._STOP["requested"] = True
        self.addCleanup(server._STOP.update, {"requested": False, "stopping": False, "server": None})
        with self.assertLogs(level="INFO") as logs:
            try:
                server.serve_until_stopped(Srv(), app, Conn())
            except SystemExit:
                pass
        return logs.output

    def test_the_clean_stop_ends_with_stopped_cleanly(self) -> None:
        lines = self.run_stop([])
        self.assertEqual(lines, ["INFO:root:stopping", "INFO:root:stopped cleanly"])

    def test_the_stuck_stop_does_not_say_it(self) -> None:
        lines = self.run_stop([object()])
        self.assertNotIn("INFO:root:stopped cleanly", lines)
        self.assertTrue(lines[-1].startswith("ERROR:root:1 handler thread(s) still running"))


if __name__ == "__main__":
    unittest.main()
