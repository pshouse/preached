"""#19 CTO must-fix 1: no play link seeks into an excluded stretch.

The chunk right after a stretch used to seek back into it by its pre-roll
(t=14s, 122s, 229s on /api/search, query.py and /api/sermon; 0.65 s inside on
the ASR path), and /api/sermon kept the 0:00 source_url. Now the chunks on
both sides of a stretch carry ``flag_end_s`` (``exclusions.boundary_flags``),
so they get no link, the sermon loses its untimed links, and the shared
``search.touches_flagged`` rule (SEEK_SLACK_S) covers every other chunk. The
same composition holds for a redacted name next to a stretch. Checked on the
real HTTP server and query.py, for a YouTube import and an ASR import.
Every name and marker word below is invented.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for sub in ("search", "align", "tests"):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

import asr_chunks  # noqa: E402
import query  # noqa: E402
from app.server import STATIC_DIR, App  # noqa: E402
from preached.exclusions import boundary_flags  # noqa: E402
from preached.search import SEEK_SLACK_S, Searcher, seek_time  # noqa: E402
from preached.store import open_readonly  # noqa: E402
from preached.youtube.cli import main as youtube_main  # noqa: E402
from preached.youtube.listing import Video  # noqa: E402
from test_priv_skip import PRAYER, SERVICE  # noqa: E402
from test_privacy_wire import CHANNEL, FILLER, ID_A, Base, embedder, words_for  # noqa: E402
from test_privacy_wire_fix import LiveServer  # noqa: E402

# A word every kept chunk of SERVICE holds (FILLER), so one search returns them all.
EVERYWHERE = "faithful"
# A redacted name spoken one sentence before the prayer stretch: it lands in the chunk next to it.
NAMED = SERVICE.replace(PRAYER, "Thank you Gerald Fenwick for the music. " + FILLER + PRAYER)


def seeks(text: str) -> list[float]:
    """Every seek in a body: YouTube ``t=Ns`` and audio ``#t=X``."""
    found = [float(m) for m in re.findall(r"[?&]t=(\d+)s", text)]
    found += [float(m) for m in re.findall(r"#t=([0-9.]+)", text)]
    return found


class BoundaryFlagsUnit(unittest.TestCase):
    def test_heads_and_tails(self) -> None:
        def run(a, b):
            return [{"i": i, "s": i * 1.0, "e": i + 0.4} for i in range(a, b)]

        # words 0-2 kept, 3-5 excluded, 6-9 kept, 10-11 excluded (to the end)
        runs = [run(0, 3), run(6, 10)]
        self.assertEqual(boundary_flags(runs, 12), [(None, 6.0), (6.0, 9.4)])
        # stretch at the start, nothing after
        self.assertEqual(boundary_flags([run(2, 5)], 5), [(2.0, None)])
        self.assertEqual(boundary_flags([run(0, 5)], 5), [(None, None)])


class Checks:
    """Shared assertions over one imported, approved sermon."""

    def stretches(self) -> list[dict]:
        lines = [json.loads(line) for line in self.review.read_text().splitlines()]
        found = [line for line in lines if line.get("field") == "exclude"]
        self.assertGreaterEqual(len(found), 3)
        return found

    def assert_no_seek_inside(self, text: str, where: str) -> None:
        for t in seeks(text):
            for line in self.stretches():
                self.assertFalse(
                    line["start_s"] <= t < line["end_s"] + SEEK_SLACK_S,
                    f"{where}: seek {t} inside excluded {line['start_s']}-{line['end_s']} (+{SEEK_SLACK_S} s)",
                )

    def check_all_surfaces(self, sermon_id: str, library: str) -> None:
        connection = open_readonly(self.index)
        self.addCleanup(connection.close)
        rows = list(connection.execute("SELECT * FROM chunks WHERE sermon_id = ? ORDER BY word_start", (sermon_id,)))
        # The chunks either side of each stretch, by time (ASR word_start counts tokens, not words).
        neighbours, after = [], []
        for line in self.stretches():
            before = [r for r in rows if r["end_s"] <= line["start_s"]]
            later = [r for r in rows if r["start_s"] >= line["end_s"]]
            if before:
                neighbours.append(max(before, key=lambda r: r["end_s"]))
            if later:
                after.append(min(later, key=lambda r: r["start_s"]))
        neighbours += after
        for row in neighbours:
            self.assertIsNotNone(row["flag_end_s"], dict(row))
        self.assertGreaterEqual(len(neighbours), 4)
        # Without the fix the chunk right after a stretch seeks back into it.
        self.assertTrue(any(
            line["start_s"] <= seek_time(r["start_s"]) < line["end_s"] + SEEK_SLACK_S
            for r in after for line in self.stretches()
        ))
        flagged_ids = {r["chunk_id"] for r in neighbours}

        live_connection = open_readonly(self.index, check_same_thread=False)
        self.addCleanup(live_connection.close)
        app = App(connection=live_connection, searcher=Searcher(live_connection), encode=None, fallback_note=None,
                  model_name=None, hosts={"127.0.0.1"}, static_dir=STATIC_DIR, library=library)
        live = LiveServer(self, app)
        status, payload, body = live.get(f"/api/search?q={EVERYWHERE}&k=25&mode=bm25&library={library}")
        self.assertEqual(status, 200, body)
        self.assertTrue(payload["results"])
        self.assert_no_seek_inside(body, "/api/search")
        for card in payload["results"]:
            if flagged_ids & set(card.get("chunk_ids") or [card["chunk_id"]]):
                self.assertIsNone(card["audio_url"], card)
                self.assertTrue(card["audio_withheld"], card)
        status, sermon, raw = live.get(f"/api/sermon/{sermon_id}")
        self.assertEqual(status, 200, raw)
        self.assertIsNone(sermon.get("source_url"), raw)  # untimed: would play from 0:00
        self.assert_no_seek_inside(raw, "/api/sermon")
        if sermon.get("audio_url"):
            self.assertTrue(seeks(sermon["audio_url"]), sermon["audio_url"])  # never an untimed link

        hits = Searcher(connection, gated=True, library=library).bm25(EVERYWHERE, 100)
        out = StringIO()
        with redirect_stdout(out):
            query.print_hits(EVERYWHERE, "bm25", None, hits, "none", connection)
        self.assert_no_seek_inside(out.getvalue(), "query.py")
        self.assertIn("withheld", out.getvalue())


