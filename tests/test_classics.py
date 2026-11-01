__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

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
        expected = {"spurgeon": 6, "edwards": 39}
        for slug, count in expected.items():
            rows = manifest.load(manifest.MANIFEST.with_name(f"{slug}.jsonl"))
            self.assertEqual(len(rows), count, slug)
            self.assertEqual(len({r["id"] for r in rows}), count)
            for r in rows:
                self.assertTrue(r["id"].startswith(slug))
                self.assertEqual(r["ia_identifier"], classics.SOURCES[slug]["ia"])
                self.assertIn(f"/{r['ia_identifier']}/", r["audio_url"])

    def test_provenance_records_text_edition(self):
        for slug in ("spurgeon", "edwards"):
            prov = json.loads(manifest.MANIFEST.with_name(f"{slug}.provenance.json").read_text())
            edition = prov["text_edition"]
            self.assertTrue(edition["note"])
            self.assertTrue(edition["librivox_url_text_source"].startswith("https://"))
            for r in manifest.load(manifest.MANIFEST.with_name(f"{slug}.jsonl")):
                self.assertEqual(r["text_source_url"], edition["librivox_url_text_source"])

    def test_talmage_is_not_shipped(self):
        self.assertNotIn("talmage", classics.SOURCES)
        self.assertFalse(manifest.MANIFEST.with_name("talmage.jsonl").exists())
        self.assertFalse(manifest.MANIFEST.with_name("talmage.provenance.json").exists())
        questions = (ROOT / "eval" / "classics_smoke.jsonl").read_text()
        self.assertNotIn("talmage", questions)

    def test_clean_title(self):
        self.assertEqual(classics.clean_title("03 - Christ's Agony, pt. 2"), "Christ's Agony, pt 2")

    def test_library_paths_are_passed_not_rebound(self):
        import fetch
        import transcribe

        before = (fetch.AUDIO_DIR, transcribe.TRANSCRIPT_DIR)
        paths = run.library_paths("spurgeon")
        self.assertEqual(paths.manifest, manifest.MANIFEST.with_name("spurgeon.jsonl"))
        self.assertEqual(paths.audio_dir, fetch.CACHE_ROOT / "audio" / "spurgeon")
        self.assertEqual(paths.transcript_dir, transcribe.CACHE_ROOT / "transcripts" / "spurgeon")
        self.assertEqual(paths.log, paths.transcript_dir / "progress.log")
        self.assertEqual((fetch.AUDIO_DIR, transcribe.TRANSCRIPT_DIR), before)  # no module globals touched
        wesley = run.library_paths(None)
        self.assertEqual((wesley.manifest, wesley.audio_dir, wesley.transcript_dir),
                         (manifest.MANIFEST, fetch.AUDIO_DIR, transcribe.TRANSCRIPT_DIR))
        row = manifest.load(paths.manifest)[0]
        self.assertEqual(fetch.audio_path(row, paths.audio_dir).parent, paths.audio_dir.resolve())
        self.assertEqual(run.out_path(row, paths.transcript_dir).parent, paths.transcript_dir.resolve())
        with self.assertRaises(SystemExit):
            run.library_paths("../x")


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
