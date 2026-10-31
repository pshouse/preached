"""ASR coverage gate: sound with no transcript word blocks approval.

Audio is synthetic: noise with a speech-like beat where "speech" is wanted,
and near silence elsewhere. ffmpeg decodes the WAV files, as in the product.
The real-world fixtures (``fixtures/asr_repro``) are the CTO's corrupted
turbo output from an AMX CPU and clean output for the same clips.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import wave
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for sub in ("align", "tests"):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

import asr_chunks  # noqa: E402
from preached.store import open_readonly, pending_review_count, visible_count  # noqa: E402
from preached.youtube.cli import main  # noqa: E402
from preached.youtube.coverage import (  # noqa: E402
    LENGTH_TOLERANCE_S,
    LONG_WORD_S,
    MAX_UNCOVERED_S,
    SR,
    Span,
    Unchecked,
    check_coverage,
    clip_to_window,
    open_spans,
    sound_spans_from_db,
    sparse_spans,
    stated_duration,
    stretched_spans,
    uncovered_spans,
    sound_spans,
)
from preached.youtube.library import open_library  # noqa: E402
from preached.youtube.listing import Video  # noqa: E402
from preached.youtube.words import Word  # noqa: E402
from test_youtube import embedder, speech_words  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "asr_repro"


def synth(seconds: float, speech: list[tuple[float, float]], *, quiet: list[tuple[float, float]] = (), floor: float = 3e-5) -> np.ndarray:
    """Room tone at ``floor`` (3e-5 is about -90 dBFS), speech at about -22 dBFS, ``quiet`` speech 33 dB lower."""
    rng = np.random.default_rng(7)
    audio = rng.normal(0, floor, int(seconds * SR)).astype(np.float32)
    t = np.arange(len(audio)) / SR
    beat = 0.55 + 0.45 * np.sin(2 * np.pi * 4 * t)  # 4 Hz syllable rhythm
    voice = rng.normal(0, 0.08, len(audio)).astype(np.float32) * beat.astype(np.float32)
    for a, b in speech:
        audio[int(a * SR) : int(b * SR)] += voice[int(a * SR) : int(b * SR)]
    for a, b in quiet:
        audio[int(a * SR) : int(b * SR)] += voice[int(a * SR) : int(b * SR)] * 10 ** (-33 / 20)
    return audio


def write_wav(path: Path, audio: np.ndarray) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def words_for(*stretches: tuple[float, float]) -> list[Word]:
    out: list[Word] = []
    for a, b in stretches:
        out.extend(speech_words(a, b, "grace abides in the quiet heart today"))
    return out


class CheckTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def check(self, speech, words, seconds=60.0):
        path = write_wav(self.dir / "a.wav", synth(seconds, speech))
        return check_coverage(path, words)

    def test_clean_file_passes(self) -> None:
        self.assertEqual(self.check([(2, 58)], words_for((2, 58))), [])

    def test_speech_the_transcript_misses_is_found(self) -> None:
        # 20 s of speech the transcript skipped, in the middle of the file.
        gaps = self.check([(2, 58)], words_for((2, 20), (40, 58)))
        self.assertEqual(len(gaps), 1)
        # Sparse windows may widen the span by up to a window; it always holds the hole.
        self.assertLessEqual(gaps[0].start_s, 20.5)
        self.assertGreaterEqual(gaps[0].end_s, 39.5)
        self.assertGreater(gaps[0].start_s, 2.0)

    def test_hole_at_the_end_is_found(self) -> None:
        gaps = self.check([(2, 58)], words_for((2, 40)))
        self.assertEqual(len(gaps), 1)
        self.assertGreater(gaps[0].length_s, 15)

    def test_gap_under_the_limit_passes(self) -> None:
        gaps = self.check([(2, 58)], words_for((2, 25), (25 + MAX_UNCOVERED_S - 1.5, 58)))
        self.assertEqual(gaps, [])

    def test_silence_without_words_passes(self) -> None:
        # Speech 2-20 and 40-58 is transcribed; 20-40 is room tone.
        self.assertEqual(self.check([(2, 20), (40, 58)], words_for((2, 20), (40, 58))), [])

    def test_two_holes_are_two_spans(self) -> None:
        gaps = self.check([(2, 58)], words_for((2, 10), (22, 34), (46, 58)))
        self.assertEqual(len(gaps), 2)

    def test_one_long_word_does_not_cover_a_hole(self) -> None:
        # M1: one junk word stretched over 28 s of speech (c03's 'eject', 56.92-85.38 s).
        words = [*words_for((2, 20)), Word(20.0, 48.0, "eject"), *words_for((48, 58))]
        gaps = self.check([(2, 58)], words)
        self.assertEqual(len(gaps), 1)
        self.assertLessEqual(gaps[0].start_s, 21.5)
        self.assertGreaterEqual(gaps[0].end_s, 46.5)
        # A word up to WORD_MAX_COVER_S long covers all of itself.
        words = [*words_for((2, 20)), Word(20.0, 21.9, "amen"), *words_for((21.9, 58))]
        self.assertEqual(self.check([(2, 58)], words), [])

    def test_stray_words_over_speech_are_a_sparse_span(self) -> None:
        # S2: one word every 4.5 s over 40 s of speech. No gap is over 5 s; the density rule finds it.
        words = [*words_for((2, 10)), *(Word(10 + 4.5 * k, 10.3 + 4.5 * k, "and") for k in range(9)), *words_for((50, 58))]
        path = write_wav(self.dir / "a.wav", synth(60.0, [(2, 58)]))
        self.assertEqual(uncovered_spans(sound_spans(synth(60.0, [(2, 58)])), words), [])
        gaps = check_coverage(path, words)
        self.assertEqual(len(gaps), 1)
        self.assertLessEqual(gaps[0].start_s, 12)
        self.assertGreaterEqual(gaps[0].end_s, 48)

    def test_stretched_word_over_speech_is_a_span(self) -> None:
        # CTO round 2 S-a: a 7 s word over speech hides ~5 s, under MAX_UNCOVERED_S.
        words = [*words_for((2, 20)), Word(20.0, 27.0, "the"), *words_for((27, 58))]
        sound = sound_spans(synth(60.0, [(2, 58)]))
        self.assertEqual(uncovered_spans(sound, words), [])
        self.assertEqual(sparse_spans(sound, words), [])
        self.assertEqual(stretched_spans(sound, words), [Span(20.0, 27.0)])
        self.assertEqual(self.check([(2, 58)], words), [Span(20.0, 27.0)])
        # A hand-set window around the sermon keeps it, though it is under 5 s.
        self.assertEqual(clip_to_window([Span(20.0, 27.0)], (2, 58)), [Span(20.0, 27.0)])

    def test_stretched_word_over_silence_or_under_the_limit_passes(self) -> None:
        # The same word over room tone hides nothing.
        words = [*words_for((2, 20)), Word(20.0, 27.0, "amen"), *words_for((27, 58))]
        self.assertEqual(self.check([(2, 20), (27, 58)], words), [])
        # A word up to LONG_WORD_S long is not this rule's business.
        words = [*words_for((2, 20)), Word(20.0, 20.0 + LONG_WORD_S, "the"), *words_for((20.0 + LONG_WORD_S, 58))]
        self.assertEqual(self.check([(2, 58)], words), [])

    def test_words_sharing_a_timestamp_count_once(self) -> None:
        # CTO round 2 S-b: three words on each stray timestamp used to triple the density.
        stray = [Word(10 + 4.5 * k + d, 10.3 + 4.5 * k + d, "and") for k in range(9) for d in (0.0, 0.0, 0.0)]
        words = [*words_for((2, 10)), *stray, *words_for((50, 58))]
        sound = sound_spans(synth(60.0, [(2, 58)]))
        self.assertEqual(uncovered_spans(sound, words), [])
        spans = sparse_spans(sound, words)
        self.assertEqual(len(spans), 1)
        self.assertLessEqual(spans[0].start_s, 12)
        self.assertGreaterEqual(spans[0].end_s, 48)
        # Three distinct starts per stray position is real density, and passes.
        spread = [Word(10 + 4.5 * k + d, 10.3 + 4.5 * k + d, "and") for k in range(9) for d in (0.0, 1.0, 2.0)]
        self.assertEqual(sparse_spans(sound, [*words_for((2, 10)), *spread, *words_for((50, 58))]), [])

    def test_quiet_speech_counts_as_sound(self) -> None:
        # S1: speech 33 dB below the loud parts is sound (it was silence at 30 dB).
        path = write_wav(self.dir / "a.wav", synth(60.0, [(2, 20), (40, 58)], quiet=[(20, 40)]))
        gaps = check_coverage(path, words_for((2, 20), (40, 58)))
        self.assertEqual(len(gaps), 1)
        self.assertLessEqual(gaps[0].start_s, 21)
        self.assertGreaterEqual(gaps[0].end_s, 39)
        self.assertEqual(check_coverage(path, words_for((2, 58))), [])

    def test_speech_43_db_down_is_sound(self) -> None:
        # CTO round 2 S-g: REL_DB 45. Loud speech at -10 dBFS, quiet speech at -53 (43 dB down), room tone at -90.
        db = np.full(2000, -90.0)
        db[100:600] = -10.0
        db[1000:1500] = -53.0
        spans = sound_spans_from_db(db)
        self.assertEqual(len(spans), 2)
        self.assertAlmostEqual(spans[1].start_s, 1000 * 0.03, places=2)

    def test_steady_hiss_is_not_sound(self) -> None:
        # S1 noise-floor guard: a hiss 30 dB under the speech (inside REL_DB) is not sound.
        path = write_wav(self.dir / "a.wav", synth(60.0, [(2, 20), (40, 58)], floor=0.08 * 10 ** (-30 / 20)))
        self.assertEqual(check_coverage(path, words_for((2, 20), (40, 58))), [])

    def test_undecodable_audio_is_unchecked(self) -> None:
        # S4: no fallback to the duration; the caller stores NULL.
        bad = self.dir / "bad.m4a"
        bad.write_bytes(b"not audio")
        with self.assertRaises(Unchecked):
            check_coverage(bad, words_for((0, 10)), duration_s=40.0)
        with self.assertRaises(Unchecked):
            check_coverage(self.dir / "missing.wav", [])

    def test_audio_shorter_than_the_transcript_is_unchecked(self) -> None:
        # M3: 20 s of audio for a 60 s transcript.
        path = write_wav(self.dir / "a.wav", synth(20.0, [(1, 19)]))
        with self.assertRaises(Unchecked):
            check_coverage(path, words_for((1, 58)))
        # Shorter than the stated duration (a download cut short), even if the words fit.
        with self.assertRaises(Unchecked):
            check_coverage(path, words_for((1, 19)), duration_s=240.0)
        # Within the tolerance it runs.
        self.assertEqual(check_coverage(path, words_for((1, 19)), duration_s=20.0 + LENGTH_TOLERANCE_S - 0.5), [])

    def test_audio_a_few_seconds_short_is_unchecked(self) -> None:
        # CTO round 2 S-c: 3-5 s short of the stated duration or the last word is past LENGTH_TOLERANCE_S.
        path = write_wav(self.dir / "a.wav", synth(20.0, [(1, 19)]))
        for short in (3.0, 4.0, 5.0):
            with self.subTest(short=short):
                with self.assertRaises(Unchecked):
                    check_coverage(path, words_for((1, 19)), duration_s=20.0 + short)
                with self.assertRaises(Unchecked):
                    check_coverage(path, [*words_for((1, 19)), Word(19.5, 20.0 + short, "amen")])
        # Right at the tolerance it still runs.
        self.assertEqual(check_coverage(path, words_for((1, 19)), duration_s=20.0 + LENGTH_TOLERANCE_S), [])

    def test_window_clips_and_drops_spans(self) -> None:
        spans = [Span(0, 12), Span(30, 50)]
        self.assertEqual(clip_to_window(spans, None), spans)
        self.assertEqual(clip_to_window(spans, (20, 100)), [Span(30, 50)])
        self.assertEqual(clip_to_window(spans, (40, 100)), [Span(40, 50)])
        self.assertEqual(clip_to_window(spans, (45, 100)), [])
        # Wholly inside the window: kept at any length. Cut by it: needs more than max_gap_s left.
        self.assertEqual(clip_to_window([Span(30, 33)], (20, 100)), [Span(30, 33)])
        self.assertEqual(clip_to_window([Span(18, 23)], (20, 100)), [])


def fixture(name: str) -> tuple[np.ndarray, list[Word], list[Word]]:
    db = np.load(FIXTURES / f"{name}.db.npy").astype(np.float64) / 10.0
    load = lambda tag: [Word(a, b, t) for a, b, t in json.loads((FIXTURES / f"{name}.{tag}.json").read_text())]  # noqa: E731
    return db, load("amx-corrupt"), load("clean")


class CorruptedAsrFixtureTests(unittest.TestCase):
    """The CTO's turbo int8 output from an AMX CPU (MKL's AMX kernels corrupted the encoder).

    Each fixture is the frame level (0.1 dB) of the 240 s clip plus the word
    list. Holes over 5 s are the ones the CTO listed; c03 has the junk word
    'eject' stretched over 56.92-85.38 s.
    """

    HOLES = {
        "c01": [(24.52, 30.64), (140.42, 156.18)],
        "c03": [(25.58, 54.16), (56.92, 85.38), (96.68, 115.38), (116.66, 146.66)],
    }

    def test_every_hole_is_flagged(self) -> None:
        for name, holes in self.HOLES.items():
            db, corrupt, _clean = fixture(name)
            spans = open_spans(sound_spans_from_db(db), corrupt)
            for a, b in holes:
                with self.subTest(clip=name, hole=(a, b)):
                    self.assertTrue(any(s.start_s <= a + 1.0 and s.end_s >= b - 1.0 for s in spans), spans)

    def test_clean_transcripts_have_no_span(self) -> None:
        for name in self.HOLES:
            db, _corrupt, clean = fixture(name)
            with self.subTest(clip=name):
                self.assertEqual(open_spans(sound_spans_from_db(db), clean), [])

    def test_the_junk_word_hole_needs_the_word_cap(self) -> None:
        import preached.youtube.coverage as coverage

        db, corrupt, _clean = fixture("c03")
        sound = sound_spans_from_db(db)
        eject = [w for w in corrupt if w.text == "eject"]
        self.assertEqual([(w.start, w.end) for w in eject], [(56.92, 85.38)])
        with patch.object(coverage, "WORD_MAX_COVER_S", 1e9):
            self.assertFalse(any(s.start_s < 80 and s.end_s > 60 for s in coverage.uncovered_spans(sound, corrupt)))
        self.assertTrue(any(s.start_s < 60 and s.end_s > 80 for s in coverage.uncovered_spans(sound, corrupt)))

    @unittest.skipUnless(Path("/cache/asr-repro/c01.wav").exists(), "needs the clips in /cache/asr-repro")
    def test_envelope_matches_the_audio(self) -> None:
        for name in self.HOLES:
            db, corrupt, clean = fixture(name)
            path = Path(f"/cache/asr-repro/{name}.wav")
            with self.subTest(clip=name):
                self.assertEqual(check_coverage(path, corrupt), open_spans(sound_spans_from_db(db), corrupt))
                self.assertEqual(check_coverage(path, clean), [])


class ApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        toml = self.root / "privacy.toml"
        toml.write_text("# built-in name rules only\n")
        env = {k: v for k, v in os.environ.items() if k != "PREACHED_FLAGGED_AUDIO"}
        env["PREACHED_PRIVACY"] = str(toml)
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.video = Video("covvideo001", "On Mercy", 60, date(2024, 6, 2), "https://www.youtube.com/watch?v=covvideo001")

    def run_main(self, argv, **kwargs):
        err = StringIO()
        with redirect_stdout(StringIO()), redirect_stderr(err):
            code = main(argv, index_dir=self.root, audio_root=self.root / "audio", **kwargs)
        return code, err.getvalue()

    def import_and_approve(self, speech, words, *, seconds: float = 60.0, duration: float = 60):
        def downloader(_video, dest):
            dest.mkdir(parents=True, exist_ok=True)
            return write_wav(dest / "covvideo001.wav", synth(seconds, speech))

        code, err = self.run_main(
            ["https://www.youtube.com/watch?v=covvideo001", "--library", "cov"],
            lister=lambda _url: [self.video],
            metadata=lambda _v: {"license": "Creative Commons Attribution license (reuse allowed)", "title": "On Mercy", "duration": duration},
            downloader=downloader,
            transcriber=lambda _path: words,
            embedder=embedder,
        )
        self.assertEqual(code, 0, err)
        return err, *self.run_main(["--library", "cov", "--ack-review", "covvideo001"])

    def stored(self):
        connection = open_library(self.root / "cov.sqlite")
        try:
            return connection.execute("SELECT coverage_gaps, approved_sha256 FROM videos").fetchone()
        finally:
            connection.close()

    def test_missed_speech_blocks_approval(self) -> None:
        import_err, code, err = self.import_and_approve([(1, 59)], words_for((1, 20), (40, 59)))
        self.assertEqual(code, 1)
        self.assertIn("not covered by the transcript", err)
        self.assertIn("coverage covvideo001", import_err)
        gaps, approved = self.stored()
        self.assertIn("[", gaps)
        self.assertIsNone(approved)

    def test_clean_file_is_approved(self) -> None:
        _import_err, code, err = self.import_and_approve([(1, 59)], words_for((1, 59)))
        self.assertEqual(code, 0, err)
        gaps, approved = self.stored()
        self.assertEqual(gaps, "[]")
        self.assertIsNotNone(approved)

    def test_approval_leaves_the_church_file_in_delete_mode(self) -> None:
        # PR #37 r1 should-fix 6: the server's read-only open then makes no -wal/-shm.
        from preached.library import open_church_readonly, wal_mode

        index = self.root / "cov.sqlite"
        _import_err, code, err = self.import_and_approve([(1, 59)], words_for((1, 59)))
        self.assertEqual(code, 0, err)
        self.assertIs(wal_mode(index), False)
        for suffix in ("-wal", "-shm"):
            self.assertFalse(Path(f"{index}{suffix}").exists(), suffix)
        connection, _identity = open_church_readonly(index)
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM videos").fetchone()[0], 1)
        finally:
            connection.close()
        for suffix in ("-wal", "-shm"):
            self.assertFalse(Path(f"{index}{suffix}").exists(), suffix)

    def test_approval_with_another_wal_reader_warns_and_the_server_refuses_the_file(self) -> None:
        import sqlite3

        from preached.library import ChurchRefused, open_church_readonly, wal_mode

        index = self.root / "cov.sqlite"

        def downloader(_video, dest):
            dest.mkdir(parents=True, exist_ok=True)
            return write_wav(dest / "covvideo001.wav", synth(60.0, [(1, 59)]))

        code, err = self.run_main(
            ["https://www.youtube.com/watch?v=covvideo001", "--library", "cov"],
            lister=lambda _url: [self.video],
            metadata=lambda _v: {"license": "Creative Commons Attribution license (reuse allowed)", "title": "On Mercy", "duration": 60},
            downloader=downloader,
            transcriber=lambda _path: words_for((1, 59)),
            embedder=embedder,
        )
        self.assertEqual(code, 0, err)
        reader = sqlite3.connect(index)  # another WAL reader, idle between reads
        self.addCleanup(reader.close)
        reader.execute("SELECT count(*) FROM chunks").fetchone()
        code, err = self.run_main(["--library", "cov", "--ack-review", "covvideo001"])
        self.assertEqual(code, 0, err)
        self.assertIn("warning: the church file is still in wal journal mode", err)
        self.assertIsNotNone(self.stored()[1])  # the approval stands
        self.assertIs(wal_mode(index), True)
        with self.assertRaises(ChurchRefused) as caught:
            open_church_readonly(index)
        self.assertIn("WAL journal mode", str(caught.exception))
        reader.close()
        code, err = self.run_main(["--library", "cov", "--ack-review", "covvideo001"])
        self.assertEqual(code, 0, err)
        self.assertNotIn("warning", err)
        self.assertIs(wal_mode(index), False)

    def test_unchecked_import_is_refused(self) -> None:
        self.import_and_approve([(1, 59)], words_for((1, 59)))
        connection = open_library(self.root / "cov.sqlite")
        connection.execute("UPDATE videos SET coverage_gaps = NULL, approved_sha256 = NULL")
        connection.commit()
        connection.close()
        code, err = self.run_main(["--library", "cov", "--ack-review", "covvideo001"])
        self.assertEqual(code, 1)
        self.assertIn("never checked", err)


    def test_download_cut_short_is_unchecked_and_refused(self) -> None:
        # M3: a 240 s video whose download stopped at 60 s; the transcript covers what is there.
        import_err, code, err = self.import_and_approve([(1, 59)], words_for((1, 59)), duration=240)
        self.assertIn("NOT checked", import_err)
        self.assertEqual(code, 1)
        self.assertIn("never checked", err)
        gaps, approved = self.stored()
        self.assertIsNone(gaps)
        self.assertIsNone(approved)

    def visible(self) -> tuple[int, int]:
        connection = open_readonly(self.root / "cov.sqlite")
        try:
            return visible_count(connection, gated=True), pending_review_count(connection)
        finally:
            connection.close()

    def test_serving_requires_an_empty_coverage_list(self) -> None:
        # M2: approved and '[]' is served; an approved row with NULL (approved before the
        # check existed) or an open span is not, and counts as pending.
        _import_err, code, err = self.import_and_approve([(1, 59)], words_for((1, 59)))
        self.assertEqual(code, 0, err)
        served, pending = self.visible()
        self.assertGreater(served, 0)
        self.assertEqual(pending, 0)
        for value in (None, "[[20.0, 45.0]]", "", "[ ]"):
            connection = open_library(self.root / "cov.sqlite")
            connection.execute("UPDATE videos SET coverage_gaps = ?", (value,))
            connection.commit()
            connection.close()
            with self.subTest(coverage_gaps=value):
                self.assertEqual(self.visible(), (0, 1))


class PendingCountTests(unittest.TestCase):
    """CTO round 2 S-e: /healthz pending_review must agree with the gate when columns are missing."""

    def test_missing_gate_columns_count_every_import_as_pending(self) -> None:
        import sqlite3

        connection = sqlite3.connect(":memory:")
        self.assertEqual(pending_review_count(connection), 0)  # no videos table: nothing imported
        # A pre-#20 file: approved, but no coverage_gaps column. visible_sql serves nothing.
        connection.execute("CREATE TABLE videos (video_id TEXT, status TEXT, review_sha256 TEXT, approved_sha256 TEXT)")
        connection.executemany("INSERT INTO videos VALUES (?, ?, 'sha', 'sha')", [("a", "ok"), ("b", "ok"), ("c", "error")])
        self.assertEqual(pending_review_count(connection), 2)
        connection.execute("CREATE TABLE chunks (video_id TEXT)")
        self.assertEqual(visible_count(connection, gated=True), 0)
        # Older still: no review columns either.
        connection.execute("DROP TABLE videos")
        connection.execute("CREATE TABLE videos (video_id TEXT, status TEXT)")
        connection.execute("INSERT INTO videos VALUES ('a', 'ok')")
        self.assertEqual(pending_review_count(connection), 1)


class ChurchPathTests(unittest.TestCase):
    """M4: align/asr_chunks.py through the real coverage check (no stub), then --ack-review."""

    AUDIO = "https://archive.org/download/church-sample/church-1.mp3"

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.toml = self.root / "privacy.toml"
        self.toml.write_text("# built-in name rules only\n")
        env = {k: v for k, v in os.environ.items() if k != "PREACHED_FLAGGED_AUDIO"}
        env["PREACHED_PRIVACY"] = str(self.toml)
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.index = self.root / "church.sqlite"
        self.audio = self.root / "audio"
        self.audio.mkdir()

    def transcript(self, words, sermon_id: str = "church-1", **extra) -> Path:
        path = self.root / f"{sermon_id}.json"
        path.write_text(json.dumps({
            "meta": {"id": sermon_id, "title": "Sunday morning", "audio_url": self.AUDIO, "duration_s": 60.0,
                     **extra.pop("meta", {})},
            "segments": [{"words": [[w.start, w.end, w.text] for w in words]}],
            **extra,
        }))
        return path

    def chunk(self, transcript: Path, *, audio_dir: Path | None = None):
        argv = [str(transcript), "--out", str(self.root / "c.jsonl"), "--library", "church", "--privacy", str(self.toml), "--index", str(self.index)]
        if audio_dir is not None:
            argv += ["--audio-dir", str(audio_dir)]
        err = StringIO()
        with redirect_stdout(StringIO()), redirect_stderr(err):
            asr_chunks.main(argv, embedder=embedder)
        return err.getvalue()

    def ack(self, sermon_id: str = "church-1"):
        err = StringIO()
        with redirect_stdout(StringIO()), redirect_stderr(err):
            code = main(["--library", "church", "--ack-review", sermon_id], index_dir=self.root, audio_root=self.root / "a")
        return code, err.getvalue()

    def stored(self, sermon_id: str = "church-1"):
        connection = open_readonly(self.index)
        try:
            row = connection.execute("SELECT coverage_gaps, approved_sha256 FROM videos WHERE video_id = ?", (sermon_id,)).fetchone()
            return (*row, visible_count(connection, gated=True))
        finally:
            connection.close()

    def test_clean_recording_is_checked_approved_and_served(self) -> None:
        write_wav(self.audio / "church-1.wav", synth(60.0, [(1, 59)]))
        self.chunk(self.transcript(words_for((1, 59))), audio_dir=self.audio)
        self.assertEqual(self.stored()[0], "[]")
        code, err = self.ack()
        self.assertEqual(code, 0, err)
        gaps, approved, served = self.stored()
        self.assertIsNotNone(approved)
        self.assertGreater(served, 0)

    def test_hole_in_the_recording_blocks_approval(self) -> None:
        # Fails if the church default were a stub that finds nothing.
        write_wav(self.audio / "church-1.wav", synth(60.0, [(1, 59)]))
        err = self.chunk(self.transcript(words_for((1, 20), (40, 59))), audio_dir=self.audio)
        self.assertIn("coverage church-1: no transcript for sound", err)
        gaps = json.loads(self.stored()[0])
        self.assertEqual(len(gaps), 1)
        code, err = self.ack()
        self.assertEqual(code, 1)
        self.assertIn("not covered by the transcript", err)
        self.assertIn("align/asr_chunks.py", err)  # S6: names the church path's own mechanism
        self.assertIn("searchable_start", err)
        self.assertEqual(self.stored()[1:], (None, 0))

    def test_hole_outside_the_searchable_window_needs_no_clearing(self) -> None:
        # Clearing by re-import: the transcript's searchable range leaves out the music before the sermon.
        write_wav(self.audio / "church-1.wav", synth(60.0, [(1, 59)]))
        self.chunk(self.transcript(words_for((20, 59)), searchable_start=19.5, searchable_end=59.5), audio_dir=self.audio)
        self.assertEqual(self.stored()[0], "[]")
        self.assertEqual(self.ack()[0], 0)

    def test_missing_audio_stores_null_and_is_refused(self) -> None:
        for audio_dir in (None, self.audio):
            with self.subTest(audio_dir=audio_dir):
                err = self.chunk(self.transcript(words_for((1, 59))), audio_dir=audio_dir)
                self.assertIn("NOT checked", err)
                self.assertEqual(self.stored()[:2], (None, None))
                code, err = self.ack()
                self.assertEqual(code, 1)
                self.assertIn("never checked", err)

    def test_no_stated_duration_stores_null(self) -> None:
        # CTO round 2 S-d: without meta.duration_s a download cut short after the last word would pass.
        write_wav(self.audio / "church-1.wav", synth(60.0, [(1, 59)]))
        for duration in (None, 0, -5, "60", True):
            with self.subTest(duration=duration):
                err = self.chunk(self.transcript(words_for((1, 59)), meta={"duration_s": duration}), audio_dir=self.audio)
                self.assertIsNone(self.stored()[0])
                self.assertIn("no usable stated duration", err)
        path = self.transcript(words_for((1, 59)))
        data = json.loads(path.read_text())
        del data["meta"]["duration_s"]
        path.write_text(json.dumps(data))
        self.chunk(path, audio_dir=self.audio)
        self.assertIsNone(self.stored()[0])
        self.assertEqual(self.ack()[0], 1)
        self.chunk(self.transcript(words_for((1, 59))), audio_dir=self.audio)
        self.assertEqual(self.stored()[0], "[]")

    def test_huge_integer_duration_is_unchecked_not_an_abort(self) -> None:
        # An integer too large for a float raised OverflowError out of stated_duration and aborted the run.
        for huge in (2**1024, -(2**1024), 10**400):
            with self.subTest(huge=huge):
                with self.assertRaises(Unchecked):
                    stated_duration(huge)
        self.assertEqual(stated_duration(2**1000), float(2**1000))
        write_wav(self.audio / "church-1.wav", synth(60.0, [(1, 59)]))
        for huge in (2**1024, -(2**1024)):
            with self.subTest(church_huge=huge):
                err = self.chunk(self.transcript(words_for((1, 59)), meta={"duration_s": huge}), audio_dir=self.audio)
                self.assertIsNone(self.stored()[0])
                self.assertIn("no usable stated duration", err)
        self.chunk(self.transcript(words_for((1, 59))), audio_dir=self.audio)
        self.assertEqual(self.stored()[0], "[]")

    def test_short_or_undecodable_audio_stores_null(self) -> None:
        # M3 / S4: 20 s of a 60 s sermon; then a file ffmpeg cannot read.
        write_wav(self.audio / "church-1.wav", synth(20.0, [(1, 19)]))
        self.chunk(self.transcript(words_for((1, 59))), audio_dir=self.audio)
        self.assertIsNone(self.stored()[0])
        # Shorter than meta.duration_s although the words fit.
        self.chunk(self.transcript(words_for((1, 19)), meta={"duration_s": 240.0}), audio_dir=self.audio)
        self.assertIsNone(self.stored()[0])
        (self.audio / "church-1.wav").write_bytes(b"RIFF not really")
        self.chunk(self.transcript(words_for((1, 19))), audio_dir=self.audio)
        self.assertIsNone(self.stored()[0])
        self.assertEqual(self.ack()[0], 1)

    def test_audio_is_matched_by_exact_name(self) -> None:
        # S3: the transcript itself (church-1.json), church-10.wav and church-1.txt are never taken.
        write_wav(self.audio / "church-10.wav", synth(60.0, [(1, 59)]))
        (self.audio / "church-1.txt").write_text("notes")
        transcript = self.transcript(words_for((1, 59)))
        (self.audio / "church-1.json").write_text(transcript.read_text())
        self.chunk(transcript, audio_dir=self.audio)
        self.assertIsNone(self.stored()[0])
        write_wav(self.audio / "church-1.wav", synth(60.0, [(1, 59)]))
        self.chunk(transcript, audio_dir=self.audio)
        self.assertEqual(self.stored()[0], "[]")

    def test_two_audio_files_for_one_sermon_refuse_before_writing(self) -> None:
        write_wav(self.audio / "church-1.wav", synth(60.0, [(1, 59)]))
        write_wav(self.audio / "church-1.mp3", synth(60.0, [(1, 59)]))
        with self.assertRaises(SystemExit) as caught:
            self.chunk(self.transcript(words_for((1, 59))), audio_dir=self.audio)
        self.assertIn("keep one", str(caught.exception))
        self.assertFalse(self.index.exists())
        self.assertFalse((self.root / "c.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
