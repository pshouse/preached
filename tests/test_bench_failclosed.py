"""search/bench.py must exit non-zero when an enabled model cannot load.

Nothing here downloads or writes outside a temp dir: the heavy steps are mocked.
"""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import contextlib
import importlib.util
import io
import json
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

    def run_main(self, *extra: str, load_fails: bool, error: Exception | None = None,
                 abstain_fails: bool = False, calibration: Path | None = None) -> tuple[int, str, str]:
        b = self.bench
        stats = {k: {"mean": 0.5} for k in b.METRICS}
        result = {"cpu_dtype": "fp32", "per_query": {m: {} for m in b.MODES}, "negative_top1": {}}
        latency = {m: {"p50_ms": 1.0} for m in b.MODES}
        failure = error or OSError("offline: cannot load model")
        embed = mock.Mock(side_effect=failure) if load_fails else mock.Mock(return_value={})
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
            mock.patch.object(b, "abstain_markdown", lambda _r: "md\n"),
            mock.patch.object(b, "describe_prompts", lambda _s: {}),
            mock.patch.object(b, "cache_matches", lambda *_a, **_k: False),
            mock.patch.object(b, "embed_corpus", embed),
            mock.patch.object(b, "cpu_eval", lambda *_a, **_k: (result, latency)),
            mock.patch.object(b, "embedding_bytes", lambda *_a: 0),
            mock.patch.object(b, "summarize", lambda _pq: stats),
            mock.patch.object(b.sys, "argv", ["bench.py", "--models", self.key, "--results-dir", str(self.tmp / "out"),
                                              "--out", str(self.tmp / "out" / "r.json"), *extra]),
        ]
        if abstain_fails:
            patches.append(mock.patch.object(b, "stored_fingerprint", mock.Mock(side_effect=failure)))
        if calibration is not None:
            patches.append(mock.patch.object(b.abstain, "calibration_path", lambda: calibration))
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
        return code, out.getvalue(), err.getvalue()

    def report(self) -> dict:
        return json.loads((self.tmp / "out" / "r.json").read_text())

    def test_model_load_failure_exits_nonzero(self) -> None:
        code, out, err = self.run_main(load_fails=True)
        self.assertEqual(code, 1)
        self.assertIn("cannot load model", err)
        self.assertIn("--allow-bm25-only", err)
        # The report is written before the exit, and records the model as not ok.
        self.assertEqual(self.report()["models"][self.key]["status"], "error")

    def test_gated_model_still_fails_closed(self) -> None:
        code, out, err = self.run_main(load_fails=True, error=OSError("401 gated repo"))
        self.assertEqual(code, 1)
        self.assertIn("skipped_gated", err)
        self.assertIn(self.key, err)
        self.assertIn("--allow-bm25-only", err)
        self.assertEqual(self.report()["models"][self.key]["status"], "skipped_gated")

    def test_allow_bm25_only_proceeds_with_loud_warning(self) -> None:
        code, out, err = self.run_main("--allow-bm25-only", load_fails=True)
        self.assertEqual(code, 0)
        self.assertIn("WARNING: --allow-bm25-only", err)
        self.assertNotIn("WARNING", out)
        self.assertNotEqual(self.report()["models"][self.key]["status"], "ok")

    def test_normal_path_exits_zero_without_warning(self) -> None:
        code, out, err = self.run_main(load_fails=False)
        self.assertEqual(code, 0)
        self.assertNotIn("WARNING", out + err)
        self.assertNotIn("error:", out + err)
        self.assertEqual(self.report()["models"][self.key]["status"], "ok")

    def test_abstain_failure_exits_nonzero_after_report(self) -> None:
        code, out, err = self.run_main("--abstain", load_fails=False, abstain_fails=True)
        self.assertEqual(code, 1)
        self.assertIn(self.key, err)
        self.assertIn("--allow-bm25-only", err)
        self.assertEqual(self.report()["models"][self.key]["status"], "error")

    def test_abstain_gated_is_plain_error_and_fails(self) -> None:
        code, out, err = self.run_main("--abstain", load_fails=False, abstain_fails=True,
                                       error=OSError("401 gated repo"))
        self.assertEqual(code, 1)
        self.assertEqual(self.report()["models"][self.key]["status"], "error")
        self.assertNotIn("skipped_gated", err)

    def test_abstain_allow_bm25_only_warns_on_stderr(self) -> None:
        code, out, err = self.run_main("--abstain", "--allow-bm25-only", load_fails=False, abstain_fails=True)
        self.assertEqual(code, 0)
        self.assertIn("WARNING: --allow-bm25-only", err)
        self.assertNotIn("WARNING", out)
        self.assertNotEqual(self.report()["models"][self.key]["status"], "ok")

    def test_abstain_write_calibration_leaves_failed_model_entry_untouched(self) -> None:
        b = self.bench
        path = self.tmp / "abstain.toml"
        entry = {"model": self.key, "backend": "torch", "variant": "fp32", "dense_floor": 0.4321,
                 "fingerprint": "f" * 16, "query_fingerprint": "q" * 16, "fitted_on": "old", "results": "old.json"}
        path.write_text(b.abstain.calibration_toml([entry]))
        before = path.read_text()
        code, out, err = self.run_main("--abstain", "--write-calibration", load_fails=False,
                                       abstain_fails=True, calibration=path)
        self.assertEqual(code, 1)
        self.assertEqual(path.read_text(), before)
        self.assertEqual(b.abstain.load_calibrations(path), [entry])


if __name__ == "__main__":
    unittest.main()
