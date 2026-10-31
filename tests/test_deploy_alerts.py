"""The alert lines docs/DEPLOY.md tells Infra Ops to match, pinned verbatim
(56-W3-DEPLOY-CONSOLIDATE). A change to one of these strings must change the
runbook's alert table and the Infra Ops rules with it.

Every church file here is a synthetic fixture. No real church data is used.
"""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app.server as server  # noqa: E402
from app.server import STATIC_DIR, Searcher, build_app  # noqa: E402
from test_church_r2 import _Root  # noqa: E402
from test_church_wire import build_church, church_app  # noqa: E402
from test_side import FIXTURE_FP, encode_fixture, reopen  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "docs" / "DEPLOY.md"

# The server logs "%(levelname)s %(message)s"; assertLogs adds ":root:".
WRITER_LOCK_AT_START = (
    "church side refused: the church file is locked by a writer (database is locked); it is not opened"
)
SEARCH_FAILED = "church search failed; that side is empty"
SEARCHER_NOT_BUILT = "church side refused: its searcher could not be built"
# Prefixes and fixed lines the runbook's alert table names.
DOCUMENTED = (
    "ERROR church side refused: the church file is locked by a writer (database is locked); it is not opened",
    "ERROR church side refused:",
    "ERROR church side dropped:",
    "INFO church side paused:",
    "INFO church side resumed",
    "ERROR church search failed; that side is empty",
    "ERROR church side refused: its searcher could not be built",
    "tar failed (tar 1, gzip 0)",
    "ERROR church vectors do not match search/models.toml; that side is BM25 only",
    "ERROR church vectors unavailable; that side is BM25 only",
    "ERROR stored vectors do not match search/models.toml; serving BM25 only",
    "ERROR embedding model unavailable; serving BM25 only",
    "ERROR refusing to serve after reload:",
    "ERROR refusing to serve:",
    "ERROR <n> handler thread(s) still running after 10s; index left open",
    "ERROR request failed:",
    "INFO listening on http://",
    "church-paused-stuck",
    "church-paused-unverified",
    "%(levelname)s %(message)s",
)

# (file, line, text on that line of the file). The runbook's tables cite each
# as file:line; PR #46 refreshes the numbers and this table with them.
CITED = (
    ("app/server.py", 826, "stored vectors do not match search/models.toml; serving BM25 only"),
    ("app/server.py", 829, "embedding model unavailable; serving BM25 only"),
    ("app/server.py", 853, "church vectors do not match search/models.toml; that side is BM25 only"),
    ("app/server.py", 856, "church vectors unavailable; that side is BM25 only"),
    ("app/server.py", 983, "church side refused: %s"),
    ("app/server.py", 988, "church side refused:"),
    ("app/server.py", 1069, "refusing to serve after reload:"),
    ("app/server.py", 1146, "refusing to serve:"),
    ("app/server.py", 1351, "church side dropped:"),
    ("app/server.py", 1359, "church side paused:"),
    ("app/server.py", 1418, "church side resumed"),
    ("app/server.py", 1421, "church search failed; that side is empty"),
    ("app/server.py", 1633, "church side refused: its searcher could not be built"),
    ("app/server.py", 2600, "listening on http://"),
    ("app/server.py", 2663, "church side refused:"),
    ("app/server.py", 2668, "church side refused:"),
    ("app/server.py", 2679, "church side refused:"),
    ("app/server.py", 3030, "handler thread(s) still running after"),
    *(("app/server.py", n, "request failed:") for n in (1833, 1838, 1883, 1885, 1945, 2185, 2206)),
)


class AlertLineTests(_Root):
    def test_a_writer_lock_at_startup_is_refused_with_the_paged_line(self) -> None:
        church = self.root / "sample.sqlite"
        build_church(church)
        writer = sqlite3.connect(church, isolation_level=None)
        writer.execute("BEGIN EXCLUSIVE")
        try:
            with self.assertLogs(level="ERROR") as logs:
                opened = server.open_church(church, slug=None, classic_library="wesley", classic_index=self.wesley)
        finally:
            writer.execute("ROLLBACK")
            writer.close()
        self.assertIsNone(opened)
        self.assertEqual(logs.output, [f"ERROR:root:{WRITER_LOCK_AT_START}"])

    def test_a_failed_church_search_logs_the_ticket_line_with_a_traceback(self) -> None:
        church = self.root / "sample.sqlite"
        build_church(church)
        app = church_app(self.wesley, church)
        with patch.object(server, "compute_signals", side_effect=RuntimeError("boom")):
            with self.assertLogs(level="ERROR") as logs:
                self.assertIsNone(app.church_search("approvedtoken", 5, "bm25"))
        self.assertEqual(len(logs.output), 1, logs.output)
        first, _, rest = logs.output[0].partition("\n")
        self.assertEqual(first, f"ERROR:root:{SEARCH_FAILED}")
        self.assertTrue(rest.startswith("Traceback"), rest)

    def test_a_searcher_that_cannot_be_built_is_refused_with_a_traceback(self) -> None:
        church = self.root / "sample.sqlite"
        build_church(church)

        def loader(connection, _model):
            return Searcher(connection, model="fixture", fingerprint=FIXTURE_FP), encode_fixture

        with patch.object(server, "load_church_searcher", side_effect=RuntimeError("boom")):
            with self.assertLogs(level="ERROR") as logs:
                app = build_app(
                    reopen(self.wesley),
                    model_key="granite-english-r2",
                    bm25_only=False,
                    hosts={"127.0.0.1"},
                    static_dir=STATIC_DIR,
                    loader=loader,
                    floor=0.5,
                    church_connection=reopen(church),
                    church_library="sample",
                )
        self.assertIsNone(app.church_searcher)
        self.assertEqual(len(logs.output), 1, logs.output)
        first, _, rest = logs.output[0].partition("\n")
        self.assertEqual(first, f"ERROR:root:{SEARCHER_NOT_BUILT}")
        self.assertTrue(rest.startswith("Traceback"), rest)

    def test_the_log_format_is_the_one_the_rules_anchor_on(self) -> None:
        source = Path(server.__file__).read_text(encoding="utf-8")
        self.assertIn('logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")', source)


class RunbookTests(unittest.TestCase):
    def test_the_runbook_quotes_every_alert_line(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")
        for line in DOCUMENTED:
            with self.subTest(line=line):
                self.assertIn(line, text)

    def test_every_cited_file_line_holds_its_string(self) -> None:
        text = DEPLOY.read_text(encoding="utf-8")
        for name, number, needle in CITED:
            with self.subTest(file=name, line=number):
                lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
                self.assertIn(needle, lines[number - 1])
                self.assertRegex(text, rf"`{name}:{number}`|`:{number}`")


if __name__ == "__main__":
    unittest.main()