class YouTubeTests(Checks, Base):
    def setUp(self) -> None:
        super().setUp()
        self.review = self.review_file(ID_A)

    def run_import(self, text: str) -> None:
        video = Video(ID_A, "Sunday service", 400, date(2024, 6, 2), f"https://www.youtube.com/watch?v={ID_A}")
        code, _out, err = self.cli(
            [CHANNEL, "--library", "wire"],
            lister=lambda _url: [video],
            metadata=lambda v: {"title": v.title, "duration": 400, "upload_date": "20240602"},
            downloader=lambda v, dest: dest / f"{v.id}.m4a",
            transcriber=lambda path: words_for(text),
            embedder=embedder,
            coverage=lambda *_a, **_k: [],
        )
        self.assertEqual(code, 0, err)
        code, _out, err = self.cli(["--library", "wire", "--ack-review", ID_A])
        self.assertEqual(code, 0, err)

    def test_no_link_seeks_into_a_stretch(self) -> None:
        self.run_import(SERVICE)
        self.check_all_surfaces(ID_A, "wire")

    def test_name_next_to_a_stretch(self) -> None:
        self.run_import(NAMED)
        self.check_all_surfaces(ID_A, "wire")
        connection = open_readonly(self.index)
        self.addCleanup(connection.close)
        name_rows = [r for r in connection.execute("SELECT * FROM chunks WHERE text LIKE '%[name]%'")]
        self.assertTrue(name_rows)
        self.assertTrue(all(r["flag_end_s"] is not None for r in name_rows))
        self.assertNotIn(b"Fenwick", self.index.read_bytes())


class AsrTests(Checks, unittest.TestCase):
    AUDIO = "https://archive.org/download/church-sample/church-1.mp3"
    PAGE = "https://archive.org/details/church-sample"

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = {k: v for k, v in os.environ.items() if not k.startswith("PREACHED_PRIVACY") and k != "PREACHED_FLAGGED_AUDIO"}
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.index = self.root / "church.sqlite"
        self.review = self.root / "church" / "review" / "church-1.review.jsonl"

    def run_import(self, text: str) -> None:
        transcript = self.root / "church-1.json"
        transcript.write_text(json.dumps({
            "meta": {"id": "church-1", "title": "Sunday morning", "audio_url": self.AUDIO, "ia_url": self.PAGE},
            "segments": [{"words": [[w.start, w.end, w.text] for w in words_for(text)]}],
        }))
        toml = self.root / "privacy.toml"
        toml.write_text("# none\n")
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()) as err:
            asr_chunks.main([str(transcript), "--out", str(self.root / "c.jsonl"), "--library", "church",
                             "--privacy", str(toml), "--index", str(self.index)], embedder=embedder, coverage=lambda *_a, **_k: [])
            code = youtube_main(["--library", "church", "--ack-review", "church-1", "--privacy", str(toml)], index_dir=self.root)
        self.assertEqual(code, 0, err.getvalue())

    def test_no_link_seeks_into_a_stretch(self) -> None:
        self.run_import(SERVICE)
        self.check_all_surfaces("church-1", "church")

    def test_name_next_to_a_stretch(self) -> None:
        self.run_import(NAMED)
        self.check_all_surfaces("church-1", "church")


if __name__ == "__main__":
    unittest.main()
