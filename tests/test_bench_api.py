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
    def write(self, text: str) -> Path:
        path = Path(self._tmp.name) / "q.jsonl"
        path.write_text(text)
        return path

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.module = load_module()

    def test_queries_match_every_row_of_the_real_eval_file(self) -> None:
        rows = [json.loads(line) for line in (ROOT / "eval" / "questions.jsonl").read_text().splitlines() if line.strip()]
        found = self.module.queries()
        self.assertEqual(found, [(row["id"], row["query"]) for row in rows])
        ids = [i for i, _ in found]
        self.assertEqual(len(ids), len(set(ids)))
        for row_id, query in found:
            self.assertIsInstance(row_id, str)
            self.assertTrue(row_id.strip())
            self.assertIsInstance(query, str)
            self.assertTrue(query.strip())

    def test_any_count_is_accepted(self) -> None:
        for n in (1, 7, 93, 150):
            path = self.write("".join(json.dumps({"id": f"q{i}", "query": f"query {i}"}) + "\n" for i in range(n)))
            self.assertEqual(len(self.module.queries(path)), n)

    def test_bad_rows_are_refused_with_path_and_line(self) -> None:
        good = '{"id": "a", "query": "x"}\n'
        cases = {
            "duplicate id": good + '{"id": "a", "query": "y"}\n',
            "empty query": '{"id": "a", "query": " "}\n',
            "missing id": '{"query": "x"}\n',
            "empty id": '{"id": "", "query": "x"}\n',
            "int id": '{"id": 1, "query": "x"}\n',
            "list id": '{"id": ["a"], "query": "x"}\n',
            "non-object row": good + '["a", "x"]\n',
            "bad json": good + "{not json\n",
            "no rows": "\n",
        }
        for name, text in cases.items():
            with self.subTest(name):
                path = self.write(text)
                with self.assertRaises(SystemExit) as ctx:
                    self.module.queries(path)
                self.assertIn(str(path), str(ctx.exception))

    def test_int_and_string_ids_are_not_both_accepted(self) -> None:
        path = self.write('{"id": 1, "query": "x"}\n{"id": "1", "query": "y"}\n')
        with self.assertRaises(SystemExit):
            self.module.queries(path)

    def test_hash_covers_ids_and_query_boundaries(self) -> None:
        h = self.module.queries_sha256
        self.assertNotEqual(h([("a", "x\ny")]), h([("a", "x"), ("b", "y")]))
        self.assertNotEqual(h([("a", "x")]), h([("b", "x")]))
        self.assertEqual(h([("a", "x")]), h([("a", "x")]))


if __name__ == "__main__":
    unittest.main()
