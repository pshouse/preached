"""The alert lines docs/DEPLOY.md tells Infra Ops to match, pinned verbatim
(56-W3-DEPLOY-CONSOLIDATE). A change to one of these strings must change the
runbook's alert table and the Infra Ops rules with it.

Every church file here is a synthetic fixture. No real church data is used.
"""

from __future__ import annotations

import re
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
WRITER_LOCK_AT_START = "the church file is locked by a writer (database is locked)"
SEARCH_FAILED = "church search failed; that side is empty"
SEARCHER_NOT_BUILT = "church side refused: its searcher could not be built (RuntimeError: boom)"
# Prefixes and fixed lines the runbook's alert table names.
DOCUMENTED = (
    "ERROR church side refused: the church file could not be opened (<exc>)",
    "ERROR church side refused:",
    "ERROR church side dropped:",
    "INFO church side paused:",
    "INFO church side resumed",
    "INFO church side pause ended: refused",
    "ERROR church search failed; that side is empty",
    "ERROR church side refused: its searcher could not be built (<Type>: <why>)",
    "tar failed (tar 1, gzip 0)",
    "ERROR church vectors do not match search/models.toml; that side is BM25 only",
    "ERROR church vectors unavailable; that side is BM25 only",
    "ERROR stored vectors do not match search/models.toml; serving BM25 only",
    "ERROR embedding model unavailable; serving BM25 only",
    "ERROR refusing to serve after reload:",
    "ERROR refusing to serve:",
    "ERROR <n> handler thread(s) still running after 10s; index left open",
    "ERROR request failed:",
    "ERROR abstain calibration unusable; abstain floor disabled",
    "ERROR index status unreadable after reload; serving BM25 only",
    "INFO stopped cleanly",
    "INFO listening on http://",
    "church-paused-stuck",
    "church-paused-unverified",
    "%(levelname)s %(message)s",
)

