"""PR #6 should-fixes 2 and 4: stale chunks_aligned.jsonl is refused, and the
CLI play link seeks max(0, start_s - 0.75) while start_s stays exact."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from preached import paths
from preached.paths import StaleChunks, check_aligned_source, chunk_source_record
from preached.search import PREROLL_S, play_start

ROOT = Path(__file__).resolve().parents[1]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def rows(n: int = 3, timed: bool = False) -> list[dict]:
    out = []
    for i in range(n):
        row = {"chunk_id": f"wesley-001-c{i:04d}", "text": f"text {i}", "start_s": None, "end_s": None}
        if timed:
            row.update(start_s=float(i), end_s=i + 0.9, text_source="canonical")
        out.append(row)
    return out


class AlignedSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        self.text_only = d / "chunks.jsonl"
        self.aligned = d / "chunks_aligned.jsonl"
        self.source = d / "chunks_aligned.source.json"
        self.config = d / "chunk_config.json"
        self.config.write_text('{"max_words": 160}')
        write_jsonl(self.text_only, rows())
        write_jsonl(self.aligned, rows(timed=True))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def check(self) -> str:
        return check_aligned_source(self.aligned, self.text_only, self.source, self.config)

    def record(self) -> None:
        self.source.write_text(json.dumps(chunk_source_record(self.text_only, self.config)))

    def test_recorded_hashes_match(self) -> None:
        self.record()
        self.assertEqual(self.check(), "hash")

    def test_no_record_but_same_ids_and_text(self) -> None:
        self.assertEqual(self.check(), "content")

    def test_rechunked_text_only_file_is_refused(self) -> None:
        # The CTO scenario: chunk_config changes, chunk_sermons.py rewrites
        # chunks.jsonl, chunks_aligned.jsonl is left behind.
        self.record()
        write_jsonl(self.text_only, rows(4))
        self.config.write_text('{"max_words": 120}')
        with self.assertRaises(StaleChunks):
            self.check()

    def test_text_change_without_record_is_refused(self) -> None:
        changed = rows()
        changed[1]["text"] = "re-chunked"
        write_jsonl(self.text_only, changed)
        with self.assertRaises(StaleChunks):
            self.check()

    def test_config_only_change_with_same_content_is_accepted(self) -> None:
        self.record()
        self.config.write_text('{"max_words": 160, "note": 1}')
        self.assertEqual(self.check(), "content")

    def test_asr_rows_are_not_compared(self) -> None:
        extra = rows(timed=True) + [{"chunk_id": "asr:church-1-c0000", "text": "heard", "text_source": "asr"}]
        write_jsonl(self.aligned, extra)
        self.assertEqual(self.check(), "content")

    def test_resolved_at_call_time_and_env_override(self) -> None:
        self.assertFalse(hasattr(paths, "INDEX_CHUNKS_JSONL"))
        self.assertEqual(paths.index_chunks_jsonl({"PREACHED_CHUNKS": str(self.aligned)}), self.aligned)


class PrerollTests(unittest.TestCase):
    def test_play_start(self) -> None:
        self.assertEqual(PREROLL_S, 0.75)
        self.assertEqual(play_start(32.81), 32.06)
        self.assertEqual(play_start(0.5), 0.0)
        self.assertEqual(play_start(0), 0.0)
        self.assertIsNone(play_start(None))
        self.assertIsNone(play_start(-1))
        self.assertIsNone(play_start(float("nan")))
        self.assertIsNone(play_start(float("inf")))
        self.assertIsNone(play_start(float("-inf")))

    def test_query_play_url(self) -> None:
        spec = importlib.util.spec_from_file_location("preached_query", ROOT / "search" / "query.py")
        query = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(query)
        mp3 = "https://archive.org/download/x/y.mp3"
        self.assertEqual(query.play_url(mp3, 32.81), mp3 + "#t=32.06")
        self.assertEqual(query.play_url(mp3 + "#t=5", 0.4), mp3 + "#t=0")
        self.assertEqual(query.play_url(mp3, None), mp3)
        self.assertEqual(query.play_url(None, 3.0), "n/a")
        # The printed time is the exact start, not the seek.
        self.assertEqual(query.fmt_time(32.81), "0:00:32")

    def load_query(self):
        spec = importlib.util.spec_from_file_location("preached_query2", ROOT / "search" / "query.py")
        query = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(query)
        return query

    def test_play_url_hides_unsafe_urls(self) -> None:
        query = self.load_query()
        for bad in (
            "javascript:x",
            "http://archive.org/download/x/y.mp3",
            "file:///etc/passwd",
            "https://evil.example/y.mp3",
            "https://user:pw@archive.org/y.mp3",
            "\x1b]0;pwned\x07https://evil.example/y.mp3",
        ):
            with self.subTest(url=bad):
                self.assertEqual(query.play_url(bad, 3.0), query.UNSAFE_URL)

    def test_print_hits_strips_control_characters(self) -> None:
        import contextlib
        import io
        from types import SimpleNamespace

        query = self.load_query()
        hit = SimpleNamespace(
            sermon_title="Title\x1b[31m red", chunk_id="c\x07", score=0.5, start_s=1.0,
            reader="Rea\x9bder", audio_url="https://archive.org/download/x/y.mp3",
            source_url="https://www.ccel.org/\x1b[2J", text="grace\x1b]0;x\x07 and\nfaith",
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            query.print_hits("q", "bm25", None, [hit])
        printed = out.getvalue()
        self.assertFalse(any(ord(c) < 32 and c != "\n" or 0x7F <= ord(c) <= 0x9F for c in printed))
        self.assertIn("grace ]0;x  and faith", printed)
        self.assertIn("y.mp3#t=0.25", printed)

    def test_play_url_youtube_archive_and_hostile(self) -> None:
        query = self.load_query()
        stored = "https://www.youtube.com/watch?v=abcdefghijk&t=11s"
        self.assertEqual(query.play_url(stored, 12.2), stored)
        self.assertNotIn("#t=", query.play_url(stored, 12.2))
        self.assertEqual(query.play_url(stored, None), stored)
        apex = "https://youtube.com/watch?v=abcdefghijk&t=0s"
        self.assertEqual(query.play_url(apex, 0.4), apex)
        mobile = "https://m.youtube.com/watch?v=abcdefghijk&t=3s"
        self.assertEqual(query.play_url(mobile, 4), mobile)
        mp3 = "https://archive.org/download/x/y.mp3"
        self.assertEqual(query.play_url(mp3, 32.81), mp3 + "#t=32.06")
        dirty = "https://www.youtube.com/watch?v=abcdefghijk&t=11s\x9b"
        self.assertEqual(query.play_url(dirty, 1.0), stored + " ")
        for bad in (
            "https://www.youtube.com.evil.com/watch?v=abcdefghijk",
            "javascript:alert(1)",
            "javascript:https://www.youtube.com/watch?v=abcdefghijk",
            "http://www.youtube.com/watch?v=abcdefghijk",
            "https://evil.com@www.youtube.com/watch?v=abcdefghijk",
            "https://www.youtube.com/watch?v=abcdefghijk&t=11s\x1b",
            "https://www.youtube.com:abc/watch?v=abcdefghijk",
            "https://www.youtube.com:99999/watch?v=abcdefghijk",
            "https://[::1]/watch?v=abcdefghijk",
            "https://[gggg::1]/watch?v=abcdefghijk",
            "https://archive.org:abc/download/x/y.mp3",
            "https://archive.org:99999/download/x/y.mp3",
        ):
            with self.subTest(url=bad):
                self.assertEqual(query.play_url(bad, 3.0), query.UNSAFE_URL)

    def test_print_hits_youtube_and_hostile_play_lines(self) -> None:
        import contextlib
        import io
        from types import SimpleNamespace

        query = self.load_query()
        youtube = SimpleNamespace(
            sermon_title="On Mercy",
            chunk_id="samplevid01-c0000",
            score=0.5,
            start_s=12.2,
            reader=None,
            audio_url="https://www.youtube.com/watch?v=abcdefghijk&t=11s",
            source_url="https://www.youtube.com/watch?v=abcdefghijk",
            text="zephyrgrace",
        )
        hostile = SimpleNamespace(
            sermon_title="Title\x1b[31m",
            chunk_id="c1",
            score=0.2,
            start_s=3.0,
            reader=None,
            audio_url="https://www.youtube.com.evil.com/watch?v=abcdefghijk",
            source_url="https://example.com/text",
            text="hidden",
        )
        script = SimpleNamespace(
            sermon_title="Script",
            chunk_id="c2",
            score=0.1,
            start_s=4.0,
            reader=None,
            audio_url="javascript:alert(1)",
            source_url="https://example.com/text",
            text="hidden",
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            query.print_hits("q", "bm25", None, [youtube, hostile, script])
        printed = out.getvalue()
        play_lines = [line.strip() for line in printed.splitlines() if line.strip().startswith("play:")]
        self.assertEqual(
            play_lines,
            [
                "play: https://www.youtube.com/watch?v=abcdefghijk&t=11s  (0.75 s pre-roll)",
                "play: n/a (unsafe URL hidden)  (0.75 s pre-roll)",
                "play: n/a (unsafe URL hidden)  (0.75 s pre-roll)",
            ],
        )
        self.assertNotIn("#t=", printed)
        self.assertNotIn("youtube.com.evil.com", printed)
        self.assertNotIn("javascript:", printed)
        self.assertFalse(any(ord(c) < 32 and c != "\n" or 0x7F <= ord(c) <= 0x9F for c in printed))


if __name__ == "__main__":
    unittest.main()
