"""search/bench.py must exit non-zero when an enabled model cannot load.

Nothing here downloads or writes outside a temp dir: the heavy steps are mocked.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_bench():
    spec = importlib.util.spec_from_file_location("bench_failclosed_under_test", ROOT / "search" / "bench.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BenchFailClosedTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        env = mock.patch.dict(os.environ, {
            "HF_HUB_OFFLINE": "1",
            "HF_HOME": str(self.tmp / "hf"),
            "PREACHED_CACHE": str(self.tmp / "cache"),
        })
        env.start()
        self.addCleanup(env.stop)
        self.bench = load_bench()
        self.key = next(k for k, s in self.bench.MODELS.items() if s.enabled)

    @staticmethod
    def memory_index() -> sqlite3.Connection:
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE chunks (sermon_title, scripture, text)")
        connection.execute("INSERT INTO chunks VALUES ('t', 's', 'x')")
        return connection

    def run_main(self, *extra: str, load_fails: bool) -> tuple[int, str]:
        b = self.bench
        stats = {k: {"mean": 0.5} for k in b.METRICS}
        result = {"cpu_dtype": "fp32", "per_query": {m: {} for m in b.MODES}, "negative_top1": {}}
        latency = {m: {"p50_ms": 1.0} for m in b.MODES}
        embed = mock.Mock(side_effect=OSError("offline: cannot load model")) if load_fails else mock.Mock(return_value={})
        patches = [
            mock.patch.object(b, "connect", lambda _p: self.memory_index()),
            mock.patch.object(b, "ensure_chunks", lambda *_a, **_k: 3),
            mock.patch.object(b, "load_questions", lambda *_a, **_k: [{"id": "q", "query": "x", "relevant": [{}]}]),
            mock.patch.object(b, "question_groups", lambda _q: {"plain": ["q"]}),
            mock.patch.object(b, "environment", lambda: {}),
            mock.patch.object(b, "Searcher", mock.Mock()),
            mock.patch.object(b, "evaluate", lambda *_a, **_k: {"per_query": {"bm25": {}}, "negative_top1": {"bm25": {}}}),
            mock.patch.object(b, "by_group", lambda *_a: {}),
            mock.patch.object(b, "markdown", lambda _r: "md\n"),
            mock.patch.object(b, "describe_prompts", lambda _s: {}),
            mock.patch.object(b, "cache_matches", lambda *_a, **_k: False),
            mock.patch.object(b, "embed_corpus", embed),
            mock.patch.object(b, "cpu_eval", lambda *_a, **_k: (result, latency)),
            mock.patch.object(b, "embedding_bytes", lambda *_a: 0),
            mock.patch.object(b, "summarize", lambda _pq: stats),
            mock.patch.object(b.sys, "argv", ["bench.py", "--models", self.key, "--results-dir", str(self.tmp / "out"),
                                              "--out", str(self.tmp / "out" / "r.json"), *extra]),
        ]
        (self.tmp / "out").mkdir()
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            try:
                b.main()
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        return code, out.getvalue() + err.getvalue()

    def test_model_load_failure_exits_nonzero(self) -> None:
        code, text = self.run_main(load_fails=True)
        self.assertEqual(code, 1)
        self.assertIn("cannot load model", text)
        self.assertIn("--allow-bm25-only", text)

    def test_allow_bm25_only_proceeds_with_loud_warning(self) -> None:
        code, text = self.run_main("--allow-bm25-only", load_fails=True)
        self.assertEqual(code, 0)
        self.assertIn("WARNING: --allow-bm25-only", text)
        self.assertTrue((self.tmp / "out" / "r.json").exists())

    def test_normal_path_exits_zero_without_warning(self) -> None:
        code, text = self.run_main(load_fails=False)
        self.assertEqual(code, 0)
        self.assertNotIn("WARNING", text)
        self.assertNotIn("error:", text)
        self.assertTrue((self.tmp / "out" / "r.json").exists())


if __name__ == "__main__":
    unittest.main()