# (file, cite, text). Every `file:line` docs/DEPLOY.md cites, with the text
# that line holds; a range `a-b` gives the text of its first and last line.
# A bare `:n` in the runbook is read against the file named before it in the
# same table row, bullet or paragraph.
REFUSED = 'logging.error("church side refused: %s", '
LOCKED = 'raise ChurchPaused(f"the church file is locked by a writer ({exc})") from exc'
CITED = (
    ("app/server.py", "237", "REQUEST_TIMEOUT_S = 15"),
    ("app/server.py", "243", "DRAIN_TIMEOUT_S = 10.0"),
    ("app/server.py", "284-285", ("CHURCH_RETRY_FIRST_S = 1.0", "CHURCH_RETRY_MAX_S = 30.0")),
    ("app/server.py", "295", 'MISMATCH_LOG = "stored vectors do not match search/models.toml; serving BM25 only"'),
    ("app/server.py", "296", 'UNAVAILABLE_LOG = "embedding model unavailable; serving BM25 only"'),
    ("app/server.py", "297", 'INDEX_STATUS_LOG = "index status unreadable after reload; serving BM25 only"'),
    ("app/server.py", "493", 'logging.warning("refused %s %s suppressed=%d", kind, detail, suppressed)'),
    ("app/server.py", "505", 'logging.warning("refused %s flush suppressed=%d", kind, suppressed)'),
    ("app/server.py", "850", "logging.exception(MISMATCH_LOG)"),
    ("app/server.py", "853", "logging.exception(UNAVAILABLE_LOG)"),
    ("app/server.py", "877", '"church vectors do not match search/models.toml; that side is BM25 only"'),
    ("app/server.py", "882", 'logging.exception("church vectors unavailable; that side is BM25 only")'),
    ("app/server.py", "900", LOCKED),
    ("app/server.py", "903", '"church side refused: its searcher could not be built (%s: %s)"'),
    ("app/server.py", "1102", 'logging.log(level, "could not read the index stamp", exc_info=True)'),
    ("app/server.py", "1133", "refusing to serve after reload:"),
    ("app/server.py", "1150", 'logging.error("%s", message)'),
    ("app/server.py", "1182", "self._serve_keyword_only(STALE_NOTE, MISMATCH_LOG)"),
    ("app/server.py", "1216", "refusing to serve:"),
    ("app/server.py", "1225", "self._serve_keyword_only(INDEX_READ_NOTE, INDEX_STATUS_LOG if self._weights_ok else None)"),
    ("app/server.py", "1421", 'logging.error("church side refused: %s", problem)'),
    ("app/server.py", "1426", 'logging.error("church side refused: the publish gate did not turn on")'),
    ("app/server.py", "1459", '"church side refused: the church file could not be opened (%s)", exc)'),
    ("app/server.py", "1466", 'logging.info("church side pause ended: refused")'),
    ("app/server.py", "1467", "self._church_paused = False"),
    ("app/server.py", "1498", 'logging.error("church side dropped: %s", problem)'),
    ("app/server.py", "1509", 'logging.info("church side paused: %s", reason)'),
    ("app/server.py", "1517", 'logging.info("%s", held)'),
    ("app/server.py", "1576", 'logging.info("church side resumed")'),
    ("app/server.py", "1579", 'logging.exception("church search failed; that side is empty")'),
    ("app/server.py", "1584", 'self._church_pause(f"the church file is locked by a writer ({exc})")'),
    ("app/server.py", "1785", 'logging.exception("abstain calibration unusable; abstain floor disabled")'),
    ("app/server.py", "1791", "def start():"),
    *(("app/server.py", str(n), 'logging.error("request failed: %s", ') for n in (2008, 2013, 2058, 2060, 2120, 2360, 2381)),
    ("app/server.py", "2814", 'logging.info("listening on http://%s:%s", host, port)'),
    ("app/server.py", "2818", "app.log_startup_pause()"),
    ("app/server.py", "2886", REFUSED + "problem)"),
    ("app/server.py", "2893", REFUSED + "exc)"),
    ("app/server.py", "2904", REFUSED + "problem)"),
    ("app/server.py", "2911", 'logging.info("church side: %s, read-only, through the publish gate", slug)'),
    ("app/server.py", "3073", 'logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")'),
    ("app/server.py", "3251", 'logging.info("stopping")'),
    ("app/server.py", "3252-3270", ("stuck = server.drain()", "raise SystemExit(1)")),
    ("app/server.py", "3256", '"%d handler thread(s) still running after %.0fs; index left open"'),
    ("app/server.py", "3266", "app.church_connection.close()"),
    ("app/server.py", "3268", 'logging.info("stopped cleanly")'),
    ("scripts/build-bundle.sh", "239", 'echo "tar exited 1 (file changed as we read it?); attempt ${attempt} of 3" >&2'),
    ("scripts/build-bundle.sh", "243", 'echo "tar failed (tar ${TAR_STATUS}, gzip ${GZIP_STATUS}); no archive written" >&2'),
    ("scripts/build-bundle.sh", "247", 'echo "tar.gz does not match MANIFEST.sha256; no archive written" >&2'),
    ("src/preached/library.py", "468", LOCKED),
    (
        "src/preached/library.py",
        "883-884",
        ('f"{path.name} is in WAL journal mode; run --ack-review', 'f"{path.name} is in WAL journal mode",'),
    ),
    (
        "src/preached/library.py",
        "895-896",
        (
            'reason = f"the church file is locked by a writer ({exc})"',
            'raise ChurchStartPaused(f"{reason}; it is not opened", reason) from exc',
        ),
    ),
    ("src/preached/library.py", "915", 'problem, paused = f"{exc}; it is not opened", str(exc)'),
    (
        "src/preached/library.py",
        "921-922",
        ('paused = f"the church file is locked by a writer ({exc})"', 'problem = f"{paused}; it is not opened"'),
    ),
    ("src/preached/library.py", "962", 'raise ChurchPaused(f"{path.name} is in WAL journal mode")'),
    ("src/preached/youtube/library.py", "157", 'f"the church file is still in {mode} journal mode'),
    ("src/preached/youtube/pipeline.py", "333", 'print(f"warning: {exc}", file=sys.stderr)'),
)
CITE = re.compile(r"`((?:[\w./-]+\.(?:py|sh))?):(\d+(?:-\d+)?)`")


