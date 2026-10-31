"""YouTube import: listing fixtures, dry-run, resume, sermon span, chunks, schema.

No network. Listings come from tests/fixtures. Transcription and download are fakes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.server import STATIC_DIR, STALE_NOTE, App, make_server
from preached.corpus import load_chunk_config
from preached.models import MODELS
from preached.library import get_meta, is_your_church, mark_your_church
from preached.search import PREROLL_S as SEARCH_PREROLL_S
from preached.search import Searcher
from preached.store import connect, load_embeddings, open_readonly, stored_fingerprint
from preached.youtube.chunking import chunk_words
from preached.youtube.cli import main
from preached.youtube.fetch import download_audio, fetch_metadata, list_channel
from preached.youtube.library import MODEL_KEY, ensure_library
from preached.youtube.listing import (
    PREROLL_S,
    WATCH_HOSTS,
    BadChannelUrl,
    ChannelRefused,
    Video,
    assert_youtube_url,
    creative_commons,
    parse_listing,
    watch_url,
    youtube_watch_url,
)
from preached.youtube.privacy import redact
from preached.youtube.sermon import is_sung, load_windows, sermon_span, speech_runs, words_in_span
from preached.youtube.words import Word

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "youtube" / "channel.json"


def listing() -> list[Video]:
    return parse_listing(json.loads(FIXTURE.read_text(encoding="utf-8")))


def unique_words(start: float, end: float, step: float = 0.5) -> list[Word]:
    """Distinct tokens so a long run is not mistaken for a repeated chorus."""
    words = []
    cursor = start
    index = 0
    while cursor < end:
        words.append(Word(cursor, cursor + min(0.3, step * 0.6), f"w{index}"))
        cursor += step
        index += 1
    return words


def speech_words(start: float, end: float, text: str, step: float = 0.5) -> list[Word]:
    words = []
    cursor = start
    piece = text.split()
    index = 0
    while cursor < end:
        token = piece[index % len(piece)]
        words.append(Word(cursor, cursor + min(0.3, step * 0.6), token))
        cursor += step
        index += 1
    return words


def embedder(titles: list[str], texts: list[str]) -> np.ndarray:
    matrix = np.zeros((len(texts), 4), dtype=np.float32)
    for index, _text in enumerate(texts):
        matrix[index, index % 4] = 1.0
    return matrix


def sample_words(start: float = 12.2) -> list[Word]:
    tokens = "zephyrgrace abides in the quiet heart today".split()
    words = []
    cursor = start
    for index, token in enumerate(tokens):
        text = token + "." if index == len(tokens) - 1 else token
        words.append(Word(cursor, cursor + 0.4, text))
        cursor += 0.5
    return words


class ListingTests(unittest.TestCase):
    def test_fixture_flattens_tabs_and_skips_live(self) -> None:
        videos = listing()
        self.assertEqual([video.id for video in videos], ["abcdefghijk", "bbbcccddd11", "shortvid001"])
        hope = videos[0]
        self.assertEqual(hope.title, "On Hope")
        self.assertEqual(hope.published, date(2024, 3, 15))
        self.assertEqual(hope.duration_s, 754)
        self.assertEqual(hope.url, "https://www.youtube.com/watch?v=abcdefghijk")
        faith = videos[1]
        self.assertEqual(faith.published, datetime.fromtimestamp(1705276800, timezone.utc).date())
        self.assertEqual(faith.url, "https://www.youtube.com/watch?v=bbbcccddd11")
        self.assertEqual(videos[2].published, date(2022, 1, 2))

    def test_video_id_is_exactly_eleven_characters(self) -> None:
        payload = {
            "title": "Example Lectures",
            "entries": [
                {"id": "../x", "title": "traversal"},
                {"id": "a.b", "title": "dotted"},
                {"id": "abc", "title": "short"},
                {"id": "A" * 12, "title": "long"},
                {"id": "BGoD6CIpLWQ", "title": "Are speeches public domain?", "duration": 322},
            ],
        }
        videos = parse_listing(payload)
        self.assertEqual([video.id for video in videos], ["BGoD6CIpLWQ"])

    def test_creative_commons_field(self) -> None:
        self.assertTrue(creative_commons("Creative Commons Attribution license (reuse allowed)"))
        self.assertFalse(creative_commons("Standard YouTube License"))
        self.assertFalse(creative_commons(None))

    def test_watch_url_uses_integer_seconds(self) -> None:
        self.assertEqual(watch_url("abcdefghijk"), "https://www.youtube.com/watch?v=abcdefghijk")
        # 12.8 - 0.75 = 12.05, then truncated to the whole second YouTube accepts.
        self.assertEqual(watch_url("abcdefghijk", 12.8), "https://www.youtube.com/watch?v=abcdefghijk&t=12s")
        # 12.2 used to seek at 12s. Pre-roll moves the play position to 11s.
        self.assertEqual(watch_url("abcdefghijk", 12.2), "https://www.youtube.com/watch?v=abcdefghijk&t=11s")
        self.assertEqual(watch_url("abcdefghijk", 0), "https://www.youtube.com/watch?v=abcdefghijk&t=0s")

    def test_watch_url_preroll_clamps_at_zero(self) -> None:
        self.assertEqual(watch_url("abcdefghijk", 0.5), "https://www.youtube.com/watch?v=abcdefghijk&t=0s")

    def test_watch_url_drops_non_finite_and_negative_and_caps(self) -> None:
        base = "https://www.youtube.com/watch?v=abcdefghijk"
        for bad in (float("inf"), float("-inf"), float("nan"), -1, -0.01):
            with self.subTest(start=bad):
                self.assertEqual(watch_url("abcdefghijk", bad), base)
        # int(1e300) is a huge integer. The seek stops at 24 h, or the sermon.
        self.assertEqual(watch_url("abcdefghijk", 1e300), base + "&t=86400s")
        self.assertEqual(watch_url("abcdefghijk", 1e300, duration_s=40), base + "&t=40s")
        self.assertEqual(watch_url("abcdefghijk", 100, duration_s=40), base + "&t=40s")
        self.assertEqual(watch_url("abcdefghijk", 12.2, duration_s=40), base + "&t=11s")
        self.assertEqual(watch_url("abcdefghijk", 1e300, duration_s=100_000), base + "&t=86400s")
        self.assertEqual(watch_url("abcdefghijk", 12.2, duration_s=float("inf")), base + "&t=11s")
        self.assertEqual(watch_url("abcdefghijk", 12.2, duration_s=float("nan")), base + "&t=11s")
        self.assertEqual(watch_url("abcdefghijk", 0), base + "&t=0s")

    def test_preroll_is_the_search_constant(self) -> None:
        self.assertIs(PREROLL_S, SEARCH_PREROLL_S)
        self.assertEqual(PREROLL_S, 0.75)
        self.assertEqual(WATCH_HOSTS, frozenset({"youtube.com", "www.youtube.com", "m.youtube.com"}))

    def test_youtube_watch_url_accepts_stored_links(self) -> None:
        stored = "https://www.youtube.com/watch?v=abcdefghijk&t=11s"
        self.assertEqual(youtube_watch_url(stored), stored)
        apex = "https://youtube.com/watch?v=abcdefghijk&t=0s"
        self.assertEqual(youtube_watch_url(apex), "https://www.youtube.com/watch?v=abcdefghijk&t=0s")
        mobile = "https://m.youtube.com/watch?v=abcdefghijk&t=3s"
        self.assertEqual(youtube_watch_url(mobile), "https://www.youtube.com/watch?v=abcdefghijk&t=3s")
        mixed = "https://WWW.YouTube.com/watch?v=abc_def-01X&t=11s"
        self.assertEqual(youtube_watch_url(mixed), "https://www.youtube.com/watch?v=abc_def-01X&t=11s")
        explicit_port = "https://www.youtube.com:443/watch?v=abcdefghijk&t=11s"
        self.assertEqual(youtube_watch_url(explicit_port), stored)
        kept_hash = "https://www.youtube.com/watch?v=abcdefghijk&t=11s#keep"
        self.assertEqual(youtube_watch_url(kept_hash), stored)

    def test_youtube_watch_url_rebuilds_validated_parts_only(self) -> None:
        base = "https://www.youtube.com/watch?v=abcdefghijk"
        hostile_t = base + "&t=javascript:alert(1)"
        self.assertEqual(youtube_watch_url(hostile_t), base)
        self.assertNotIn("javascript", youtube_watch_url(hostile_t) or "")
        extra = base + "&t=11s&redirect=https://evil.example&feature=share"
        self.assertEqual(youtube_watch_url(extra), base + "&t=11s")
        self.assertNotIn("redirect", youtube_watch_url(extra) or "")
        self.assertEqual(youtube_watch_url(base + "&t=011s"), base + "&t=11s")
        self.assertEqual(youtube_watch_url(base + "&t=86400s"), base + "&t=86400s")
        self.assertEqual(youtube_watch_url(base + "&t=86401s"), base)
        self.assertEqual(youtube_watch_url(base + "&t=11s&t=12s"), base)
        self.assertEqual(youtube_watch_url(base + "&t="), base)

    def test_youtube_watch_url_rejects_hostile_and_other_shapes(self) -> None:
        rejected = (
            "https://www.youtube.com.evil.com/watch?v=abcdefghijk",
            "javascript:alert(1)",
            "javascript:https://www.youtube.com/watch?v=abcdefghijk",
            "http://www.youtube.com/watch?v=abcdefghijk",
            "https://evil.com@www.youtube.com/watch?v=abcdefghijk",
            "https://user:pw@www.youtube.com/watch?v=abcdefghijk",
            "https://youtu.be/abcdefghijk",
            "https://www.youtube.com/embed/abcdefghijk",
            "https://www.youtube.com/watch?v=short",
            "https://www.youtube.com/watch?v=abcdefghijkl",
            "https://www.youtube.com/watch?v=abcdefghijk&v=zzzzzzzzzzz",
            "https://www.youtube.com/watch?v=abcdefghijk&v=",
            "https://www.youtube.com/watch?v=&v=abcdefghijk",
            "https://www.youtube.com/watch?v=abcdefghijk&v",
            "https://www.youtube.com:8443/watch?v=abcdefghijk",
            "https://www.youtube.com:abc/watch?v=abcdefghijk",
            "https://www.youtube.com:99999/watch?v=abcdefghijk",
            "https://[::1]/watch?v=abcdefghijk",
            "https://[gggg::1]/watch?v=abcdefghijk",
            "https://www.youtube.com./watch?v=abcdefghijk",
            "https://www.youtube.com/watch/?v=abcdefghijk",
            "https://archive.org/download/x/y.mp3",
            "https://www.youtube.com/watch?v=abcdefghijk&t=11s\x1b",
            None,
            "",
        )
        for url in rejected:
            with self.subTest(url=url):
                self.assertIsNone(youtube_watch_url(url))

    def test_stored_start_s_is_the_word_onset(self) -> None:
        """The chunk record keeps the first word. Only the watch URL is pre-rolled."""
        from preached.youtube.pipeline import _chunks_for

        video = Video(
            "samplevid01",
            "On Mercy",
            40,
            date(2024, 6, 2),
            "https://www.youtube.com/watch?v=samplevid01",
        )
        words = sample_words(12.2)
        records, _ = _chunks_for(video, words, {})
        self.assertEqual(records[0]["chunk_id"], "samplevid01-c0000")
        self.assertEqual(records[0]["start_s"], words[0].start)
        self.assertAlmostEqual(records[0]["start_s"], 12.2)
        self.assertEqual(
            records[0]["audio_url"],
            "https://www.youtube.com/watch?v=samplevid01&t=11s",
        )
        late, _ = _chunks_for(video, sample_words(100), {})
        self.assertAlmostEqual(late[0]["start_s"], 100)
        self.assertEqual(
            late[0]["audio_url"],
            "https://www.youtube.com/watch?v=samplevid01&t=40s",
        )

    def test_blocked_channel_name_is_refused(self) -> None:
        with self.assertRaises(ChannelRefused):
            parse_listing({"title": "Gaston Community Church", "entries": []})


class SermonTests(unittest.TestCase):
    def test_longest_speech_beats_a_longer_chorus(self) -> None:
        announcement = speech_words(0, 10, "welcome friends to this morning gathering")
        chorus = speech_words(30, 500, "hallelujah")
        sermon = unique_words(520, 800)
        prayer = unique_words(820, 860)
        words = announcement + chorus + sermon + prayer
        self.assertTrue(is_sung(chorus))
        self.assertFalse(is_sung(sermon))
        start, end = sermon_span(words)
        self.assertAlmostEqual(start, sermon[0].start)
        self.assertAlmostEqual(end, sermon[-1].end)
        kept = words_in_span(words, start, end)
        self.assertEqual(kept[0].text, sermon[0].text)
        self.assertNotIn("hallelujah", [word.text for word in kept])

    def test_repeated_line_is_singing(self) -> None:
        line = speech_words(0, 180, "alpha bravo charlie delta echo", step=0.4)
        self.assertTrue(is_sung(line))

    def test_fallback_when_every_run_is_sung(self) -> None:
        chorus = speech_words(0, 90, "hallelujah")
        start, end = sermon_span(chorus)
        self.assertAlmostEqual(start, chorus[0].start)
        self.assertAlmostEqual(end, chorus[-1].end)

    def test_gap_of_fifteen_seconds_stays_one_run(self) -> None:
        self.assertEqual(len(speech_runs([Word(0, 1, "alpha"), Word(16, 17, "beta")])), 1)
        self.assertEqual(len(speech_runs([Word(0, 1, "alpha"), Word(16.01, 17, "beta")])), 2)

    def test_override_replaces_the_rule(self) -> None:
        words = speech_words(0, 40, "grace faith hope")
        self.assertEqual(sermon_span(words, (10, 18)), (10, 18))
        kept = words_in_span(words, 10, 18)
        self.assertTrue(all(10 <= word.start < 18 for word in kept))

    def test_toml_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "windows.toml"
            path.write_text("[videos.abcdefghijk]\nstart_s = 3\nend_s = 9\n", encoding="utf-8")
            self.assertEqual(load_windows(path), {"abcdefghijk": (3.0, 9.0)})
            self.assertEqual(load_windows(None), {})


class ChunkTests(unittest.TestCase):
    def test_chunks_carry_start_and_end_seconds(self) -> None:
        config = load_chunk_config()
        words = []
        cursor = 5.0
        for index in range(300):
            token = f"word{index}." if index % 12 == 11 else f"word{index}"
            words.append(Word(cursor, cursor + 0.3, token))
            cursor += 0.4
        chunks = chunk_words(words, config)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["start_s"], words[0].start)
        self.assertEqual(chunks[-1]["end_s"], words[-1].end)
        starts = [chunk["start_s"] for chunk in chunks]
        self.assertEqual(starts, sorted(starts))
        overlapped = False
        for previous, nxt in zip(chunks, chunks[1:]):
            self.assertEqual(previous["start_s"], words[previous["word_start"]].start)
            self.assertEqual(previous["end_s"], words[previous["word_end"] - 1].end)
            self.assertLess(previous["start_s"], previous["end_s"])
            self.assertGreater(previous["word_end"], previous["word_start"])
            if nxt["word_start"] < previous["word_end"]:
                overlapped = True
        self.assertTrue(overlapped)


class ImportTests(unittest.TestCase):
    def setUp(self) -> None:
        # The import refuses to run without a privacy config (fail closed);
        # an empty one keeps the built-in name rules, which these samples pass.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        toml = Path(tmp.name) / "privacy.toml"
        toml.write_text("# no library-specific names\n")
        env = {k: v for k, v in os.environ.items() if k != "PREACHED_FLAGGED_AUDIO"}
        env["PREACHED_PRIVACY"] = str(toml)
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, argv: list[str], tmp: Path, **kwargs):
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv, index_dir=tmp, audio_root=tmp / "audio", **kwargs)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_dry_run_lists_id_title_date_duration(self) -> None:
        videos = listing()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, out, _err = self._run(
                [
                    "https://www.youtube.com/channel/UCexample",
                    "--library",
                    "sample",
                    "--since",
                    "2024-02-01",
                    "--limit",
                    "1",
                    "--dry-run",
                ],
                root,
                lister=lambda _url: videos,
                downloader=self._boom,
                transcriber=self._boom,
                coverage=lambda *_a, **_k: [],
                metadata=self._boom,
            )
            self.assertEqual(code, 0)
            self.assertEqual(out, "abcdefghijk\tOn Hope\t2024-03-15\t754\n")
            self.assertFalse((root / "sample.sqlite").exists())

    def test_dry_run_strips_tabs_in_titles(self) -> None:
        videos = listing()
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _err = self._run(
                ["https://www.youtube.com/channel/UCexample", "--library", "sample", "--dry-run"],
                Path(tmp),
                lister=lambda _url: videos,
            )
            self.assertEqual(code, 0)
            lines = out.splitlines()
            self.assertEqual(len(lines), 3)
            faith = lines[1].split("\t")
            self.assertEqual(faith[0], "bbbcccddd11")
            self.assertEqual(faith[1], "On Faith and love")
            self.assertEqual(faith[3], "1800")

    def test_refuses_blocked_channel_without_listing(self) -> None:
        def lister(_url):
            raise AssertionError("lister should not run")

        with tempfile.TemporaryDirectory() as tmp:
            code, _out, err = self._run(
                [
                    "https://www.youtube.com/@gastoncommunitychurch6944/videos",
                    "--library",
                    "sample",
                    "--dry-run",
                ],
                Path(tmp),
                lister=lister,
            )
            self.assertEqual(code, 2)
            self.assertIn("permission", err)

    def test_resume_skips_ok_and_continues_after_failure(self) -> None:
        videos = [
            Video("videookkk1", "First", 30, date(2024, 1, 2), "https://www.youtube.com/watch?v=videookkk1"),
            Video("videofail1", "Second", 30, date(2024, 1, 3), "https://www.youtube.com/watch?v=videofail1"),
            Video("videoalso1", "Third", 30, date(2024, 1, 4), "https://www.youtube.com/watch?v=videoalso1"),
        ]
        downloaded: list[str] = []
        transcribed: list[str] = []
        failures = {"videofail1": 0}

        def downloader(video, dest: Path):
            downloaded.append(video.id)
            dest.mkdir(parents=True, exist_ok=True)
            path = dest / f"{video.id}.m4a"
            path.write_bytes(b"fake")
            return path

        def transcriber(path: Path):
            transcribed.append(path.name)
            if path.name.startswith("videofail1") and failures["videofail1"] == 0:
                failures["videofail1"] += 1
                raise RuntimeError("decoder blew up")
            return sample_words()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            argv = ["https://www.youtube.com/channel/UCexample", "--library", "sample"]
            code, _out, err = self._run(
                argv,
                root,
                lister=lambda _url: videos,
                downloader=downloader,
                transcriber=transcriber,
                coverage=lambda *_a, **_k: [],
                metadata=lambda _video: {},
                embedder=embedder,
            )
            self.assertEqual(code, 1, err)
            self.assertIn("videofail1", err)
            self.assertEqual(downloaded, ["videookkk1", "videofail1", "videoalso1"])
            connection = open_readonly(root / "sample.sqlite")
            try:
                ok = {
                    row[0]
                    for row in connection.execute("SELECT video_id FROM videos WHERE status = 'ok'")
                }
                failed = connection.execute(
                    "SELECT status FROM videos WHERE video_id = 'videofail1'"
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(ok, {"videookkk1", "videoalso1"})
            self.assertEqual(failed[0], "error")

            downloaded.clear()
            transcribed.clear()
            code, _out, err = self._run(
                argv,
                root,
                lister=lambda _url: videos,
                downloader=downloader,
                transcriber=transcriber,
                coverage=lambda *_a, **_k: [],
                metadata=lambda _video: {},
                embedder=embedder,
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(downloaded, ["videofail1"])
            self.assertEqual(transcribed, ["videofail1.m4a"])

    def test_success_deletes_the_returned_audio_file(self) -> None:
        inside = Video("BGoD6CIpLWQ", "Talk", 40, date(2024, 6, 2), "https://www.youtube.com/watch?v=BGoD6CIpLWQ")
        escaped = Video("abcdefghijk", "Other", 40, date(2024, 6, 3), "https://www.youtube.com/watch?v=abcdefghijk")
        linked = Video("bbbcccddd11", "Link", 40, date(2024, 6, 4), "https://www.youtube.com/watch?v=bbbcccddd11")

        def downloader(video, dest: Path):
            dest.mkdir(parents=True, exist_ok=True)
            if video.id == escaped.id:
                path = dest / ".." / ".." / "escaped.m4a"
                path.write_bytes(b"nope")
                return path
            if video.id == linked.id:
                target = dest.parent.parent / "secret.m4a"
                target.write_bytes(b"secret")
                link = dest / "linked.m4a"
                link.symlink_to(target)
                return link
            path = dest / f"{video.id}.m4a"
            path.write_bytes(b"audio")
            (dest / f"{video.id}.part").write_bytes(b"part")
            return path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, _out, err = self._run(
                ["https://www.youtube.com/channel/UCexample", "--library", "sample"],
                root,
                lister=lambda _url: [inside, escaped, linked],
                downloader=downloader,
                transcriber=lambda _path: sample_words(),
                coverage=lambda *_a, **_k: [],
                metadata=lambda _video: {},
                embedder=embedder,
            )
            self.assertEqual(code, 0, err)
            audio = root / "audio" / "sample"
            self.assertFalse((audio / f"{inside.id}.m4a").exists())
            self.assertTrue((audio / f"{inside.id}.part").is_file())
            self.assertEqual((root / "escaped.m4a").read_bytes(), b"nope")
            self.assertTrue((audio / "linked.m4a").is_symlink())
            self.assertEqual((root / "secret.m4a").read_bytes(), b"secret")

    def test_failed_import_keeps_the_audio_file(self) -> None:
        video = Video("audiofail01", "Talk", 40, date(2024, 6, 2), "https://www.youtube.com/watch?v=audiofail01")

        def downloader(_video, dest: Path):
            dest.mkdir(parents=True, exist_ok=True)
            path = dest / f"{video.id}.m4a"
            path.write_bytes(b"audio")
            return path

        def transcriber(_path):
            raise RuntimeError("decoder blew up")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, _out, err = self._run(
                ["https://www.youtube.com/channel/UCexample", "--library", "sample"],
                root,
                lister=lambda _url: [video],
                downloader=downloader,
                transcriber=transcriber,
                coverage=lambda *_a, **_k: [],
                metadata=lambda _video: {},
                embedder=embedder,
            )
            self.assertEqual(code, 1, err)
            self.assertTrue((root / "audio" / "sample" / f"{video.id}.m4a").is_file())
            connection = open_readonly(root / "sample.sqlite")
            try:
                status = connection.execute(
                    "SELECT status FROM videos WHERE video_id = ?",
                    (video.id,),
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(status[0], "error")

    def test_keep_audio_flag_retains_the_file(self) -> None:
        video = Video("audiokeep01", "Talk", 40, date(2024, 6, 2), "https://www.youtube.com/watch?v=audiokeep01")

        def downloader(_video, dest: Path):
            dest.mkdir(parents=True, exist_ok=True)
            path = dest / f"{video.id}.m4a"
            path.write_bytes(b"audio")
            return path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, _out, err = self._run(
                ["https://www.youtube.com/channel/UCexample", "--library", "sample", "--keep-audio"],
                root,
                lister=lambda _url: [video],
                downloader=downloader,
                transcriber=lambda _path: sample_words(),
                coverage=lambda *_a, **_k: [],
                metadata=lambda _video: {},
                embedder=embedder,
            )
            self.assertEqual(code, 0, err)
            saved = root / "audio" / "sample" / f"{video.id}.m4a"
            self.assertEqual(saved.read_bytes(), b"audio")

    def test_require_cc_skips_without_transcribing(self) -> None:
        video = Video("cccheck0001", "Talk", 40, date(2024, 5, 1), "https://www.youtube.com/watch?v=cccheck0001")
        seen = {"meta": 0, "audio": 0}

        def metadata(_video):
            seen["meta"] += 1
            return {"license": "Standard YouTube License", "upload_date": "20240501", "uploader": "A Speaker"}

        def downloader(_video, _dest):
            seen["audio"] += 1
            raise AssertionError("downloaded")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            argv = [
                "https://www.youtube.com/watch?v=cccheck0001",
                "--library",
                "sample",
                "--require-cc",
            ]
            code, _out, err = self._run(
                argv,
                root,
                lister=lambda _url: [video],
                metadata=metadata,
                downloader=downloader,
                transcriber=self._boom,
                coverage=lambda *_a, **_k: [],
            )
            self.assertEqual(code, 0, err)
            self.assertIn("not Creative Commons", err)
            self.assertEqual(seen, {"meta": 1, "audio": 0})
            code, _out, err = self._run(
                argv,
                root,
                lister=lambda _url: [video],
                metadata=metadata,
                downloader=downloader,
                transcriber=self._boom,
                coverage=lambda *_a, **_k: [],
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(seen["meta"], 1)

    def test_schema_matches_the_search_server(self) -> None:
        video = Video("samplevid01", "On Mercy", 40, date(2024, 6, 2), "https://www.youtube.com/watch?v=samplevid01")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, _out, err = self._run(
                ["https://www.youtube.com/watch?v=samplevid01", "--library", "sample"],
                root,
                lister=lambda _url: [video],
                metadata=lambda _video: {
                    "license": "Creative Commons Attribution license (reuse allowed)",
                    "upload_date": "20240602",
                    "title": "On Mercy",
                    "uploader": "A Speaker",
                    "duration": 40,
                },
                downloader=lambda _video, dest: dest / "samplevid01.m4a",
                transcriber=lambda _path: sample_words(12.2),
                coverage=lambda *_a, **_k: [],
                embedder=embedder,
            )
            self.assertEqual(code, 0, err)
            code, _out, err = self._run(["--library", "sample", "--ack-review", "samplevid01"], root)
            self.assertEqual(code, 0, err)
            path = root / "sample.sqlite"
            connection = open_readonly(path, check_same_thread=False)
            try:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(chunks)")}
                for name in (
                    "start_s",
                    "end_s",
                    "audio_url",
                    "reader",
                    "text_source",
                    "video_id",
                    "title",
                    "published",
                ):
                    self.assertIn(name, columns)
                stored = connection.execute(
                    "SELECT video_id, title, published, reader, text_source FROM chunks"
                ).fetchone()
                self.assertEqual(stored["video_id"], "samplevid01")
                self.assertEqual(stored["title"], "On Mercy")
                self.assertEqual(stored["published"], "2024-06-02")
                self.assertIsNone(stored["reader"])
                self.assertEqual(stored["text_source"], "asr")
                _rowids, matrix = load_embeddings(connection, MODEL_KEY)
                self.assertEqual(matrix.dtype, np.float32)
                self.assertEqual(matrix.ndim, 2)
                self.assertAlmostEqual(float(np.linalg.norm(matrix[0])), 1.0, places=5)
                self.assertEqual(
                    stored_fingerprint(connection, MODEL_KEY),
                    MODELS[MODEL_KEY].fingerprint(),
                )
                Searcher(connection, model=MODEL_KEY)
                app = App(
                    connection=connection,
                    searcher=Searcher(connection),
                    encode=None,
                    fallback_note=None,
                    model_name=None,
                    hosts={"127.0.0.1", "localhost"},
                    static_dir=STATIC_DIR,
                    library="sample",
                )
                payload = app.search("zephyrgrace", 5, "bm25")
                self.assertGreaterEqual(len(payload["results"]), 1)
                hit = payload["results"][0]
                self.assertIn("zephyrgrace", hit["text"])
                self.assertAlmostEqual(hit["start_s"], 12.2, places=5)
                self.assertGreater(hit["end_s"], hit["start_s"])
                self.assertEqual(hit["audio_url"], "https://www.youtube.com/watch?v=samplevid01&t=11s")
                self.assertIsNone(hit["reader"])
                self.assertEqual(hit["text_source"], "asr")
                self.assertEqual(hit["sermon_title"], "On Mercy")

                server = make_server(app, "127.0.0.1", 0)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                port = server.server_address[1]
                try:
                    status, body = self._get(port, "/api/search?q=zephyrgrace&library=sample&mode=bm25")
                    self.assertEqual(status, 200)
                    remote = json.loads(body)["results"][0]
                    self.assertEqual(remote["audio_url"], hit["audio_url"])
                    self.assertEqual(remote["text_source"], "asr")
                    status, body = self._get(port, "/api/search?q=zephyrgrace&library=wesley&mode=bm25")
                    self.assertEqual(status, 400)
                    self.assertIn("library must be sample", json.loads(body)["error"])
                finally:
                    server.shutdown()
                    server.server_close()
            finally:
                connection.close()

    def test_server_reloads_youtube_library_and_falls_back(self) -> None:
        """A YouTube library is served, then reloaded, then served as BM25 when vectors go away."""
        video = Video(
            "samplevid02",
            "On Mercy",
            40,
            date(2024, 6, 2),
            "https://www.youtube.com/watch?v=samplevid02",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, _out, err = self._run(
                ["https://www.youtube.com/watch?v=samplevid02", "--library", "sample"],
                root,
                lister=lambda _url: [video],
                metadata=lambda _video: {
                    "license": "Creative Commons Attribution license (reuse allowed)",
                    "upload_date": "20240602",
                    "title": "On Mercy",
                    "uploader": "A Speaker",
                    "duration": 40,
                },
                downloader=lambda _video, dest: dest / "samplevid02.m4a",
                transcriber=lambda _path: sample_words(12.2),
                coverage=lambda *_a, **_k: [],
                embedder=embedder,
            )
            self.assertEqual(code, 0, err)
            # #12's publish gate: an imported sermon is served only once approved.
            code, _out, err = self._run(["--library", "sample", "--ack-review", "samplevid02"], root)
            self.assertEqual(code, 0, err)
            path = root / "sample.sqlite"

            readonly = open_readonly(path, check_same_thread=False)
            try:
                served = App(
                    connection=readonly,
                    searcher=Searcher(readonly),
                    encode=None,
                    fallback_note=None,
                    model_name=None,
                    hosts={"127.0.0.1", "localhost"},
                    static_dir=STATIC_DIR,
                    library="sample",
                )
                server = make_server(served, "127.0.0.1", 0)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                port = server.server_address[1]
                try:
                    status, body = self._get(port, "/api/search?q=zephyrgrace&library=sample&mode=bm25")
                    self.assertEqual(status, 200)
                    hit = json.loads(body)["results"][0]
                    self.assertEqual(hit["audio_url"], "https://www.youtube.com/watch?v=samplevid02&t=11s")
                    self.assertEqual(hit["text_source"], "asr")
                    self.assertEqual(hit["sermon_id"], "samplevid02")
                    self.assertIsNone(hit["reader"])
                    status, health_body = self._get(port, "/healthz")
                    self.assertEqual(status, 200)
                    health = json.loads(health_body)
                    self.assertEqual(health["library"], "sample")
                    self.assertIn("backend", health)
                    self.assertIsNone(health["backend"])
                finally:
                    server.shutdown()
                    server.server_close()
            finally:
                readonly.close()

            connection = connect(path)
            try:
                connection.execute(
                    "INSERT INTO meta (key, value) VALUES ('chunks_sha256', 'aaa') "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
                )
                connection.commit()

                def encode(_query: str) -> np.ndarray:
                    return np.ones(4, dtype=np.float32)

                encode.backend = "onnx"
                app = App(
                    connection=connection,
                    searcher=Searcher(connection, model=MODEL_KEY),
                    encode=encode,
                    fallback_note=None,
                    model_name=MODEL_KEY,
                    hosts={"127.0.0.1"},
                    static_dir=STATIC_DIR,
                    backend="onnx",
                    library="sample",
                )
                first = app.search("zephyrgrace", 5, "dense")
                self.assertEqual(first["mode"], "dense")
                self.assertEqual(first["note"], None)
                self.assertEqual(
                    first["results"][0]["audio_url"],
                    "https://www.youtube.com/watch?v=samplevid02&t=11s",
                )
                self.assertEqual(first["results"][0]["text_source"], "asr")
                self.assertEqual(app.health()["backend"], "onnx")
                self.assertEqual(app.health()["library"], "sample")
                self.assertTrue(app.health()["dense"])

                connection.execute(
                    "UPDATE chunks SET text = ? WHERE sermon_id = ?",
                    ("A prayer for the whole church gathers here.", "samplevid02"),
                )
                connection.execute("UPDATE meta SET value = 'bbb' WHERE key = 'chunks_sha256'")
                connection.commit()
                second = app.search("prayer", 5, "bm25")
                self.assertTrue(any("prayer" in hit["text"] for hit in second["results"]))
                self.assertEqual(
                    second["results"][0]["audio_url"],
                    "https://www.youtube.com/watch?v=samplevid02&t=11s",
                )
                self.assertEqual(app.health()["backend"], "onnx")

                connection.execute("DELETE FROM embeddings")
                connection.execute("DELETE FROM meta WHERE key LIKE 'embeddings:%'")
                connection.commit()
                third = app.search("prayer", 5, "dense")
                self.assertEqual(third["mode"], "bm25")
                self.assertEqual(third["note"], STALE_NOTE)
                self.assertTrue(any("prayer" in hit["text"] for hit in third["results"]))
                self.assertEqual(
                    third["results"][0]["audio_url"],
                    "https://www.youtube.com/watch?v=samplevid02&t=11s",
                )
                health = app.health()
                self.assertFalse(health["dense"])
                self.assertTrue(health["fallback"])
                self.assertIsNone(health["backend"])
                self.assertIsNone(health["model"])
                self.assertEqual(health["library"], "sample")
            finally:
                connection.close()

    def test_dash_url_is_refused_before_subprocess(self) -> None:
        self._assert_url_refused("-https://www.youtube.com/watch?v=abcdefghijk")
        self._assert_url_refused("--version")

    def test_non_youtube_host_is_refused_before_subprocess(self) -> None:
        self._assert_url_refused("https://example.com/watch?v=abcdefghijk")
        self._assert_url_refused("http://www.youtube.com/watch?v=abcdefghijk")
        self._assert_url_refused("https://www.youtube.com.evil.com/watch?v=abcdefghijk")
        self._assert_url_refused("https://evil.com@www.youtube.com/watch?v=abcdefghijk")

    def test_youtube_hosts_are_accepted(self) -> None:
        for url in (
            "https://youtube.com/@channel/videos",
            "https://www.youtube.com/watch?v=BGoD6CIpLWQ",
            "https://m.youtube.com/watch?v=BGoD6CIpLWQ",
            "https://youtu.be/BGoD6CIpLWQ",
        ):
            assert_youtube_url(url)

    def test_missing_yt_dlp_names_the_youtube_extra(self) -> None:
        missing = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="/usr/bin/python: No module named yt_dlp\n",
        )
        url = "https://www.youtube.com/channel/UCexample"
        with patch("preached.youtube.fetch.subprocess.run", return_value=missing):
            with self.assertRaises(RuntimeError) as caught:
                list_channel(url)
        self.assertIn("--extra youtube", str(caught.exception))

    def test_yt_dlp_url_follows_double_dash(self) -> None:
        url = "https://www.youtube.com/channel/UCexample"
        listed = subprocess.CompletedProcess(args=[], returncode=0, stdout='{"entries":[]}', stderr="")
        with patch("preached.youtube.fetch.subprocess.run", return_value=listed) as run:
            self.assertEqual(list_channel(url), [])
        self._assert_yt_dlp_hardened(run.call_args.args[0], url)

        video = Video("BGoD6CIpLWQ", "Talk", 10, None, "https://www.youtube.com/watch?v=BGoD6CIpLWQ")
        meta = subprocess.CompletedProcess(args=[], returncode=0, stdout="{}", stderr="")
        with patch("preached.youtube.fetch.subprocess.run", return_value=meta) as run:
            self.assertEqual(fetch_metadata(video), {})
        self._assert_yt_dlp_hardened(run.call_args.args[0], video.watch_url())

        failed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp:
            with patch("preached.youtube.fetch.subprocess.run", return_value=failed) as run:
                with self.assertRaises(RuntimeError):
                    download_audio(video, Path(tmp))
        self._assert_yt_dlp_hardened(run.call_args.args[0], video.watch_url())

    def _assert_yt_dlp_hardened(self, command: list[str], url: str) -> None:
        """The four lock-down options sit before ``--`` and the URL."""
        self.assertEqual(command[:3], [sys.executable, "-m", "yt_dlp"])
        self.assertEqual(command[-2:], ["--", url])
        before = command[:-2]
        self.assertNotIn("--", before)
        for option in ("--ignore-config", "--no-plugin-dirs", "--no-remote-components"):
            self.assertIn(option, before)
        extractors = before.index("--use-extractors")
        self.assertEqual(before[extractors + 1], "youtube,youtube:tab")
        self.assertLess(extractors, len(before) - 1)

    def test_case_sensitive_sermon_id_on_the_fixture_library(self) -> None:
        video_id = "BGoD6CIpLWQ"
        video = Video(
            video_id,
            "Are speeches public domain?",
            40,
            date(2012, 8, 6),
            f"https://www.youtube.com/watch?v={video_id}",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, _out, err = self._run(
                [f"https://www.youtube.com/watch?v={video_id}", "--library", "sample"],
                root,
                lister=lambda _url: [video],
                metadata=lambda _video: {
                    "license": "Creative Commons Attribution license (reuse allowed)",
                    "upload_date": "20120806",
                    "title": video.title,
                    "uploader": "New Media Rights",
                    "duration": 40,
                },
                downloader=lambda _video, dest: dest / f"{video_id}.m4a",
                transcriber=lambda _path: sample_words(12.2),
                coverage=lambda *_a, **_k: [],
                embedder=embedder,
            )
            self.assertEqual(code, 0, err)
            code, _out, err = self._run(["--library", "sample", "--ack-review", video_id], root)
            self.assertEqual(code, 0, err)
            connection = open_readonly(root / "sample.sqlite", check_same_thread=False)
            try:
                app = App(
                    connection=connection,
                    searcher=Searcher(connection, model=MODEL_KEY),
                    encode=None,
                    fallback_note=None,
                    model_name=None,
                    hosts={"127.0.0.1", "localhost"},
                    static_dir=STATIC_DIR,
                    library="sample",
                )
                server = make_server(app, "127.0.0.1", 0)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                port = server.server_address[1]
                try:
                    status, body = self._get(port, f"/api/sermon/{video_id}")
                    self.assertEqual(status, 200, body)
                    meta = json.loads(body)
                    self.assertEqual(meta["sermon_id"], video_id)
                    self.assertEqual(meta["sermon_title"], video.title)
                    self.assertEqual(
                        meta["audio_url"],
                        f"https://www.youtube.com/watch?v={video_id}&t=11s",
                    )
                    status, body = self._get(port, f"/api/sermon/{video_id.lower()}")
                    self.assertEqual(status, 404)
                    self.assertEqual(json.loads(body)["error"], "not found")
                    for path in (
                        "/api/sermon/../pyproject.toml",
                        "/api/sermon/Wesley-001",
                        "/api/sermon/" + ("A" * 64),
                    ):
                        status, body = self._get(port, path)
                        self.assertEqual(status, 404, path)
                        self.assertNotIn(b"pyproject", body.lower())
                finally:
                    server.shutdown()
                    server.server_close()
            finally:
                connection.close()

    def _assert_url_refused(self, url: str) -> None:
        with patch("preached.youtube.fetch.subprocess.run") as run:
            with self.assertRaises(BadChannelUrl):
                list_channel(url)
            run.assert_not_called()
        called: list[str] = []

        def lister(got: str):
            called.append(got)
            raise AssertionError("lister should not run")

        argv = [url, "--library", "sample", "--dry-run"]
        if url.startswith("-"):
            argv = ["--library", "sample", "--dry-run", "--", url]
        with tempfile.TemporaryDirectory() as tmp:
            code, _out, err = self._run(
                argv,
                Path(tmp),
                lister=lister,
                downloader=self._boom,
                transcriber=self._boom,
                coverage=lambda *_a, **_k: [],
                metadata=self._boom,
            )
        self.assertEqual(code, 2, err)
        self.assertEqual(called, [])
        self.assertIn("https", err)

    def test_bad_slug_exits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, _out, err = self._run(
                ["https://www.youtube.com/channel/UCexample", "--library", "Wesley"],
                Path(tmp),
                lister=self._boom,
            )
            self.assertEqual(code, 2)
            self.assertIn("slug", err)
            code, _out, err = self._run(
                ["https://www.youtube.com/channel/UCexample", "--library", "wesley"],
                Path(tmp),
                lister=self._boom,
            )
            self.assertEqual(code, 2)

    def test_your_church_mark_is_exclusive_and_dry_run_writes_nothing(self) -> None:
        video = Video(
            "samplevid01",
            "On Mercy",
            40,
            date(2024, 6, 2),
            "https://www.youtube.com/watch?v=samplevid01",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, _out, err = self._run(
                [
                    "https://www.youtube.com/watch?v=samplevid01",
                    "--library",
                    "sample",
                    "--your-church",
                    "--dry-run",
                ],
                root,
                lister=lambda _url: [video],
                downloader=self._boom,
                transcriber=self._boom,
                metadata=self._boom,
            )
            self.assertEqual(code, 0, err)
            self.assertFalse((root / "sample.sqlite").exists())

            other = connect(root / "other.sqlite")
            ensure_library(other)  # a church import, so its mark may be cleared
            mark_your_church(other)
            other.commit()
            other.close()
            code, _out, err = self._run(
                [
                    "https://www.youtube.com/watch?v=samplevid01",
                    "--library",
                    "sample",
                    "--your-church",
                ],
                root,
                lister=lambda _url: [video],
                metadata=lambda _video: {
                    "license": "Creative Commons Attribution license (reuse allowed)",
                    "upload_date": "20240602",
                    "title": "On Mercy",
                    "uploader": "A Speaker",
                    "duration": 40,
                },
                downloader=lambda _video, dest: dest / "samplevid01.m4a",
                transcriber=lambda _path: sample_words(12.2),
                embedder=embedder,
            )
            self.assertEqual(code, 0, err)
            marked = open_readonly(root / "sample.sqlite")
            try:
                self.assertTrue(is_your_church(marked))
                self.assertEqual(get_meta(marked, "sample"), "1")
            finally:
                marked.close()
            cleared = open_readonly(root / "other.sqlite")
            try:
                self.assertFalse(is_your_church(cleared))
            finally:
                cleared.close()

    def test_your_church_reports_sibling_marks_it_did_not_clear(self) -> None:
        """A marked sibling with a second hard link is not cleared, and the importer says so."""
        video = Video(
            "samplevid01",
            "On Mercy",
            40,
            date(2024, 6, 2),
            "https://www.youtube.com/watch?v=samplevid01",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            other = connect(root / "other.sqlite")
            ensure_library(other)
            mark_your_church(other)
            other.commit()
            other.close()
            (root / "elsewhere").mkdir()
            (root / "elsewhere" / "other-link.sqlite").hardlink_to(root / "other.sqlite")
            code, _out, err = self._run(
                [
                    "https://www.youtube.com/watch?v=samplevid01",
                    "--library",
                    "sample",
                    "--your-church",
                ],
                root,
                lister=lambda _url: [video],
                metadata=lambda _video: {
                    "license": "Creative Commons Attribution license (reuse allowed)",
                    "upload_date": "20240602",
                    "title": "On Mercy",
                    "uploader": "A Speaker",
                    "duration": 40,
                },
                downloader=lambda _video, dest: dest / "samplevid01.m4a",
                transcriber=lambda _path: sample_words(12.2),
                embedder=embedder,
            )
            self.assertEqual(code, 0, err)
            self.assertIn(
                "warning: other.sqlite may still be marked as your church; it has 2 hard links, so the mark was not cleared",
                err,
            )
            kept = open_readonly(root / "other.sqlite")
            try:
                self.assertTrue(is_your_church(kept))
            finally:
                kept.close()

    def test_failed_import_does_not_mark_the_church(self) -> None:
        video = Video(
            "samplevid01",
            "On Mercy",
            40,
            date(2024, 6, 2),
            "https://www.youtube.com/watch?v=samplevid01",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            other = connect(root / "other.sqlite")
            ensure_library(other)  # a church import, so its mark may be cleared
            mark_your_church(other)
            other.commit()
            other.close()

            def boom(_path):
                raise RuntimeError("transcribe failed")

            code, _out, err = self._run(
                [
                    "https://www.youtube.com/watch?v=samplevid01",
                    "--library",
                    "sample",
                    "--your-church",
                ],
                root,
                lister=lambda _url: [video],
                metadata=lambda _video: {
                    "license": "Creative Commons Attribution license (reuse allowed)",
                    "upload_date": "20240602",
                    "title": "On Mercy",
                    "uploader": "A Speaker",
                    "duration": 40,
                },
                downloader=lambda _video, dest: dest / "samplevid01.m4a",
                transcriber=boom,
                embedder=embedder,
            )
            self.assertEqual(code, 1, err)
            self.assertTrue((root / "sample.sqlite").is_file())
            marked = open_readonly(root / "sample.sqlite")
            try:
                self.assertFalse(is_your_church(marked))
            finally:
                marked.close()
            sibling = open_readonly(root / "other.sqlite")
            try:
                self.assertTrue(is_your_church(sibling))
            finally:
                sibling.close()

    def test_classic_slugs_are_refused_as_your_church(self) -> None:
        for slug in ("wesley", "spurgeon", "edwards"):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                code, _out, err = self._run(
                    [
                        "https://www.youtube.com/watch?v=samplevid01",
                        "--library",
                        slug,
                        "--your-church",
                    ],
                    root,
                    lister=self._boom,
                )
                self.assertEqual(code, 2, err)
                self.assertIn("classic", err)
                self.assertFalse((root / f"{slug}.sqlite").exists())

    def test_privacy_hook_is_identity(self) -> None:
        words = sample_words()
        self.assertIs(redact(words), words)

    @staticmethod
    def _boom(*_args, **_kwargs):
        raise AssertionError("should not be called")

    @staticmethod
    def _get(port: int, path: str) -> tuple[int, bytes]:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()


if __name__ == "__main__":
    unittest.main()
