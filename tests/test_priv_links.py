"""#12 must-fix 2, Patrick's link rule, on every surface (/api/search, /api/sermon, search/query.py).

A flagged passage gets no link at all. An unflagged passage in the same sermon
keeps its own timed (seeked) link. The untimed sermon-level links (source_url,
a watch link with no t=, an audio file with no seek) play from 0:00, so they
are dropped for any sermon with a flagged passage. A sermon with no flagged
passage is unchanged. Every name below is invented.
"""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import io
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
from preached.search import Searcher, sermon_flagged, touches_flagged  # noqa: E402
from preached.store import open_readonly  # noqa: E402
from preached.youtube.cli import main as youtube_main  # noqa: E402
from preached.youtube.listing import watch_url  # noqa: E402
from test_privacy_wire import FILLER, ID_A, ID_B, Base, embedder, words_for  # noqa: E402
from coverage_stub import stub_audio

YOUTUBE = re.compile(r"https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]{11}(&t=\d+s)?")
QUERIES = ("soup", "faithful", "mercy", "season", "zephyrgrace", "morning", "God", "hospital", "children")


def links_in(value) -> list[str]:
    return [m.group(0) for m in YOUTUBE.finditer(json.dumps(value))]


def card_hit(row):
    return SimpleNamespace(**{key: row[key] for key in ("sermon_id", "flag_end_s", "word_start", "word_end", "start_s", "end_s")})


class YouTubeRuleTests(Base):
    """YouTube import: sermon A opens with names (flagged), B has none."""

    def setUp(self) -> None:
        super().setUp()
        self.assertEqual(self.importer(b="Our choir sang a hymn and the morning was bright. ")[0], 0)
        for video_id in (ID_A, ID_B):
            self.assertEqual(self.cli(["--library", "wire", "--ack-review", video_id])[0], 0)

    def results(self, app: App) -> list[dict]:
        seen = {}
        for q in QUERIES:
            for k in (1, 5, 20):
                for r in app.search(q, k, "bm25")["results"]:
                    seen[r["chunk_id"]] = r
        return list(seen.values())

    def rows(self, connection) -> dict[str, sqlite3.Row]:
        return {row["chunk_id"]: row for row in connection.execute("SELECT * FROM chunks")}

    def test_sermon_flagged(self) -> None:
        connection = self.app().connection
        self.assertTrue(sermon_flagged(connection, ID_A))
        self.assertFalse(sermon_flagged(connection, ID_B))

    def test_api_search(self) -> None:
        app = self.app()
        rows = self.rows(app.connection)
        results = self.results(app)
        checked = {"flagged": 0, "clear": 0, "B": 0}
        for r in results:
            row = rows[r["chunk_id"]]
            with self.subTest(chunk=r["chunk_id"]):
                if r["sermon_id"] == ID_B:
                    checked["B"] += 1
                    self.assertEqual(r["source_url"], f"https://www.youtube.com/watch?v={ID_B}")
                    self.assertIn("&t=", r["audio_url"])
                    continue
                # Sermon A: no untimed link anywhere in the card.
                self.assertIsNone(r["source_url"])
                for link in links_in(r):
                    self.assertIn("&t=", link)
                if row["flag_end_s"] is not None or touches_flagged(app.connection, card_hit(row)):
                    checked["flagged"] += 1
                    self.assertIsNone(r["audio_url"])
                    self.assertTrue(r["audio_withheld"])
                    self.assertEqual(links_in(r), [])
                else:
                    checked["clear"] += 1
                    # Its own timed link, rebuilt from the validated id and its own start.
                    self.assertEqual(r["audio_url"], watch_url(ID_A, row["start_s"]))
                    self.assertIn("&t=", r["audio_url"])
                    self.assertNotIn("audio_withheld", r)
        self.assertTrue(all(checked.values()), checked)

    def test_api_search_withholds_an_untimed_link_on_a_clear_passage(self) -> None:
        """A clear passage of a flagged sermon whose link would have no t= gets none."""
        writer = sqlite3.connect(self.index)
        writer.execute(
            "UPDATE chunks SET start_s = NULL, audio_url = ? WHERE video_id = ? AND flag_end_s IS NULL",
            (f"https://www.youtube.com/watch?v={ID_A}", ID_A),
        )
        writer.commit()
        writer.close()
        app = self.app()
        results = [r for r in self.results(app) if r["sermon_id"] == ID_A]
        self.assertTrue(results)
        for r in results:
            self.assertIsNone(r["audio_url"])
            self.assertIsNone(r["source_url"])
            self.assertEqual(links_in(r), [])

    def test_api_sermon(self) -> None:
        app = self.app()
        sermon = app.sermon(ID_A)
        self.assertIsNone(sermon["source_url"])
        self.assertIn("&t=", sermon["audio_url"])
        rows = [row for row in app.connection.execute("SELECT * FROM chunks WHERE video_id = ? ORDER BY rowid", (ID_A,))]
        clear = next(row for row in rows if row["flag_end_s"] is None and not touches_flagged(app.connection, card_hit(row)))
        self.assertEqual(sermon["audio_url"], watch_url(ID_A, clear["start_s"]))
        self.assertGreater(clear["start_s"], 0)
        # B has no flagged passage: unchanged, including its source link.
        other = app.sermon(ID_B)
        self.assertEqual(other["source_url"], f"https://www.youtube.com/watch?v={ID_B}")
        self.assertIn("&t=", other["audio_url"])

    def test_api_sermon_never_gives_an_untimed_link(self) -> None:
        writer = sqlite3.connect(self.index)
        writer.execute("UPDATE chunks SET start_s = NULL WHERE video_id = ? AND flag_end_s IS NULL", (ID_A,))
        writer.commit()
        writer.close()
        sermon = self.app().sermon(ID_A)
        self.assertIsNone(sermon["audio_url"])
        self.assertIsNone(sermon["source_url"])

    def test_query_cli(self) -> None:
        connection = self.app().connection
        hits = Searcher(connection, gated=True, library="wire").bm25("God faithful mercy soup morning", 20)
        out = io.StringIO()
        with redirect_stdout(out):
            query.print_hits("q", "bm25", None, hits, "none", connection)
        text = out.getvalue()
        cards = text.split("\n[")[1:]
        self.assertTrue(cards)
        seen = {ID_A: 0, ID_B: 0}
        for card, hit in zip(cards, hits):
            seen[hit.sermon_id] += 1
            text_line = next(line for line in card.splitlines() if line.strip().startswith("text:"))
            play_line = next(line for line in card.splitlines() if line.strip().startswith("play:"))
            if hit.sermon_id == ID_B:
                self.assertIn(f"watch?v={ID_B}", text_line)
                continue
            self.assertNotIn("youtube", text_line)
            for link in YOUTUBE.finditer(card):
                self.assertIn("&t=", link.group(0))
            if hit.flag_end_s is not None or touches_flagged(connection, hit):
                self.assertIn("withheld", play_line)
            else:
                self.assertIn(watch_url(ID_A, hit.start_s), play_line)
        self.assertTrue(all(seen.values()), seen)

    def test_query_cli_untimed_clear_passage(self) -> None:
        hit = SimpleNamespace(start_s=None, end_s=None, flag_end_s=None, video_id=ID_A, sermon_id=ID_A,
                              audio_url=f"https://www.youtube.com/watch?v={ID_A}",
                              source_url=f"https://www.youtube.com/watch?v={ID_A}")
        self.assertIn("withheld", query.hit_play(hit, "none", False, True))
        self.assertIn("withheld", query.hit_text_link(hit, "none", False, True))
        # Without a flagged passage in the sermon, the old behaviour.
        self.assertEqual(query.hit_text_link(hit, "none", False, False), hit.source_url)


