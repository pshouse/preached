"""scripts/synthetic_sermon.py makes audio and words the coverage gate accepts."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from preached.youtube.coverage import check_coverage  # noqa: E402
from preached.youtube.words import Word  # noqa: E402

spec = importlib.util.spec_from_file_location("synthetic_sermon", ROOT / "scripts" / "synthetic_sermon.py")
synthetic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(synthetic)


class SyntheticSermonTests(unittest.TestCase):
    def test_pair_has_no_open_span_and_a_dropped_stretch_does(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wav, transcript = synthetic.write(Path(tmp), "probe-1", 60.0, "one two three")
            words = [Word(a, b, t) for a, b, t in json.loads(transcript.read_text())["segments"][0]["words"]]
            self.assertGreater(len(words), 100)
            self.assertEqual(check_coverage(wav, words, duration_s=60.0), [])
            kept = [w for w in words if not 20 <= w.start < 60]  # the gate is live, not a stub
            self.assertTrue(check_coverage(wav, kept, duration_s=60.0))

    def test_default_output_is_unchanged_and_jitter_is_seeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp)
            wav, transcript = synthetic.write(a / "a", "p", 30.0, "one two three")
            words = json.loads(transcript.read_text())["segments"][0]["words"]
            self.assertEqual(words[:3], [[1.0, 1.3, "one"], [1.5, 1.8, "two"], [2.0, 2.3, "three"]])
            same = synthetic.write(a / "b", "p", 30.0, "one two three", jitter_seed=None)
            self.assertEqual(wav.read_bytes(), same[0].read_bytes())
            j1 = synthetic.write(a / "c", "p", 120.0, "x y", jitter_seed=3)
            j2 = synthetic.write(a / "d", "p", 120.0, "x y", jitter_seed=3)
            j3 = synthetic.write(a / "e", "p", 120.0, "x y", jitter_seed=4)
            self.assertEqual(j1[0].read_bytes(), j2[0].read_bytes())
            self.assertEqual(j1[1].read_text(), j2[1].read_text())
            self.assertNotEqual(j1[1].read_text(), j3[1].read_text())
            jw = [Word(x, y, t) for x, y, t in json.loads(j1[1].read_text())["segments"][0]["words"]]
            gaps = [n.start - o.end for o, n in zip(jw, jw[1:])]
            self.assertGreater(max(gaps), 1.0)  # a pause
            self.assertGreater(len({round(g, 2) for g in gaps}), 5)
            self.assertEqual(check_coverage(j1[0], jw, duration_s=120.0), [])

    def test_caller_timings_are_used_and_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wav, transcript = synthetic.write(Path(tmp), "p", 10.0, "a b", timings=[[1, 1.4], [2, 2.2, "grace"], [5, 6]])
            words = json.loads(transcript.read_text())["segments"][0]["words"]
            self.assertEqual(words, [[1.0, 1.4, "a"], [2.0, 2.2, "grace"], [5.0, 6.0, "a"]])
            with self.assertRaises(ValueError):
                synthetic.build(10.0, "a", timings=[[3, 4], [2, 2.5]])


if __name__ == "__main__":
    unittest.main()
