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
# Literal pins: a regenerated-from-itself sheet cannot hide a changed seed, shuffle or column set.
PINNED_SEED = 20261031
PINNED_SHEET_SHA256 = "6141beaaed326f48a12813b95cb812cccd14f8e4eea55632ca063100f5369b12"
PINNED_KEY_SHA256 = "892207b6a9c126ec4478488804ef42a8153808c53eb1b69d665b39cafdae3d21"  # gitleaks:allow
PINNED_HEADER = ["row id", "question id", "question", "chunk id", "chunk text", "verdict", "notes"]


class LabelSheetTest(unittest.TestCase):
    def test_regenerates_byte_for_byte_from_key_seed(self):
        sheet, key, bad = gen.build()
        self.assertEqual(bad, [])
        committed = gen.SHEET.read_bytes()
        self.assertEqual(hashlib.sha256(sheet.encode()).hexdigest(), hashlib.sha256(committed).hexdigest())
        self.assertEqual(key.encode(), gen.KEY.read_bytes())
        self.assertIn(f"`{gen.SEED}`", gen.KEY.read_text(encoding="utf-8"))

    def test_literal_pins_seed_sheet_hash_and_header(self):
        self.assertEqual(gen.SEED, PINNED_SEED)
        self.assertEqual(gen.HEADER, PINNED_HEADER)
        committed = gen.SHEET.read_bytes()
        self.assertEqual(hashlib.sha256(committed).hexdigest(), PINNED_SHEET_SHA256)
        self.assertEqual(hashlib.sha256(gen.KEY.read_bytes()).hexdigest(), PINNED_KEY_SHA256)
        self.assertEqual(next(csv.reader(io.StringIO(committed.decode("utf-8"), newline=""))), PINNED_HEADER)
        self.assertIn(f"`{PINNED_SEED}`", gen.KEY.read_text(encoding="utf-8"))

    def test_text_cells_match_source_exactly_and_hold_no_markup_or_hidden_chars(self):
        import json
        import unicodedata
        src = json.loads(gen.SOURCE.read_text(encoding="utf-8"))
        rows = list(csv.reader(io.StringIO(gen.SHEET.read_text(encoding="utf-8"), newline="")))[1:]
        self.assertEqual(sorted((r[2], r[4]) for r in rows), sorted((i["question"], i["chunk_text"]) for i in src))
        for row in rows:
            for value in row:
                self.assertNotIn("<!--", value)
                self.assertNotIn("-->", value)
                self.assertIsNone(re.search(r"</?[A-Za-z!?]", value), value[:60])
                for ch in value:
                    # space separators are fine; control/format/private/other and exotic spaces are not
                    cat = unicodedata.category(ch)
                    self.assertTrue(ch == " " or cat[0] not in "CZ", (hex(ord(ch)), value[:60]))

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
            self.assertRegex(row[3], r"^C\d\d$")

    def test_no_wesley_id_or_sermon_header_anywhere_in_sheet(self):
        raw = gen.SHEET.read_text(encoding="utf-8")
        self.assertNotRegex(raw, r"(?i)wesley-\d")
        self.assertNotRegex(raw, r"c\d{4}")
        rows = list(csv.reader(io.StringIO(raw, newline="")))[1:]
        for row in rows:
            self.assertNotRegex(row[2] + row[4], r"(?i)wesley-\d")
            self.assertFalse(re.match(r"\s*(\d+\s|sermon\b|upon our lord)", row[4], re.I), row[4][:40])

    def test_chunk_ids_opaque_and_one_per_chunk(self):
        import json
        src = json.loads(gen.SOURCE.read_text(encoding="utf-8"))
        rows = list(csv.reader(io.StringIO(gen.SHEET.read_text(encoding="utf-8"), newline="")))[1:]
        by_text = {}
        for row in rows:
            by_text.setdefault(row[4], set()).add(row[3])
        self.assertTrue(all(len(v) == 1 for v in by_text.values()))
        cids = sorted({r[3] for r in rows})
        self.assertEqual(cids, [f"C{i:02d}" for i in range(1, len(by_text) + 1)])
        self.assertEqual(len(by_text), len({it["chunk_id"] for it in src}))
        # ids follow the shuffled order, not the sermon number
        firsts = []
        for r in rows:
            if r[3] not in firsts:
                firsts.append(r[3])
        self.assertEqual(firsts, cids)

    def test_row_order_is_the_seeded_shuffle_of_the_source(self):
        import json
        import random
        src = json.loads(gen.SOURCE.read_text(encoding="utf-8"))
        order = list(range(len(src)))
        random.Random(PINNED_SEED).shuffle(order)
        rows = list(csv.reader(io.StringIO(gen.SHEET.read_text(encoding="utf-8"), newline="")))[1:]
        self.assertEqual([(r[2], r[4]) for r in rows], [(src[i]["question"], src[i]["chunk_text"]) for i in order])
        # the KEY's "orig #" column (1-based position in the source) lists the same order
        key_rows = [line.split(" | ") for line in gen.KEY.read_text(encoding="utf-8").splitlines() if re.match(r"\| L\d\d \|", line)]
        self.assertEqual([int(k[4]) for k in key_rows], [i + 1 for i in order])
        self.assertEqual([k[0].lstrip("| ") for k in key_rows], [r[0] for r in rows])


if __name__ == "__main__":
    unittest.main()