def _close_app(app) -> None:
    """Close the sqlite connections church_app / build_app left open."""
    app.connection.close()
    if app.church_connection is not None:
        app.church_connection.close()
    for searcher in (app.searcher, app.church_searcher):
        cache = getattr(searcher, "_visible_cache", None)
        if cache is not None:
            cache.fts.close()


def runbook_cites(text: str) -> set[tuple[str | None, str]]:
    """(file, cite) for every `file:n` and bare `:n` in the runbook.

    Each table row, list item and paragraph is read on its own: a bare `:n`
    belongs to the last file named before it there, or to None.
    """
    cites = set()
    for paragraph in text.split("\n\n"):
        for block in re.split(r"\n(?=\s*(?:- |\d+\. |\|))", paragraph):
            name = None
            for match in CITE.finditer(block):
                name = match.group(1) or name
                cites.add((name, match.group(2)))
    return cites


class AlertLineTests(_Root):
    def test_a_writer_lock_at_startup_is_a_pause_not_a_refusal(self) -> None:
        church = self.root / "sample.sqlite"
        build_church(church)
        writer = sqlite3.connect(church, isolation_level=None)
        writer.execute("BEGIN EXCLUSIVE")
        try:
            with self.assertNoLogs(level="ERROR"):
                with self.assertRaises(server.ChurchPaused) as caught:
                    server.open_church(church, slug=None, classic_library="wesley", classic_index=self.wesley)
        finally:
            writer.execute("ROLLBACK")
            writer.close()
        self.assertEqual(str(caught.exception), WRITER_LOCK_AT_START)

    def test_a_failed_church_search_logs_the_ticket_line_with_a_traceback(self) -> None:
        church = self.root / "sample.sqlite"
        build_church(church)
        app = church_app(self.wesley, church)
        self.addCleanup(_close_app, app)
        with patch.object(server, "compute_signals", side_effect=RuntimeError("boom")):
            with self.assertLogs(level="ERROR") as logs:
                self.assertIsNone(app.church_search("approvedtoken", 5, "bm25"))
        self.assertEqual(len(logs.output), 1, logs.output)
        first, _, rest = logs.output[0].partition("\n")
        self.assertEqual(first, f"ERROR:root:{SEARCH_FAILED}")
        self.assertTrue(rest.startswith("Traceback"), rest)

    def test_a_searcher_that_cannot_be_built_is_refused_in_one_line(self) -> None:
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
        self.addCleanup(_close_app, app)
        self.assertIsNone(app.church_searcher)
        self.assertEqual(len(logs.output), 1, logs.output)
        self.assertEqual(logs.output, [f"ERROR:root:{SEARCHER_NOT_BUILT}"])

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
        for name, cite, needle in CITED:
            with self.subTest(file=name, cite=cite):
                lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
                first, _, last = cite.partition("-")
                needles = (needle,) if isinstance(needle, str) else needle
                for number, text in zip((first, last or first), needles):
                    self.assertIn(text, lines[int(number) - 1])

    def test_the_runbook_cites_exactly_the_pinned_lines(self) -> None:
        cites = runbook_cites(DEPLOY.read_text(encoding="utf-8"))
        pinned = {(name, cite) for name, cite, _ in CITED}
        self.assertEqual(len(pinned), len(CITED), "a cite is pinned twice")
        self.assertEqual(cites - pinned, set(), "cited in docs/DEPLOY.md but not pinned here")
        self.assertEqual(pinned - cites, set(), "pinned here but not cited in its row of docs/DEPLOY.md")


if __name__ == "__main__":
    unittest.main()
