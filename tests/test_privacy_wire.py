"""W3-PRIV-WIRE: redaction, review files, the publish gate and flagged-audio policy.

Synthetic two-video channel; every name below is invented.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.server import STATIC_DIR, App, hit_dict
from preached.audio_policy import check_flagged_audio, flagged_play, resolve_flagged_audio
from preached.privacy import Config
from preached.search import Hit, Searcher
from preached.store import hidden_rowids, open_readonly
from preached.youtube.chunking import chunk_words
from preached.youtube.cli import main
from preached.youtube.listing import Video, watch_url
from preached.youtube.pipeline import REPO_ROOT, write_private_review
from preached.youtube.words import Word
from preached.corpus import load_chunk_config

CHANNEL = "https://www.youtube.com/channel/UCwiretest"
ID_A, ID_B = "wirevideo01", "wirevideo02"
OPENING_A = (
    "Last week my neighbor Gerald Fenwick brought me soup. "
    "I told Paul about the hospital and Timothy came too. "
)
OPENING_B = "Our friend Brenda Okonkwo-Vale taught the children. Then Mrs. Thistlewood called. "
FILLER = "God is faithful in every season of life and mercy is new each morning. "


def words_for(text: str, step: float = 0.5) -> list[Word]:
    return [Word(i * step, i * step + 0.4, token) for i, token in enumerate(text.split())]


def transcript(opening: str) -> list[Word]:
    return words_for(opening + FILLER * 40 + "zephyrgrace ends here.")


def embedder(titles: list[str], texts: list[str]) -> np.ndarray:
    matrix = np.zeros((len(texts), 8), dtype=np.float32)
    for row, text in enumerate(texts):
        for token in text.lower().split():
            matrix[row, hashlib.sha256(token.encode()).digest()[0] % 8] += 1.0
        matrix[row, 0] += 1.0
    return matrix


def videos() -> list[Video]:
    return [
        Video(ID_A, "Soup with Gerald Fenwick", 400, date(2024, 6, 2), f"https://www.youtube.com/watch?v={ID_A}"),
        Video(ID_B, "Sunday morning", 400, date(2024, 6, 9), f"https://www.youtube.com/watch?v={ID_B}"),
    ]


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        env = {k: v for k, v in os.environ.items() if not k.startswith("PREACHED_PRIVACY") and k != "PREACHED_FLAGGED_AUDIO"}
        # A church import needs a privacy config (fail closed). An empty one
        # keeps the built-in rules; tests of the refusal remove it.
        self.empty_config = self.root / "empty-privacy.toml"
        self.empty_config.write_text("# no library-specific names\n")
        env["PREACHED_PRIVACY"] = str(self.empty_config)
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def cli(self, argv: list[str], **kwargs):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv, index_dir=self.root, audio_root=self.root / "audio", **kwargs)
        return code, out.getvalue(), err.getvalue()

    def importer(self, extra: list[str] | None = None, *, a: str = OPENING_A, b: str = OPENING_B):
        spoken = {ID_A: transcript(a), ID_B: transcript(b)}
        return self.cli(
            [CHANNEL, "--library", "wire", *(extra or [])],
            lister=lambda _url: videos(),
            metadata=lambda video: {"title": video.title, "duration": 400, "upload_date": "20240602"},
            downloader=lambda video, dest: dest / f"{video.id}.m4a",
            transcriber=lambda path: spoken[Path(path).stem],
            coverage=lambda *_a, **_k: [],
            embedder=embedder,
        )

    @property
    def index(self) -> Path:
        return self.root / "wire.sqlite"

    def review_file(self, video_id: str) -> Path:
        return self.root / "wire" / "review" / f"{video_id}.review.jsonl"

    def app(self, flagged_audio: str | None = None, **kwargs) -> App:
        connection = open_readonly(self.index, check_same_thread=False)
        self.addCleanup(connection.close)
        app = App(
            connection=connection,
            searcher=Searcher(connection),
            encode=None,
            fallback_note=None,
            model_name=None,
            hosts={"127.0.0.1"},
            static_dir=STATIC_DIR,
            library="wire",
            **kwargs,
        )
        if flagged_audio is not None:
            # Test hook only. No flag, env or TOML selects play for a
            # church library (Patrick chose none); this exercises the kept code.
            app.flagged_audio = check_flagged_audio(flagged_audio)
        return app


class EndToEndTests(Base):
    def test_redacted_chunks_review_files_and_publish_gate(self) -> None:
        code, out, err = self.importer()
        self.assertEqual(code, 0, err)

        # Names are gone from the stored chunks and the title; timings are untouched.
        raw = self.index.read_bytes()
        for name in (b"Fenwick", b"Gerald", b"Okonkwo", b"Thistlewood", b"Brenda"):
            self.assertNotIn(name, raw)
        connection = open_readonly(self.index)
        rows = list(connection.execute("SELECT * FROM chunks WHERE video_id = ? ORDER BY rowid", (ID_A,)))
        self.assertIn("[name]", rows[0]["text"])
        self.assertEqual(rows[0]["sermon_title"], "Soup with [name] [name]")
        plain = chunk_words(transcript(OPENING_A), load_chunk_config())
        self.assertEqual(len(rows), len(plain))
        for row, expected in zip(rows, plain):
            for key in ("start_s", "end_s", "word_start", "word_end", "word_count"):
                self.assertEqual(row[key], expected[key], key)
        connection.close()

        # One owner-only review file per video; counts only on the console.
        for video_id in (ID_A, ID_B):
            path = self.review_file(video_id)
            self.assertTrue(path.is_file())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        self.assertIn("Timothy", self.review_file(ID_A).read_text())
        self.assertIn("review items", out)
        for text in (out, err):
            for name in ("Fenwick", "Gerald", "Okonkwo", "Timothy", "Thistlewood"):
                self.assertNotIn(name, text)
        self.assertIn("UNPUBLISHED", err)

        # Unacknowledged: invisible to search, the sermon route and /healthz.
        app = self.app()
        self.assertEqual(app.search("faithful", 5, "bm25")["results"], [])
        self.assertEqual(app.search("soup", 5, "bm25")["results"], [])
        self.assertIsNone(app.sermon(ID_A))
        self.assertEqual(app.health()["chunks"], 0)
        self.assertEqual(len(hidden_rowids(app.connection)), app.connection.execute("SELECT count(*) FROM chunks").fetchone()[0])

        # Approving one sermon publishes only that sermon.
        code, _out, err = self.cli(["--library", "wire", "--ack-review", ID_A])
        self.assertEqual(code, 0, err)
        app = self.app()
        hits = app.search("faithful", 50, "bm25")["results"]
        self.assertTrue(hits)
        self.assertEqual({hit["sermon_id"] for hit in hits}, {ID_A})
        self.assertIsNotNone(app.sermon(ID_A))
        self.assertIsNone(app.sermon(ID_B))
        self.assertGreater(app.health()["chunks"], 0)
        self.assertLess(app.health()["chunks"], app.connection.execute("SELECT count(*) FROM chunks").fetchone()[0])

    def test_changed_review_revokes_approval(self) -> None:
        self.assertEqual(self.importer()[0], 0)
        self.assertEqual(self.cli(["--library", "wire", "--ack-review", ID_A])[0], 0)
        self.assertTrue(self.app().search("faithful", 5, "bm25")["results"])

        # A re-import (here with a new block list, so a different review file) drops it back.
        toml = self.root / "privacy.toml"
        toml.write_text('block = ["Timothy"]\n')
        code, _out, err = self.importer(["--redo", "--privacy", str(toml)])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.app().search("faithful", 5, "bm25")["results"], [])
        # Approval runs under the import's privacy config (W3-PRIV-WIRE fix-up).
        self.assertEqual(self.cli(["--library", "wire", "--ack-review", ID_A, "--privacy", str(toml)])[0], 0)
        self.assertTrue(self.app().search("faithful", 5, "bm25")["results"])

        # A review file edited after import cannot be approved.
        with self.review_file(ID_B).open("a") as handle:
            handle.write("{}\n")
        code, _out, err = self.cli(["--library", "wire", "--ack-review", ID_B])
        self.assertEqual(code, 1)
        self.assertIn("changed since import", err)
        self.assertIsNone(self.app().sermon(ID_B))

    def test_ack_needs_a_known_video_and_no_channel(self) -> None:
        self.assertEqual(self.importer()[0], 0)
        code, _out, err = self.cli(["--library", "wire", "--ack-review", "nosuchvideo"])
        self.assertEqual(code, 1)
        self.assertIn("not imported", err)
        code, _out, err = self.cli([CHANNEL, "--library", "wire", "--ack-review", ID_A])
        self.assertEqual(code, 2)

    def test_old_library_without_gate_columns_fails_closed(self) -> None:
        self.assertEqual(self.importer()[0], 0)
        import sqlite3

        connection = sqlite3.connect(self.index)
        connection.execute("ALTER TABLE videos RENAME COLUMN approved_sha256 TO approved_old")
        connection.commit()
        connection.close()
        connection = open_readonly(self.index)
        self.addCleanup(connection.close)
        self.assertEqual(Searcher(connection).bm25("faithful", 5), [])

    def test_review_files_never_go_inside_the_repo(self) -> None:
        with self.assertRaises(RuntimeError):
            write_private_review([], REPO_ROOT / "review" / "x.review.jsonl")
        self.assertFalse((REPO_ROOT / "review" / "x.review.jsonl").exists())

    def test_wesley_style_index_is_never_gated(self) -> None:
        import sqlite3

        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE chunks (chunk_id TEXT, text TEXT)")
        connection.execute("INSERT INTO chunks VALUES ('a', 'b')")
        self.assertEqual(hidden_rowids(connection), set())


class PrivacyConfigTests(Base):
    def test_privacy_flag_and_environment_both_apply(self) -> None:
        toml = self.root / "privacy.toml"
        toml.write_text('block = ["Faithful"]\n')
        self.assertEqual(self.importer(["--privacy", str(toml)])[0], 0)
        connection = open_readonly(self.index)
        self.assertNotIn("faithful", connection.execute("SELECT group_concat(text) FROM chunks").fetchone()[0].lower())
        connection.close()
        self.index.unlink()
        with patch.dict(os.environ, {"PREACHED_PRIVACY": str(toml)}):
            self.assertEqual(self.importer()[0], 0)
        connection = open_readonly(self.index)
        self.assertNotIn("faithful", connection.execute("SELECT group_concat(text) FROM chunks").fetchone()[0].lower())
        connection.close()

    def test_drop_window_uses_the_video_id(self) -> None:
        toml = self.root / "privacy.toml"
        toml.write_text(f'[[drop]]\nsource = "{ID_A}"\nstart = 0.0\nend = 10.0\n')
        self.assertEqual(self.importer(["--privacy", str(toml)])[0], 0)
        connection = open_readonly(self.index)
        first = connection.execute("SELECT min(start_s) FROM chunks WHERE video_id = ?", (ID_A,)).fetchone()[0]
        other = connection.execute("SELECT min(start_s) FROM chunks WHERE video_id = ?", (ID_B,)).fetchone()[0]
        connection.close()
        self.assertGreaterEqual(first, 10.0)
        self.assertEqual(other, 0.0)

    def test_bad_privacy_settings_exit_2(self) -> None:
        toml = self.root / "bad.toml"
        toml.write_text('flagged_audio = "loud"\n')
        code, _out, err = self.importer(["--privacy", str(toml)])
        self.assertEqual(code, 2)
        self.assertIn("flagged_audio must be one of play, none", err)
        self.assertEqual(self.importer(["--privacy", str(self.root / "missing.toml")])[0], 2)

    def test_church_audio_policy_cannot_be_chosen(self) -> None:
        """Patrick chose none: play and shifted are refused from every config source, before any download."""
        for value in ("shifted", "play"):
            toml = self.root / f"{value}.toml"
            toml.write_text(f'flagged_audio = "{value}"\n')
            code, _out, err = self.importer(["--privacy", str(toml)])
            self.assertEqual(code, 2, err)
            self.assertRegex(err, "Patrick chose 'none'|must be one of play, none")
            with patch.dict(os.environ, {"PREACHED_FLAGGED_AUDIO": value}):
                code, _out, err = self.importer()
            self.assertEqual(code, 2, err)
            self.assertRegex(err, "Patrick chose 'none'|must be one of play, none")
        # There is no command-line flag any more (argparse exits 2).
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as ctx:
            self.importer(["--flagged-audio", "shifted"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertFalse(self.index.exists())
        # "none" is still accepted, so an existing config keeps working.
        toml = self.root / "none.toml"
        toml.write_text('flagged_audio = "none"\n')
        self.assertEqual(self.importer(["--privacy", str(toml)])[0], 0)


class FlaggedAudioTests(Base):
    def test_policy_function(self) -> None:
        self.assertIs(flagged_play(10.0, 55.0, None, "none"), True)
        self.assertIs(flagged_play(10.0, 55.0, 20.0, "play"), True)
        self.assertIs(flagged_play(10.0, 55.0, 20.0, "none"), False)
        # The 'shifted' policy was deleted (round 6): it is not a known value any more.
        with self.assertRaises(ValueError):
            flagged_play(10.0, 55.0, 20.0, "shifted")
        with self.assertRaises(ValueError):
            check_flagged_audio("shifted")
        for bad in ("", "Play", "mute", None):
            with self.assertRaises(ValueError):
                check_flagged_audio(bad)
        with self.assertRaises(ValueError):
            flagged_play(0.0, 1.0, 0.5, "mute")
        with self.assertRaises(ValueError):
            Config.from_dict({"flagged_audio": "mute"})
        self.assertEqual(resolve_flagged_audio(), "none")
        self.assertEqual(resolve_flagged_audio("none"), "none")
        with patch.dict(os.environ, {"PREACHED_FLAGGED_AUDIO": "none"}):
            self.assertEqual(resolve_flagged_audio("none"), "none")
        # Patrick chose none for church libraries: nothing else is selectable.
        for value in ("play", "shifted"):
            with self.assertRaisesRegex(ValueError, "Patrick chose 'none'|must be one of play, none"):
                resolve_flagged_audio(value)
            with patch.dict(os.environ, {"PREACHED_FLAGGED_AUDIO": value}), self.assertRaises(ValueError):
                resolve_flagged_audio()
            with self.assertRaises(ValueError):
                Config.from_dict({"flagged_audio": value})
        with patch.dict(os.environ, {"PREACHED_FLAGGED_AUDIO": "bogus"}), self.assertRaises(ValueError):
            resolve_flagged_audio()

    def hit(self, flag_end_s: float | None) -> Hit:
        return Hit(
            rowid=1, score=1.0, chunk_id="c", sermon_id=ID_A, sermon_title="t", text="x [name]",
            start_s=100.0, end_s=145.0, source_url=None, scripture=None,
            audio_url=watch_url(ID_A, 100.0), text_source="asr", video_id=ID_A, flag_end_s=flag_end_s,
        )

    def test_api_json_for_both_values_and_unflagged_chunks(self) -> None:
        plain = hit_dict(self.hit(None), "none")
        self.assertEqual(plain["audio_url"], f"https://www.youtube.com/watch?v={ID_A}&t=99s")
        self.assertNotIn("audio_withheld", plain)
        self.assertNotIn("play_from_s", plain)
        flagged = self.hit(112.0)
        play = hit_dict(flagged, "play")
        self.assertEqual(play["audio_url"], plain["audio_url"])
        self.assertNotIn("play_from_s", play)
        self.assertEqual((play["start_s"], play["end_s"]), (100.0, 145.0))
        none = hit_dict(flagged, "none")
        self.assertIsNone(none["audio_url"])
        self.assertTrue(none["audio_withheld"])
        self.assertEqual((none["start_s"], none["end_s"]), (None, None))
        with self.assertRaises(ValueError):
            hit_dict(flagged, "shifted")

    def test_watch_url(self) -> None:
        base = f"https://www.youtube.com/watch?v={ID_A}"
        self.assertEqual(watch_url(ID_A, 100.0), f"{base}&t=99s")
        self.assertEqual(watch_url(ID_A, 100.0, end_s=145.0, flag_end_s=112.0, policy="play"), f"{base}&t=99s")
        self.assertIsNone(watch_url(ID_A, 100.0, end_s=145.0, flag_end_s=112.0, policy="none"))
        with self.assertRaises(ValueError):
            watch_url(ID_A, 100.0, end_s=145.0, flag_end_s=112.0, policy="mute")

    def served(self, policy: str | None) -> dict[str, dict]:
        """The chunk with the opening names ("soup") and a late clear chunk ("zephyrgrace")."""
        if not self.index.exists():
            self.assertEqual(self.importer()[0], 0)
            self.assertEqual(self.cli(["--library", "wire", "--ack-review", ID_A])[0], 0)
        app = self.app(flagged_audio=policy)
        found = {}
        for key in ("soup", "zephyrgrace"):
            results = [r for r in app.search(key, 20, "bm25")["results"] if key in r["text"]]
            self.assertEqual(len(results), 1, [(r['chunk_id'], r['text'][:50]) for r in results])
            found[key] = results[0]
        return found

    def test_served_results_follow_the_policy(self) -> None:
        default = self.served(None)  # no flag, no env: none
        self.assertIn("[name]", default["soup"]["text"])
        self.assertIsNone(default["soup"]["audio_url"])
        self.assertTrue(default["soup"]["audio_withheld"])
        clear = default["zephyrgrace"]
        self.assertNotIn("[name]", clear["text"])
        self.assertTrue(clear["audio_url"].startswith("https://www.youtube.com/watch?v="))
        self.assertIn("&t=", clear["audio_url"])  # its own timed link stays (Patrick's rule)
        self.assertIsNone(clear["source_url"])  # the 0:00 watch link goes: this sermon has a flagged passage
        self.assertNotIn("audio_withheld", clear)
        played = self.served("play")
        self.assertTrue(played["soup"]["audio_url"])
        self.assertNotIn("play_from_s", played["soup"])
        # play (tests only) keeps every link, including the sermon's source link.
        self.assertEqual({**played["zephyrgrace"], "source_url": None}, clear)

    def test_invalid_policy_is_rejected(self) -> None:
        self.assertEqual(self.importer()[0], 0)
        with self.assertRaises(ValueError):
            self.app(flagged_audio="loud")

    def test_query_cli_play_line(self) -> None:
        import sys

        sys.path.insert(0, str(REPO_ROOT / "search"))
        try:
            import query
        finally:
            sys.path.pop(0)
        flagged = replace(self.hit(112.0), audio_url="https://archive.org/download/x/y.mp3")
        self.assertIn("withheld", query.hit_play(flagged, "none"))
        self.assertIn("#t=99.25", query.hit_play(flagged, "play"))
        clear = replace(flagged, flag_end_s=None)
        self.assertIn("#t=99.25", query.hit_play(clear, "none"))


class AsrChunksTests(unittest.TestCase):
    """align/asr_chunks.py: redact only when a privacy config is in effect."""

    def setUp(self) -> None:
        import sys

        sys.path.insert(0, str(REPO_ROOT / "align"))
        self.addCleanup(sys.path.remove, str(REPO_ROOT / "align"))
        import asr_chunks

        self.module = asr_chunks
        words = transcript(OPENING_A)
        self.transcript = {
            "meta": {"id": "church-1", "title": "Soup with Gerald Fenwick"},
            "segments": [{"words": [[w.start, w.end, w.text] for w in words]}],
        }
        self.config = load_chunk_config()

    def test_no_config_leaves_everything_alone(self) -> None:
        rows = self.module.asr_chunks(self.transcript, self.config)
        self.assertIn("Fenwick", rows[0]["text"])
        self.assertNotIn("flag_end_s", rows[0])

    def test_config_redacts_text_title_and_keeps_timings(self) -> None:
        plain = self.module.asr_chunks(self.transcript, self.config)
        rows = self.module.asr_chunks(self.transcript, self.config, privacy=Config())
        self.assertEqual(len(rows), len(plain))
        for row, before in zip(rows, plain):
            self.assertEqual((row["start_s"], row["end_s"], row["word_start"], row["word_end"]), (before["start_s"], before["end_s"], before["word_start"], before["word_end"]))
        self.assertNotIn("Fenwick", rows[0]["text"])
        self.assertEqual(rows[0]["sermon_title"], "Soup with [name] [name]")
        self.assertGreater(rows[0]["flag_end_s"], 0)
        self.assertIsNone(rows[-1]["flag_end_s"])

    def test_wesley_is_never_redacted(self) -> None:
        with patch.dict(os.environ, {"PREACHED_PRIVACY": str(REPO_ROOT / "privacy.example.toml")}):
            self.assertIsNone(self.module.privacy_for("wesley", None))
            self.assertIsNotNone(self.module.privacy_for("gaston-test", None))
        with self.assertRaises(SystemExit):
            self.module.privacy_for("wesley", Path("privacy.toml"))


if __name__ == "__main__":
    unittest.main()
