"""scripts/bench_api.py must follow the eval file, not a fixed question count."""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
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

    def test_u2028_inside_a_query_does_not_split_the_row(self) -> None:
        row = {"id": "a", "query": "before\u2028after\x85end"}
        path = self.write(json.dumps(row, ensure_ascii=False) + '\n{"id": "b", "query": "y"}\n')
        self.assertEqual(self.module.queries(path), [("a", row["query"]), ("b", "y")])


FAKE_SERVER = r"""
import json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
open(os.environ["FAKE_ENV_OUT"], "w").write(json.dumps({k: os.environ.get(k) for k in ("PREACHED_RATE_LIMIT", "PREACHED_GLOBAL_RATE_LIMIT")}))
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        if self.path.startswith("/healthz"):
            self.reply(200, {"dense": True, "model": "m", "backend": "b", "chunks": 1})
        elif os.environ.get("FAKE_MODE") == "429":
            self.reply(429, {"error": "rate limited"})
        else:
            self.reply(200, {"mode": "hybrid"})
srv = HTTPServer(("127.0.0.1", 0), H)
print("PREACHED_LISTENING 127.0.0.1:%d" % srv.server_address[1], flush=True)
srv.serve_forever()
"""


class BenchApiMainTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "app").mkdir()
        (self.root / "app" / "server.py").write_text(FAKE_SERVER)
        self.module = load_module()
        self.module.ROOT = self.root
        # tempfile caches its directory, so TMPDIR in run_main alone leaves the stderr file in the real one.
        patcher = mock.patch.object(tempfile, "tempdir", str(self.root))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.module.queries = lambda: [("a", "q")]
        self.env_out = self.root / "env.json"

    def run_main(self, env: dict[str, str]) -> tuple[str, str]:
        full = {"FAKE_ENV_OUT": str(self.env_out), "TMPDIR": str(self.root), **env}
        out, err = io.StringIO(), io.StringIO()
        base = {k: v for k, v in os.environ.items() if not k.startswith("PREACHED_")}
        with (
            mock.patch.dict(os.environ, {**base, **full}, clear=True),
            mock.patch.object(sys, "argv", ["bench_api.py"]),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            try:
                self.module.main()
                code = None
            except SystemExit as exc:
                code = str(exc)
        return out.getvalue(), code or ""

    def child_env(self) -> dict[str, str]:
        return json.loads(self.env_out.read_text())

    def test_unset_and_empty_rate_limits_are_lifted(self) -> None:
        for name, env in (("unset", {}), ("empty", {"PREACHED_RATE_LIMIT": "", "PREACHED_GLOBAL_RATE_LIMIT": "  "})):
            with self.subTest(name):
                out, code = self.run_main(env)
                self.assertEqual(code, "")
                self.assertEqual(self.child_env(), {"PREACHED_RATE_LIMIT": "1000000", "PREACHED_GLOBAL_RATE_LIMIT": "1000000"})
                self.assertEqual(json.loads(out)["n_queries"], 1)

    def test_explicit_rate_limit_is_kept(self) -> None:
        self.run_main({"PREACHED_RATE_LIMIT": "7"})
        self.assertEqual(self.child_env()["PREACHED_RATE_LIMIT"], "7")

    def test_http_error_exits_with_status_body_and_stderr_path(self) -> None:
        _, code = self.run_main({"FAKE_MODE": "429"})
        self.assertIn("HTTP 429", code)
        self.assertIn("rate limited", code)
        self.assertRegex(code, r"see \S*preached-bench-\S*\.stderr")
        for leftover in self.root.glob("preached-bench-*.stderr"):
            leftover.unlink()


if __name__ == "__main__":
    unittest.main()
