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


if __name__ == "__main__":
    unittest.main()
