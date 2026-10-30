"""PR #12 merged with #11 (dedupe merges) and #13 (YouTube watch links).

A merged card keeps only its main chunk's flag fields, so a flagged chunk
must never be merged into another card. Under the default ``none`` policy no
card that touches a flagged chunk may carry a play or watch link, on the API,
the page or the CLI. 
Every name below is invented.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from app.server import hit_dict
from preached.search import MERGE_MAX_WORDS, Hit, dedupe_adjacent, merge_overlapping, repeats_kept
from preached.store import open_readonly
from preached.youtube.listing import watch_url
from unittest.mock import patch

from test_dedupe import hit, words
from test_privacy_wire import FILLER, ID_A, ID_B, REPO_ROOT, Base, embedder, words_for

YT = f"https://www.youtube.com/watch?v={ID_A}"
APP_JS = REPO_ROOT / "app" / "static" / "app.js"
# Every word of the fixture that is not a redaction marker; enough to put
# each chunk on some page at several k.
QUERIES = (
    "soup", "hospital", "children", "taught", "called", "neighbor brought",
    "God is faithful", "every season of life", "mercy is new each morning",
    "faithful mercy", "season morning", "zephyrgrace", "week told", "friend",
)


def yt_hit(**kwargs) -> Hit:
    base = dict(sermon_id=ID_A, video_id=ID_A, audio_url=f"{YT}&t=0s", source_url=YT, text_source="asr")
    base.update(kwargs)
    return hit(**base)


def import_query_module():
    sys.path.insert(0, str(REPO_ROOT / "search"))
    try:
        import query
    finally:
        sys.path.pop(0)
    return query


class MergeGuardTests(unittest.TestCase):
    """(a) A merge candidate pair with a flagged side is never merged."""

    def pair(self, flag_best: bool):
        best = yt_hit(chunk_id="c1", score=3, word_start=100, word_end=200, text=words("w", 100, 200),
                      start_s=50.0, end_s=95.0, flag_end_s=60.0 if flag_best else None)
        before = yt_hit(chunk_id="c0", score=2, word_start=20, word_end=125, text=words("w", 20, 125),
                        start_s=10.0, end_s=60.0, flag_end_s=None if flag_best else 12.0)
        return best, before

    def test_flagged_neighbour_is_not_merged(self) -> None:
        best, before = self.pair(flag_best=False)
        self.assertIsNone(merge_overlapping(best, before))
        kept = dedupe_adjacent([best, before], limit=10)
        # Stays separate: the flagged neighbour is dropped, not folded in.
        self.assertEqual([card.chunk_ids for card in kept], [["c1"]])
        self.assertEqual(kept[0].start_s, 50.0)
        # The flagged chunk on its own gets no link under the default policy.
        payload = hit_dict(before)
        self.assertIsNone(payload["audio_url"])
        self.assertIsNone(payload["source_url"])
        self.assertTrue(payload["audio_withheld"])
        # And the kept card, whose span touches the flagged chunk, gets none either.
        touching = hit_dict(kept[0], near_flag=True)
        self.assertIsNone(touching["audio_url"])
        self.assertTrue(touching["audio_withheld"])

    def test_flagged_kept_card_absorbs_nothing(self) -> None:
        best, before = self.pair(flag_best=True)
        self.assertIsNone(merge_overlapping(best, before))
        kept = dedupe_adjacent([best, before], limit=10)
        self.assertEqual([card.chunk_ids for card in kept], [["c1"]])
        self.assertEqual(kept[0].flag_end_s, 60.0)
        self.assertIsNone(hit_dict(kept[0])["audio_url"])

    def test_different_video_ids_are_not_merged(self) -> None:
        best, before = self.pair(flag_best=False)
        before = yt_hit(**{**before.__dict__, "flag_end_s": None, "video_id": ID_B})
        self.assertIsNone(merge_overlapping(best, before))
        same = yt_hit(**{**before.__dict__, "video_id": ID_A})
        self.assertIsNotNone(merge_overlapping(best, same))

    def test_random_lists_with_flags(self) -> None:
        """The dedupe property test, with ~1 in 4 chunks flagged."""
        rng = random.Random(20261031)
        for run in range(5000):
            pool = []
            for sermon in range(rng.randint(1, 3)):
                start = 0
                for index in range(rng.randint(1, 10)):
                    size = rng.randint(60, 150)
                    pool.append(yt_hit(
                        rowid=len(pool) + 1, score=rng.choice([rng.random(), round(rng.random(), 1)]),
                        chunk_id=f"s{sermon}-c{index:04d}", sermon_id=f"s{sermon}", video_id=f"vid{sermon:08d}",
                        text=words(f"s{sermon}w", start, start + size), word_start=start, word_end=start + size,
                        flag_end_s=1.0 if rng.random() < 0.25 else None,
                    ))
                    start += size - max(1, size // 4)
            rng.shuffle(pool)
            flagged = {h.chunk_id for h in pool if h.flag_end_s is not None}
            limit = rng.randint(1, 10)
            kept = dedupe_adjacent(pool, limit)
            with self.subTest(run=run):
                for card in kept:
                    ids = card.chunk_ids
                    if len(ids) > 1:
                        self.assertFalse(flagged & set(ids), ids)
                    self.assertEqual(card.flag_end_s is not None, bool(flagged & set(ids)))
                    self.assertLessEqual(len(card.text.split()), MERGE_MAX_WORDS)
                for i, first in enumerate(kept):
                    for second in kept[i + 1:]:
                        self.assertFalse(repeats_kept(second, first))
                shown = " ".join(card.text for card in kept).split()
                self.assertEqual(len(shown), len(set(shown)))
                self.assertEqual(dedupe_adjacent(kept, limit), kept)


class ServedTests(Base):
    """(b) Real import (synthetic channel), real SQLite, real dedupe."""

    def setUp(self) -> None:
        super().setUp()
        # Stored watch links that point at the names, as an import made under
        # play before Patrick chose none would have left them: every client
        # must rebuild or drop them, never pass them through. play can no
        # longer be configured, so the fixture writes those links itself.
        code, _out, err = self.importer()
        self.assertEqual(code, 0, err)
        writer = sqlite3.connect(self.index)
        for rowid, video_id, start_s in list(writer.execute("SELECT rowid, video_id, start_s FROM chunks")):
            writer.execute("UPDATE chunks SET audio_url = ? WHERE rowid = ?", (watch_url(video_id, start_s), rowid))
        writer.commit()
        writer.close()
        for video_id in (ID_A, ID_B):
            code, _out, err = self.cli(["--library", "wire", "--ack-review", video_id])
            self.assertEqual(code, 0, err)
        connection = sqlite3.connect(self.index)
        connection.row_factory = sqlite3.Row
        self.rows = {row["chunk_id"]: row for row in connection.execute("SELECT * FROM chunks")}
        connection.close()
        self.flagged = {cid: row for cid, row in self.rows.items() if row["flag_end_s"] is not None}
        self.assertTrue(self.flagged)
        # The stored link of a flagged chunk plays the name (imported under play).
        some = next(iter(self.flagged.values()))
        self.assertIn("&t=", some["audio_url"])

    def touches(self, card: dict) -> bool:
        spans = [self.rows[cid] for cid in card["chunk_ids"]]
        start = min(row["word_start"] for row in spans)
        end = max(row["word_end"] for row in spans)
        return any(
            row["sermon_id"] == card["sermon_id"] and row["word_start"] < end and row["word_end"] > start
            for row in self.flagged.values()
        )

    def cards(self, app) -> list[dict]:
        out = []
        for query in QUERIES:
            for k in (1, 3, 5, 10, 20):
                out.extend(app.search(query, k, "bm25")["results"])
        return out

    def test_no_card_touching_a_flagged_chunk_has_a_link_by_default(self) -> None:
        cards = self.cards(self.app())
        touching = [card for card in cards if self.touches(card)]
        clear = [card for card in cards if not self.touches(card)]
        self.assertTrue(touching, "fixture never served a card near a name")
        self.assertTrue(clear, "fixture never served a clear card")
        # #11 merges only chunks with the same audio_url; every YouTube chunk
        # stores its own &t= link, so YouTube cards are single chunks.
        # ChurchAsrServedTests covers merged cards.
        for card in touching:
            self.assertIsNone(card["audio_url"], card["chunk_ids"])
            self.assertIsNone(card["source_url"], card["chunk_ids"])
            self.assertTrue(card["audio_withheld"])
            self.assertIsNone(card["start_s"])
            self.assertNotIn("play_from_s", card)
            self.assertNotIn("youtube", json.dumps(card))
        for card in clear:
            self.assertTrue(card["audio_url"].startswith(f"https://www.youtube.com/watch?v="))
        # A merged card never contains a flagged chunk.
        for card in cards:
            if len(card["chunk_ids"]) > 1:
                self.assertFalse(set(card["chunk_ids"]) & set(self.flagged), card["chunk_ids"])

    def soup(self, app) -> dict:
        results = [r for r in app.search("soup", 5, "bm25")["results"] if "soup" in r["text"]]
        self.assertEqual(len(results), 1)
        return results[0]



    def run_page(self, cards: list[dict], checks: str) -> None:
        if not shutil.which("deno"):
            self.skipTest("deno not installed")
        from test_app_js import PRELUDE

        script = PRELUDE + APP_JS.read_text() + f"""
