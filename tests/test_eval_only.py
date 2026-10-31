"""Eval-only models (Arctic): the benchmark may score them, the product never loads them."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "search") not in sys.path:
    sys.path.insert(0, str(ROOT / "search"))

from preached.models import MODELS
from preached.search import Searcher
from preached.store import connect, save_embedding_info, write_embeddings

TEXTS = {
    "a": ("s1", "grace alone saves the sinner through faith"),
    "b": ("s2", "the love of money is the root of every evil"),
}


def arctic_index(path: Path):
    connection = connect(path)
    for chunk_id, (sermon, text) in TEXTS.items():
        connection.execute(
            "INSERT INTO chunks (chunk_id, sermon_id, sermon_title, text, word_count) VALUES (?, ?, ?, ?, ?)",
            (chunk_id, sermon, sermon, text, len(text.split())),
        )
    connection.commit()
    rowids = [int(r[0]) for r in connection.execute("SELECT rowid FROM chunks ORDER BY rowid")]
    write_embeddings(connection, "arctic-embed-l", rowids, np.array([[1, 0], [0, 1]], dtype=np.float32))
    save_embedding_info(connection, "arctic-embed-l", {"fingerprint": MODELS["arctic-embed-l"].fingerprint()})
    return connection


class BenchArcticTests(unittest.TestCase):
    def test_cpu_eval_scores_arctic_without_weights(self) -> None:
        import bench

        questions = [{
            "id": "q1", "query": "grace alone",
            "relevant": [{"quote": "grace alone saves the sinner", "grade": 2, "sermon_id": "s1"}],
        }]
        with tempfile.TemporaryDirectory() as tmp:
            connection = arctic_index(Path(tmp) / "i.db")
            with patch("preached.embed.load_model", side_effect=AssertionError("no weights")):
                result, latency = bench.cpu_eval(
                    MODELS["arctic-embed-l"], connection, questions,
                    encode=lambda _q: np.array([1, 0], dtype=np.float32), dtype_label="stub",
                )
            connection.close()
        self.assertEqual(result["per_query"]["dense"]["q1"]["sermon@5"], 1.0)
        self.assertEqual(latency["dense"]["n"], 1)

    def test_searcher_needs_the_explicit_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            connection = arctic_index(Path(tmp) / "i.db")
            with self.assertRaisesRegex(RuntimeError, "eval-only"):
                Searcher(connection, model="arctic-embed-l")
            Searcher(connection, model="arctic-embed-l", allow_eval_only=True)
            connection.close()


class FlagScanTests(unittest.TestCase):
    def test_flag_stays_out_of_the_product(self) -> None:
        allowed = {ROOT / "src" / "preached" / "search.py"}
        product = [*sorted((ROOT / "app").rglob("*.py")), ROOT / "search" / "query.py",
                   *sorted((ROOT / "src" / "preached").rglob("*.py"))]
        self.assertTrue(product)
        hits = [str(p.relative_to(ROOT)) for p in product
                if p not in allowed and "allow_eval_only" in p.read_text()]
        self.assertEqual(hits, [])
        self.assertIn("allow_eval_only", (ROOT / "src" / "preached" / "search.py").read_text())
        self.assertIn("allow_eval_only=True", (ROOT / "search" / "bench.py").read_text())
