"""ASR coverage gate: sound with no transcript word blocks approval.

Audio is synthetic: noise with a speech-like beat where "speech" is wanted,
and near silence elsewhere. ffmpeg decodes the WAV files, as in the product.
"""

from __future__ import annotations

import os
import tempfile
import unittest
import wave
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import numpy as np

from preached.youtube.cli import main
from preached.youtube.coverage import MAX_UNCOVERED_S, SR, Span, check_coverage, clip_to_window
from preached.youtube.library import open_library
from preached.youtube.listing import Video
from preached.youtube.words import Word
from test_youtube import embedder, speech_words


def synth(seconds: float, speech: list[tuple[float, float]]) -> np.ndarray:
    rng = np.random.default_rng(7)
    audio = rng.normal(0, 3e-5, int(seconds * SR)).astype(np.float32)  # about -90 dBFS room tone
    t = np.arange(len(audio)) / SR
    beat = 0.55 + 0.45 * np.sin(2 * np.pi * 4 * t)  # 4 Hz syllable rhythm
    voice = rng.normal(0, 0.08, len(audio)).astype(np.float32) * beat.astype(np.float32)
    for a, b in speech:
        audio[int(a * SR) : int(b * SR)] += voice[int(a * SR) : int(b * SR)]
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
        self.assertAlmostEqual(gaps[0].start_s, 20.0, delta=1.0)
        self.assertAlmostEqual(gaps[0].end_s, 40.0, delta=1.0)

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

    def test_undecodable_audio_falls_back_to_the_duration(self) -> None:
        bad = self.dir / "bad.m4a"
        bad.write_bytes(b"not audio")
        gaps = check_coverage(bad, words_for((0, 10)), duration_s=40.0)
        self.assertEqual(len(gaps), 1)
        self.assertAlmostEqual(gaps[0].length_s, 40 - 10.3, delta=1.0)
        with self.assertRaises(RuntimeError):
            check_coverage(bad, [])

    def test_window_clips_and_drops_spans(self) -> None:
        spans = [Span(0, 12), Span(30, 50)]
        self.assertEqual(clip_to_window(spans, None), spans)
        self.assertEqual(clip_to_window(spans, (20, 100)), [Span(30, 50)])
        self.assertEqual(clip_to_window(spans, (40, 100)), [Span(40, 50)])
        self.assertEqual(clip_to_window(spans, (45, 100)), [])


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

    def import_and_approve(self, speech, words):
        def downloader(_video, dest):
            dest.mkdir(parents=True, exist_ok=True)
            return write_wav(dest / "covvideo001.wav", synth(60.0, speech))

        code, err = self.run_main(
            ["https://www.youtube.com/watch?v=covvideo001", "--library", "cov"],
            lister=lambda _url: [self.video],
            metadata=lambda _v: {"license": "Creative Commons Attribution license (reuse allowed)", "title": "On Mercy", "duration": 60},
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
        self.assertIn("no transcript", err)
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

    def test_unchecked_import_is_refused(self) -> None:
        self.import_and_approve([(1, 59)], words_for((1, 59)))
        connection = open_library(self.root / "cov.sqlite")
        connection.execute("UPDATE videos SET coverage_gaps = NULL, approved_sha256 = NULL")
        connection.commit()
        connection.close()
        code, err = self.run_main(["--library", "cov", "--ack-review", "covvideo001"])
        self.assertEqual(code, 1)
        self.assertIn("never checked", err)


if __name__ == "__main__":
    unittest.main()
