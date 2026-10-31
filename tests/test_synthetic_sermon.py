"""scripts/synthetic_sermon.py makes audio and words the coverage gate accepts."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
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

    def test_default_cli_output_is_pinned(self) -> None:
        # Golden digests of the CLI default (60 s, the fixed phrase). Any
        # change to the noise seed, rhythm or WAV/JSON layout shows up here.
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            synthetic.main([tmp])
            wav = (Path(tmp) / "probe-1.wav").read_bytes()
            transcript = (Path(tmp) / "probe-1.json").read_bytes()
        self.assertEqual(hashlib.sha256(wav).hexdigest(), "69e60c2ed2fa4b58ac961a6c6e108c6bba8d5e68379503218a42a649ceb85c69")
        self.assertEqual(hashlib.sha256(transcript).hexdigest(), "015b6e2a1e9758bb84e6e5f5e1fc34c1be6f1c247e0510df3db99713b3456bc9")

    def test_bad_timings_are_a_usage_error(self) -> None:
        bad = {
            "not json": "[[1, 2]",
            "not a list": '{"a": 1}',
            "not a pair": "[1, 2]",
            "too short": "[[1]]",
            "text time": '[["1", 2]]',
            "bool time": "[[true, 2]]",
            "empty word": '[[1, 2, " "]]',
            "out of order": "[[3, 4], [2, 2.5]]",
            "past the end": "[[1, 99]]",
        }
        with tempfile.TemporaryDirectory() as tmp:
            for name, text in bad.items():
                with self.subTest(name):
                    path = Path(tmp) / "t.json"
                    path.write_text(text)
                    out = Path(tmp) / name.replace(" ", "-")
                    err = io.StringIO()
                    with self.assertRaises(SystemExit) as caught, contextlib.redirect_stderr(err):
                        synthetic.main([str(out), "--seconds", "10", "--timings", str(path)])
                    self.assertEqual(caught.exception.code, 2)
                    self.assertIn("--timings", err.getvalue())
                    self.assertNotIn("Traceback", err.getvalue())
                    self.assertFalse(out.exists())
            err = io.StringIO()
            with self.assertRaises(SystemExit) as caught, contextlib.redirect_stderr(err):
                synthetic.main([tmp, "--timings", str(Path(tmp) / "missing.json")])
            self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
