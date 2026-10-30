import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingest"))
sys.path.insert(0, str(ROOT / "search"))

import classics  # noqa: E402
import manifest  # noqa: E402
import build_library  # noqa: E402
import run  # noqa: E402
from preached.corpus import load_chunk_config  # noqa: E402


class ManifestTests(unittest.TestCase):
    def test_committed_manifests_validate(self):
        expected = {"talmage": 1, "spurgeon": 6, "edwards": 39}
        for slug, count in expected.items():
            rows = manifest.load(manifest.MANIFEST.with_name(f"{slug}.jsonl"))
            self.assertEqual(len(rows), count, slug)
            self.assertEqual(len({r["id"] for r in rows}), count)
            for r in rows:
                self.assertTrue(r["id"].startswith(slug))
                self.assertEqual(r["ia_identifier"], classics.SOURCES[slug]["ia"])
                self.assertIn(f"/{r['ia_identifier']}/", r["audio_url"])

    def test_clean_title(self):
        self.assertEqual(classics.clean_title("03 - Christ's Agony, pt. 2"), "Christ's Agony, pt 2")

    def test_use_library_points_dirs(self):
        import fetch
        import transcribe

        old = (fetch.AUDIO_DIR, transcribe.TRANSCRIPT_DIR, run.LOG)
        try:
            run.use_library("spurgeon")
            self.assertEqual(fetch.AUDIO_DIR.name, "spurgeon")
            self.assertEqual(transcribe.TRANSCRIPT_DIR.name, "spurgeon")
            with self.assertRaises(manifest.UnsafeRow):
                run.use_library("../x")
        finally:
            fetch.AUDIO_DIR, transcribe.TRANSCRIPT_DIR, run.LOG = old


class BuildTests(unittest.TestCase):
    def test_searchable_window_and_chunks(self):
        words = [[float(i), i + 0.5, f"w{i}."] for i in range(100)]
        doc = {"searchable_start": 10.0, "searchable_end": 60.0, "segments": [{"words": words}]}
        got = build_library.transcript_words(doc)
        self.assertEqual((got[0].start, got[-1].start), (10.0, 59.0))
        row = {"id": "x-01", "audio_url": "https://archive.org/download/x/a.mp3", "ia_url": "https://archive.org/details/x"}
        chunks = build_library.chunks_for(row, got, load_chunk_config())
        self.assertTrue(chunks)
        self.assertEqual(chunks[0]["chunk_id"], "x-01-c0000")
        self.assertEqual(chunks[0]["audio_url"], row["audio_url"])
        self.assertGreaterEqual(chunks[0]["start_s"], 10.0)


if __name__ == "__main__":
    unittest.main()
