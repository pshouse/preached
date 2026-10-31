"""scripts/bench_api.py must follow the eval file, not a fixed question count."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location("bench_api", ROOT / "scripts" / "bench_api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BenchApiQueryTests(unittest.TestCase):
    def test_queries_match_every_row_of_the_real_eval_file(self) -> None:
        rows = [json.loads(line) for line in (ROOT / "eval" / "questions.jsonl").read_text().splitlines() if line.strip()]
        self.assertEqual(load_module().queries(), [row["query"] for row in rows])

    def test_any_count_is_accepted(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "q.jsonl"
            for n in (1, 7, 93, 150):
                path.write_text("".join(json.dumps({"id": f"q{i}", "query": f"query {i}"}) + "\n" for i in range(n)))
                self.assertEqual(len(module.queries(path)), n)

    def test_duplicate_ids_and_empty_queries_are_refused(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "q.jsonl"
            path.write_text('{"id": "a", "query": "x"}\n{"id": "a", "query": "y"}\n')
            with self.assertRaises(SystemExit):
                module.queries(path)
            path.write_text('{"id": "a", "query": " "}\n')
            with self.assertRaises(SystemExit):
                module.queries(path)


if __name__ == "__main__":
    unittest.main()
