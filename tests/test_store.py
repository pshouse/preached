"""Index sync (content hash, legacy-index migration) and the query-time
embedding fingerprint check."""

from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from preached.models import MODELS
from preached.search import Searcher
from preached.store import (
    CHUNK_COLUMNS,
    EmbeddingMismatch,
    connect,
    load_chunk_rows,
    replace_chunks,
    save_embedding_info,
    sync_chunks,
    write_embeddings,
)


def make_chunks(n: int = 3) -> list[dict]:
    return [
        {
            "chunk_id": f"wesley-001-{i:03d}",
            "sermon_id": "wesley-001",
            "sermon_title": "Salvation by Faith",
            "text": f"By grace are ye saved through faith, part {i}.",
            "start_s": None,
            "end_s": None,
            "sermon_number": 1,
            "scripture": "Eph 2:8",
            "source_url": "https://www.ccel.org/ccel/wesley/sermons.v.i.html",
            "word_count": 9,
            "word_start": 9 * i,
            "word_end": 9 * i + 9,
            "librivox_id": None,
        }
        for i in range(n)
    ]


def write_jsonl(path: Path, chunks: list[dict]) -> None:
    path.write_text("".join(json.dumps(c) + "\n" for c in chunks))


class SyncChunksTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.jsonl = self.dir / "chunks.jsonl"
        self.connection = connect(self.dir / "index.sqlite")

    def tearDown(self) -> None:
        self.connection.close()
        self._tmp.cleanup()

    def build_legacy_index(self, chunks: list[dict]) -> None:
        """An index as 7347eb7 built it: chunks and vectors, no chunks_sha256."""
        replace_chunks(self.connection, chunks)
        rowids = [int(r["rowid"]) for r in load_chunk_rows(self.connection)]
        write_embeddings(self.connection, "m", rowids, np.eye(len(rowids), 4, dtype=np.float32))
        self.assertIsNone(
            self.connection.execute("SELECT value FROM meta WHERE key = 'chunks_sha256'").fetchone()
        )

    def test_columns_match_schema(self) -> None:
        cols = [r[1] for r in self.connection.execute("PRAGMA table_info(chunks)") if r[1] != "rowid"]
        self.assertEqual(tuple(cols), CHUNK_COLUMNS)

    def test_legacy_index_with_new_timing_is_rebuilt(self) -> None:
        # CTO's repro: same text, chunk 0 gains start_s/end_s (the W1-C flow).
        chunks = make_chunks()
        self.build_legacy_index(chunks)
        aligned = [dict(c) for c in chunks]
        aligned[0]["start_s"], aligned[0]["end_s"] = 12.5, 31.0
        write_jsonl(self.jsonl, aligned)
        self.assertEqual(sync_chunks(self.connection, self.jsonl), 3)
        row = load_chunk_rows(self.connection)[0]
        self.assertEqual((row["start_s"], row["end_s"]), (12.5, 31.0))
        # Rowids changed, so the old vectors and their fingerprints are gone.
        self.assertEqual(self.connection.execute("SELECT count(*) FROM embeddings").fetchone()[0], 0)
        # And a second sync is a no-op that keeps the timing.
        self.assertEqual(sync_chunks(self.connection, self.jsonl), 3)
        self.assertEqual(load_chunk_rows(self.connection)[0]["start_s"], 12.5)

    def test_legacy_index_with_other_field_change_is_rebuilt(self) -> None:
        chunks = make_chunks()
        self.build_legacy_index(chunks)
        changed = [dict(c) for c in chunks]
        changed[2]["librivox_id"] = "sermons_wesley_01"
        write_jsonl(self.jsonl, changed)
        sync_chunks(self.connection, self.jsonl)
        self.assertEqual(load_chunk_rows(self.connection)[2]["librivox_id"], "sermons_wesley_01")

    def test_identical_legacy_index_is_adopted_with_vectors(self) -> None:
        chunks = make_chunks()
        self.build_legacy_index(chunks)
        write_jsonl(self.jsonl, chunks)
        self.assertEqual(sync_chunks(self.connection, self.jsonl), 3)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM embeddings").fetchone()[0], 3)
        self.assertIsNotNone(
            self.connection.execute("SELECT value FROM meta WHERE key = 'chunks_sha256'").fetchone()
        )

    def test_hashed_index_picks_up_timing_only_change(self) -> None:
        chunks = make_chunks()
        write_jsonl(self.jsonl, chunks)
        sync_chunks(self.connection, self.jsonl)
        aligned = [dict(c) for c in chunks]
        aligned[1]["start_s"], aligned[1]["end_s"] = 40.0, 52.25
        write_jsonl(self.jsonl, aligned)
        sync_chunks(self.connection, self.jsonl)
        row = load_chunk_rows(self.connection)[1]
        self.assertEqual((row["start_s"], row["end_s"]), (40.0, 52.25))


class FingerprintCheckTests(unittest.TestCase):
    KEY = "granite-english-r2"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        path = Path(self._tmp.name)
        jsonl = path / "chunks.jsonl"
        write_jsonl(jsonl, make_chunks())
        self.connection = connect(path / "index.sqlite")
        sync_chunks(self.connection, jsonl)
        rowids = [int(r["rowid"]) for r in load_chunk_rows(self.connection)]
        write_embeddings(self.connection, self.KEY, rowids, np.eye(3, 4, dtype=np.float32))
        self.spec = MODELS[self.KEY]

    def tearDown(self) -> None:
        self.connection.close()
        self._tmp.cleanup()

    def test_matching_fingerprint_loads(self) -> None:
        save_embedding_info(self.connection, self.KEY, {"fingerprint": self.spec.fingerprint()})
        searcher = Searcher(self.connection, model=self.KEY)
        hits = searcher.dense(np.array([1, 0, 0, 0], dtype=np.float32), 1)
        self.assertEqual(hits[0].chunk_id, "wesley-001-000")

    def test_revision_bump_without_reembed_is_refused(self) -> None:
        save_embedding_info(self.connection, self.KEY, {"fingerprint": self.spec.fingerprint()})
        bumped = dataclasses.replace(self.spec, revision="0" * 40).fingerprint()
        with self.assertRaises(EmbeddingMismatch) as ctx:
            Searcher(self.connection, model=self.KEY, fingerprint=bumped)
        self.assertIn("bench.py --models granite-english-r2", str(ctx.exception))

    def test_missing_fingerprint_is_refused(self) -> None:
        with self.assertRaises(EmbeddingMismatch) as ctx:
            Searcher(self.connection, model=self.KEY)
        self.assertIn("none recorded", str(ctx.exception))

    def test_bm25_needs_no_fingerprint(self) -> None:
        self.assertTrue(Searcher(self.connection).bm25("grace", 3))

    def test_unknown_model_is_refused(self) -> None:
        with self.assertRaises(RuntimeError):
            Searcher(self.connection, model="no-such-model")


if __name__ == "__main__":
    unittest.main()
