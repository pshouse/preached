"""#12 CTO round 4 must-fix: back-to-back chunks and the play link's seek.

The flagged chunk and the next one share no words, so the old word-overlap
check let the next chunk keep a link that seeks inside the redacted name
(CTO: ``&t=379s`` with the name at 378.86-379.22 s). ``search.touches_flagged``
now also asks whether any flagged chunk of the sermon ends after this
passage's seek minus 0.5 s and starts before its end. Checked on the real
HTTP server for a YouTube import and an ASR (archive.org audio) import.
Every name below is invented.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for sub in ("search", "align"):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

import asr_chunks  # noqa: E402
import query  # noqa: E402
from app.server import STATIC_DIR, App  # noqa: E402
from preached.search import SEEK_SLACK_S, Searcher, seek_time, touches_flagged  # noqa: E402
from preached.store import open_readonly  # noqa: E402
from preached.youtube.cli import main as youtube_main  # noqa: E402
from test_privacy_wire import FILLER, ID_A, Base, embedder, words_for  # noqa: E402
from test_privacy_wire_fix import LiveServer  # noqa: E402

# CTO's numbers: the name spoken at 378.86-379.22 s, the next chunk's first word
# at 379.9 s, so its pre-roll seek is 379.15 s (audio) and t=379 (YouTube).
NAME_START, NAME_END, NEXT_START = 378.86, 379.22, 379.9
MARKER = "zephyrgrace"


def back_to_back(index: Path, sermon_id: str, flag_end_s: float = NAME_END) -> tuple[str, str]:
    """Make a flagged chunk end right where the chunk holding MARKER starts.

    The two share no words (flagged ``word_end`` == next ``word_start``) and the
    flagged words end at ``flag_end_s``. Returns (flagged chunk_id, next chunk_id).
    """
    writer = sqlite3.connect(index)
    writer.row_factory = sqlite3.Row
    try:
        nxt = writer.execute(
            "SELECT * FROM chunks WHERE sermon_id = ? AND flag_end_s IS NULL AND text LIKE ? ORDER BY rowid DESC",
            (sermon_id, f"%{MARKER}%"),
        ).fetchone()
        flagged = writer.execute(
            "SELECT * FROM chunks WHERE sermon_id = ? AND flag_end_s IS NOT NULL ORDER BY rowid", (sermon_id,)
        ).fetchone()
        assert nxt is not None and flagged is not None
        writer.execute(
            "UPDATE chunks SET start_s = ?, end_s = ?, flag_end_s = ?, word_start = ?, word_end = ? WHERE rowid = ?",
            (flag_end_s - 0.6, flag_end_s, flag_end_s, nxt["word_start"] - 3, nxt["word_start"], flagged["rowid"]),
        )
        writer.execute("UPDATE chunks SET start_s = ?, end_s = ? WHERE rowid = ?",
                       (NEXT_START, NEXT_START + 30.0, nxt["rowid"]))
        # Any other flagged chunk of the sermon is moved well away, so only this pair decides.
        writer.execute(
            "UPDATE chunks SET start_s = 1.0, end_s = 2.0, flag_end_s = 1.5, word_start = 0, word_end = 1 "
            "WHERE sermon_id = ? AND flag_end_s IS NOT NULL AND rowid != ?",
            (sermon_id, flagged["rowid"]),
        )
        writer.commit()
        return flagged["chunk_id"], nxt["chunk_id"]
    finally:
        writer.close()


def words_overlap(connection, chunk_id: str) -> bool:
    """The check before this fix: a flagged chunk sharing a word with ``chunk_id``."""
    row = connection.execute("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
    return connection.execute(
        "SELECT 1 FROM chunks WHERE sermon_id = ? AND flag_end_s IS NOT NULL AND word_start < ? AND word_end > ?",
        (row["sermon_id"], row["word_end"], row["word_start"]),
    ).fetchone() is not None


class SeekRule(unittest.TestCase):
    """touches_flagged on its own: the seek boundary, both link kinds."""

    def test_seek_time_is_the_earliest_link_seek(self) -> None:
        self.assertEqual(seek_time(NEXT_START), 379.0)  # YouTube t=379 is below the audio seek 379.15
        self.assertEqual(seek_time(0.5), 0.0)
        self.assertIsNone(seek_time(None))
        self.assertIsNone(seek_time(float("nan")))

    def connection(self, flag_end_s: float, flag_start_s: float | None = 378.0) -> sqlite3.Connection:
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute("CREATE TABLE chunks (sermon_id, start_s, end_s, word_start, word_end, flag_end_s)")
        connection.execute("INSERT INTO chunks VALUES ('s', ?, ?, 0, 10, ?)", (flag_start_s, flag_end_s, flag_end_s))
        return connection

    def hit(self, start_s: float = NEXT_START, end_s: float | None = 410.0):
        return SimpleNamespace(sermon_id="s", flag_end_s=None, word_start=10, word_end=20, start_s=start_s, end_s=end_s)

    def test_boundary(self) -> None:
        limit = seek_time(NEXT_START) - SEEK_SLACK_S  # 378.5
        self.assertTrue(touches_flagged(self.connection(NAME_END), self.hit()))
        self.assertTrue(touches_flagged(self.connection(limit + 0.01), self.hit()))
        self.assertFalse(touches_flagged(self.connection(limit), self.hit()))
        self.assertFalse(touches_flagged(self.connection(370.0, 369.0), self.hit()))

    def test_flagged_chunk_after_the_passage_does_not_count(self) -> None:
        self.assertFalse(touches_flagged(self.connection(420.0, 415.0), self.hit()))
        # ... unless the passage has no end (it may play on into it), or the flagged start is unknown.
        self.assertTrue(touches_flagged(self.connection(420.0, 415.0), self.hit(end_s=None)))
        self.assertTrue(touches_flagged(self.connection(420.0, None), self.hit()))


class YouTubeBackToBackTests(Base):
    def setUp(self) -> None:
        super().setUp()
        self.assertEqual(self.importer()[0], 0)
        self.assertEqual(self.cli(["--library", "wire", "--ack-review", ID_A])[0], 0)

    def live(self) -> LiveServer:
        connection = open_readonly(self.index, check_same_thread=False)
        self.addCleanup(connection.close)
        app = App(connection=connection, searcher=Searcher(connection), encode=None, fallback_note=None,
                  model_name=None, hosts={"127.0.0.1"}, static_dir=STATIC_DIR, library="wire")
        return LiveServer(self, app)

    def card(self, live: LiveServer, chunk_id: str) -> tuple[dict, str]:
        status, payload, body = live.get(f"/api/search?q={MARKER}&k=25&mode=bm25&library=wire")
        self.assertEqual(status, 200, body)
        cards = [r for r in payload["results"] if chunk_id in (r.get("chunk_ids") or [r["chunk_id"]])]
        self.assertEqual(len(cards), 1, body)
        return cards[0], body

    def test_next_chunk_gets_no_link_into_the_name(self) -> None:
        _, nxt = back_to_back(self.index, ID_A)
        connection = open_readonly(self.index)
        self.addCleanup(connection.close)
        self.assertFalse(words_overlap(connection, nxt))  # the old check passed this card
        live = self.live()
        card, body = self.card(live, nxt)
        self.assertIsNone(card["audio_url"])
        self.assertTrue(card["audio_withheld"])
        self.assertNotIn("&t=379s", body)
        self.assertIsNone(re.search(r"watch\?v=" + ID_A + r"&t=", json.dumps(card)))
        status, sermon, raw = live.get(f"/api/sermon/{ID_A}")
        self.assertEqual(status, 200, raw)
        self.assertNotIn("&t=379s", raw)
        # query.py, the same rule.
        hits = Searcher(connection, gated=True, library="wire").bm25(MARKER, 5)
        out = StringIO()
        with redirect_stdout(out):
            query.print_hits(MARKER, "bm25", None, hits, "none", connection)
        self.assertNotIn("t=379", out.getvalue())
        self.assertIn("withheld", out.getvalue())

    def test_name_ending_before_the_seek_slack_keeps_the_link(self) -> None:
        _, nxt = back_to_back(self.index, ID_A, flag_end_s=seek_time(NEXT_START) - SEEK_SLACK_S)
        card, _ = self.card(self.live(), nxt)
        self.assertEqual(card["audio_url"], f"https://www.youtube.com/watch?v={ID_A}&t=379s")


class AsrBackToBackTests(unittest.TestCase):
    """W1-C path: one archive.org file per sermon; the link is ``<file>#t=<seek>``."""

    AUDIO = "https://archive.org/download/church-sample/church-1.mp3"
    PAGE = "https://archive.org/details/church-sample"

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        env = {k: v for k, v in os.environ.items() if not k.startswith("PREACHED_PRIVACY") and k != "PREACHED_FLAGGED_AUDIO"}
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        spoken = "Gerald Fenwick brought soup. " + FILLER * 60 + f"{MARKER} ends here."
        transcript = root / "church-1.json"
        transcript.write_text(json.dumps({
            "meta": {"id": "church-1", "title": "Sunday morning", "audio_url": self.AUDIO, "ia_url": self.PAGE},
            "segments": [{"words": [[w.start, w.end, w.text] for w in words_for(spoken)]}],
        }))
        toml = root / "privacy.toml"
        toml.write_text("# none\n")
        self.index = root / "church.sqlite"
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            asr_chunks.main([str(transcript), "--out", str(root / "c.jsonl"), "--library", "church",
                             "--privacy", str(toml), "--index", str(self.index)], embedder=embedder)
            code = youtube_main(["--library", "church", "--ack-review", "church-1", "--privacy", str(toml)], index_dir=root)
        self.assertEqual(code, 0)

    def live(self) -> LiveServer:
        connection = open_readonly(self.index, check_same_thread=False)
        self.addCleanup(connection.close)
        app = App(connection=connection, searcher=Searcher(connection), encode=None, fallback_note=None,
                  model_name=None, hosts={"127.0.0.1"}, static_dir=STATIC_DIR, library="church")
        return LiveServer(self, app)

    def card(self, live: LiveServer, chunk_id: str) -> tuple[dict, str]:
        status, payload, body = live.get(f"/api/search?q={MARKER}&k=25&mode=bm25&library=church")
        self.assertEqual(status, 200, body)
        cards = [r for r in payload["results"] if chunk_id in (r.get("chunk_ids") or [r["chunk_id"]])]
        self.assertEqual(len(cards), 1, body)
        return cards[0], body

    def test_next_chunk_gets_no_link_into_the_name(self) -> None:
        _, nxt = back_to_back(self.index, "church-1")
        connection = open_readonly(self.index)
        self.addCleanup(connection.close)
        self.assertFalse(words_overlap(connection, nxt))
        live = self.live()
        card, body = self.card(live, nxt)
        self.assertIsNone(card["audio_url"])
        self.assertTrue(card["audio_withheld"])
        self.assertIsNone(card["start_s"])  # no time the page could seek to
        status, sermon, raw = live.get("/api/sermon/church-1")
        self.assertEqual(status, 200, raw)
        self.assertNotIn("#t=379.15", raw)
        hits = Searcher(connection, gated=True, library="church").bm25(MARKER, 5)
        out = StringIO()
        with redirect_stdout(out):
            query.print_hits(MARKER, "bm25", None, hits, "none", connection)
        self.assertNotIn("379.15", out.getvalue())
        self.assertIn("withheld", out.getvalue())

    def test_name_ending_before_the_seek_slack_keeps_the_link(self) -> None:
        _, nxt = back_to_back(self.index, "church-1", flag_end_s=seek_time(NEXT_START) - SEEK_SLACK_S)
        card, _ = self.card(self.live(), nxt)
        self.assertEqual(card["audio_url"], self.AUDIO)
        self.assertEqual(card["start_s"], NEXT_START)


if __name__ == "__main__":
    unittest.main()