var CARDS = {json.dumps(cards)};
function walk(n, out) {{ out.push(n); n.children.forEach(function (c) {{ walk(c, out); }}); return out; }}
function nodes(card) {{ return walk(renderCard(card), []); }}
function text(card) {{ return nodes(card).map(function (n) {{ return n.textContent; }}).join("|"); }}
function hrefs(card) {{ return nodes(card).map(function (n) {{ return n.href || ""; }}).filter(Boolean); }}
{checks}
console.log("ok");
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "check.js"
            path.write_text(script)
            result = subprocess.run(["deno", "run", "--quiet", "--no-prompt", "--no-config", str(path)],
                                    capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_page_renders_no_link_under_none(self) -> None:
        cards = [card for card in self.cards(self.app()) if self.touches(card)]
        self.run_page(cards, """
CARDS.forEach(function (card) {
  var all = text(card);
  if (!all.includes("Text only")) throw new Error("no text-only note: " + all);
  if (all.includes("Watch on YouTube") || all.includes("Play from")) throw new Error("link: " + all);
  if (hrefs(card).length) throw new Error("href: " + hrefs(card));
});
""")


    def cli_output(self, policy: str, query_text: str) -> str:
        query = import_query_module()
        connection = open_readonly(self.index)
        self.addCleanup(connection.close)
        from preached.search import Searcher

        hits = Searcher(connection).bm25(query_text, 20)
        out = StringIO()
        with redirect_stdout(out):
            query.print_hits(query_text, "bm25", None, hits, policy, connection)
        return out.getvalue()

    def test_cli_prints_no_link_under_none(self) -> None:
        out = self.cli_output("none", "soup hospital children taught called faithful")
        blocks = out.split("\n[")[1:]
        self.assertTrue(blocks)
        withheld = 0
        for block in blocks:
            cid = re.search(r", ([^)]+)\)\n", block).group(1)
            if cid in self.flagged:
                withheld += 1
                self.assertIn("audio withheld", block)
                self.assertNotIn("youtube", block)
        self.assertGreater(withheld, 0)



class ChurchAsrServedTests(unittest.TestCase):
    """(b) on the W1-C church ASR path: one audio file per sermon, so #11's
    dedupe does merge neighbouring chunks here."""

    AUDIO = "https://archive.org/download/church-sample/church-1.mp3"

    def setUp(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "align"))
        self.addCleanup(sys.path.remove, str(REPO_ROOT / "align"))
        import asr_chunks

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        env = {k: v for k, v in os.environ.items() if k not in ("PREACHED_PRIVACY", "PREACHED_FLAGGED_AUDIO")}
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        spoken = FILLER * 30 + "Gerald Fenwick brought soup. " + FILLER * 30 + "Timothy came too. " + FILLER * 30
        transcript = root / "church-1.json"
        transcript.write_text(json.dumps({
            "meta": {"id": "church-1", "title": "Sunday morning", "audio_url": self.AUDIO},
            "segments": [{"words": [[w.start, w.end, w.text] for w in words_for(spoken)]}],
        }))
        toml = root / "privacy.toml"
        toml.write_text('block = ["Timothy"]\n')
        index = root / "church.sqlite"
        argv = [str(transcript), "--out", str(root / "chunks.jsonl"), "--library", "church",
                "--privacy", str(toml), "--index", str(index)]
        from contextlib import redirect_stderr
        from preached.youtube.cli import main as youtube_main

        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            asr_chunks.main(argv, embedder=embedder, coverage=lambda *_a, **_k: [])
            code = youtube_main(["--library", "church", "--ack-review", "church-1", "--privacy", str(toml)],
                                index_dir=root)
        self.assertEqual(code, 0)
        self.connection = open_readonly(index, check_same_thread=False)
        self.addCleanup(self.connection.close)
        self.connection.row_factory = sqlite3.Row
        self.rows = {row["chunk_id"]: row for row in self.connection.execute("SELECT * FROM chunks")}
        self.flagged = {cid: row for cid, row in self.rows.items() if row["flag_end_s"] is not None}
        self.assertGreaterEqual(len(self.flagged), 2)
        self.assertLess(len(self.flagged), len(self.rows))

    def app(self, policy=None):
        from app.server import STATIC_DIR, App
        from preached.search import Searcher

        app = App(connection=self.connection, searcher=Searcher(self.connection), encode=None, fallback_note=None,
                  model_name=None, hosts={"127.0.0.1"}, static_dir=STATIC_DIR, library="church")
        if policy is not None:
            app.flagged_audio = policy  # test hook only; nothing configures it (Patrick chose none)
        return app

    touches = ServedTests.touches
    cards = ServedTests.cards

    def test_no_card_touching_a_flagged_chunk_has_a_link_by_default(self) -> None:
        cards = self.cards(self.app())
        merged = [card for card in cards if len(card["chunk_ids"]) > 1]
        self.assertTrue(merged, "fixture never merged two chunks")
        touching = [card for card in cards if self.touches(card)]
        self.assertTrue(touching)
        self.assertTrue([card for card in cards if not self.touches(card)])
        for card in cards:
            self.assertFalse(set(card["chunk_ids"]) & set(self.flagged) and len(card["chunk_ids"]) > 1,
                             card["chunk_ids"])
            if self.touches(card):
                self.assertIsNone(card["audio_url"], card["chunk_ids"])
                self.assertTrue(card["audio_withheld"], card["chunk_ids"])
                self.assertIsNone(card["start_s"])
                self.assertNotIn("play_from_s", card)
            else:
                self.assertEqual(card["audio_url"], self.AUDIO)

    def test_play_policy_still_merges_nothing_flagged(self) -> None:
        for card in self.cards(self.app("play")):
            if len(card["chunk_ids"]) > 1:
                self.assertFalse(set(card["chunk_ids"]) & set(self.flagged), card["chunk_ids"])


if __name__ == "__main__":
    unittest.main()
