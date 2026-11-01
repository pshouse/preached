"""eval/apply_grades.py must not delete Patrick's confirmed labels when it re-applies grades (CTO #50 MF3)."""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("eval_apply_grades", ROOT / "eval" / "apply_grades.py")
apply_grades = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(apply_grades)

CONFIRMED = {"passage_id": "p-x-conf-01", "grade": 2, "quote": "q", "chunk_ids": ["c"], "status": "confirmed",
             "found_by": "human:patrick-blind-w3", "sheet_row": "L08", "quote_source": "chunk-unique"}
PROPOSED = {"passage_id": "p-x-g2-01", "grade": 2, "quote": "q", "chunk_ids": ["c"], "status": "proposed"}


def question(qid: str, group: str, *labels: dict) -> dict:
    return {"id": qid, "query": "?", "type": "conceptual", "group": group, "relevant": list(labels)}


class ConfirmedLabelsSurviveTest(unittest.TestCase):
    def run_main(self, questions: list[dict], *argv: str) -> tuple[int, str, bytes, bytes, bool]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "questions.jsonl"
            path.write_text("".join(json.dumps(q) + "\n" for q in questions))
            before = path.read_bytes()
            out = StringIO()
            with patch.object(apply_grades, "questions_path", return_value=path), \
                    patch.object(apply_grades, "load_chunks", return_value={}) as load_chunks, \
                    patch.object(sys, "argv", ["apply_grades.py", tmp, *argv]), redirect_stdout(out):
                code = apply_grades.main()
            return code, out.getvalue(), before, path.read_bytes(), load_chunks.called

    def test_refuses_to_rewrite_over_a_confirmed_plain_blind_label(self):
        code, out, before, after, loaded = self.run_main([question("p-x", "plain-blind", PROPOSED, CONFIRMED)])
        self.assertEqual(code, 1)
        self.assertIn("refusing", out)
        self.assertIn("p-x p-x-conf-01", out)
        self.assertEqual(after, before)
        self.assertFalse(loaded)

    def test_check_still_runs_and_proposed_only_items_still_rewrite(self):
        code, _, before, after, loaded = self.run_main([question("p-x", "plain-blind", CONFIRMED)], "--check")
        self.assertEqual((code, after, loaded), (0, before, True))
        code, out, _, after, _ = self.run_main([question("p-x", "plain-blind", PROPOSED)])
        self.assertEqual(code, 0)
        self.assertNotIn("refusing", out)
        self.assertEqual(after, b"")  # no grade files: the plain-blind item and its proposal are rebuilt from nothing

    def test_confirmed_labels_on_other_groups_are_kept(self):
        kept = apply_grades.strip_applied([question("q-x", "plain", PROPOSED, CONFIRMED)])
        self.assertEqual(kept[0]["relevant"], [CONFIRMED])
        self.assertEqual(apply_grades.confirmed_plain_blind([question("q-x", "plain", CONFIRMED)]), [])

    def test_the_repo_has_a_confirmed_plain_blind_label_so_a_rerun_refuses(self):
        questions = [json.loads(line) for line in (ROOT / "eval" / "questions.jsonl").read_text().splitlines() if line.strip()]
        self.assertIn("p-013 p-013-conf-01", apply_grades.confirmed_plain_blind(questions))


if __name__ == "__main__":
    unittest.main()