class AsrRuleTests(unittest.TestCase):
    """W1-C path: one archive.org file per sermon, source_url is its details page."""

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
        spoken = "Gerald Fenwick brought soup. " + FILLER * 60
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
                             "--privacy", str(toml), "--index", str(self.index), *stub_audio(transcript)], embedder=embedder, coverage=lambda *_a, **_k: [])
            code = youtube_main(["--library", "church", "--ack-review", "church-1", "--privacy", str(toml)], index_dir=root)
        self.assertEqual(code, 0)
        self.connection = open_readonly(self.index, check_same_thread=False)
        self.addCleanup(self.connection.close)
        self.app = App(connection=self.connection, searcher=Searcher(self.connection), encode=None, fallback_note=None,
                       model_name=None, hosts={"127.0.0.1"}, static_dir=STATIC_DIR, library="church")

    def test_api_search_and_cli(self) -> None:
        results = self.app.search("God faithful mercy season", 20, "bm25")["results"]
        rows = {row["chunk_id"]: row for row in self.connection.execute("SELECT * FROM chunks")}
        self.assertTrue(any(rows[r["chunk_id"]]["flag_end_s"] is None for r in results))
        for r in results:
            self.assertIsNone(r["source_url"])  # the details page plays from 0:00
            row = rows[r["chunk_id"]]
            if row["flag_end_s"] is None and not touches_flagged(self.connection, card_hit(row)):
                self.assertEqual(r["audio_url"], self.AUDIO)
                self.assertIsNotNone(r["start_s"])  # the page seeks to it
        hits = Searcher(self.connection, gated=True, library="church").bm25("God faithful mercy season", 20)
        out = io.StringIO()
        with redirect_stdout(out):
            query.print_hits("q", "bm25", None, hits, "none", self.connection)
        text = out.getvalue()
        self.assertNotIn(self.PAGE, text)
        for line in text.splitlines():
            if self.AUDIO in line:
                self.assertIn("#t=", line)

    def test_untimed_clear_passage_gets_no_link(self) -> None:
        writer = sqlite3.connect(self.index)
        writer.execute("UPDATE chunks SET start_s = NULL WHERE flag_end_s IS NULL")
        writer.commit()
        writer.close()
        for r in self.app.search("God faithful mercy season", 20, "bm25")["results"]:
            self.assertIsNone(r["audio_url"])
            self.assertIsNone(r["source_url"])
        self.assertIsNone(self.app.sermon("church-1")["audio_url"])

    def test_api_sermon(self) -> None:
        sermon = self.app.sermon("church-1")
        self.assertIsNone(sermon["source_url"])
        self.assertTrue(sermon["audio_url"].startswith(self.AUDIO + "#t="))


if __name__ == "__main__":
    unittest.main()
