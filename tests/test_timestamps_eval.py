"""eval/timestamps.py: a chunk with no file id never matches a gold span."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


class JudgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("eval_timestamps", ROOT / "eval" / "timestamps.py")
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def test_missing_file_id_does_not_match(self) -> None:
        span = {"file_id": "f1", "start_s": 10.0, "end_s": 20.0}
        hit = SimpleNamespace(start_s=12.0, end_s=40.0)
        self.assertEqual(self.mod.judge(hit, None, span), {"inside": False, "overlap": False, "lead_s": None})

    def test_same_file_matches_and_other_file_does_not(self) -> None:
        span = {"file_id": "f1", "start_s": 10.0, "end_s": 20.0}
        hit = SimpleNamespace(start_s=12.0, end_s=40.0)
        got = self.mod.judge(hit, "f1", span)
        self.assertTrue(got["inside"] and got["overlap"])
        self.assertEqual(got["lead_s"], -2.0)
        self.assertFalse(self.mod.judge(hit, "f2", span)["overlap"])


if __name__ == "__main__":
    unittest.main()
