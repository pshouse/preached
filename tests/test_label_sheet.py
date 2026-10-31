"""The blind label sheet: reproducible from the KEY's seed, no leaking tags."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("make_label_sheet", ROOT / "scripts" / "make_label_sheet.py")
gen = importlib.util.module_from_spec(_spec)
sys.modules["make_label_sheet"] = gen
_spec.loader.exec_module(gen)

FORBIDDEN = re.compile(r"blind|held-out|heldout|split|grade|rank|hit|bm25|dense|hybrid", re.I)
TEXT_COLUMNS = {"question", "chunk text"}


class LabelSheetTest(unittest.TestCase):
    def test_regenerates_byte_for_byte_from_key_seed(self):
        sheet, key, bad = gen.build()
        self.assertEqual(bad, [])
        committed = gen.SHEET.read_bytes()
        self.assertEqual(hashlib.sha256(sheet.encode()).hexdigest(), hashlib.sha256(committed).hexdigest())
        self.assertEqual(key.encode(), gen.KEY.read_bytes())
        self.assertIn(f"`{gen.SEED}`", gen.KEY.read_text(encoding="utf-8"))

    def test_no_leaking_tags_outside_question_and_chunk_text(self):
        rows = list(csv.reader(io.StringIO(gen.SHEET.read_text(encoding="utf-8"), newline="")))
        header, body = rows[0], rows[1:]
        self.assertEqual(header, gen.HEADER)
        self.assertEqual(len(body), 24)
        self.assertIsNone(FORBIDDEN.search(",".join(header)))
        for row in body:
            for name, value in zip(header, row):
                if name not in TEXT_COLUMNS:
                    self.assertIsNone(FORBIDDEN.search(value), (name, value))
            self.assertEqual(row[5:], ["", ""])
            self.assertRegex(row[0], r"^L\d\d$")
            self.assertRegex(row[1], r"^Q\d\d$")


if __name__ == "__main__":
    unittest.main()
