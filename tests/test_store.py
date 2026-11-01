"""Index sync (content hash, legacy-index migration) and the query-time
embedding fingerprint check."""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import dataclasses
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from preached.models import MODELS
from preached.search import Searcher
from preached.store import (
    CHUNK_COLUMNS,
    DuplicateChunkId,
    EmbeddingMismatch,
    NullTimingRefused,
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
        self.connection.commit()
        rowids = [int(r["rowid"]) for r in load_chunk_rows(self.connection)]
        write_embeddings(self.connection, "m", rowids, np.eye(len(rowids), 4, dtype=np.float32))
        self.assertIsNone(
            self.connection.execute("SELECT value FROM meta WHERE key = 'chunks_sha256'").fetchone()
        )

    def test_columns_match_schema(self) -> None:
        cols = [r[1] for r in self.connection.execute("PRAGMA table_info(chunks)") if r[1] != "rowid"]
        self.assertEqual(tuple(cols), CHUNK_COLUMNS)

    def test_legacy_index_with_new_timing_lands_and_keeps_vectors(self) -> None:
        # CTO's PR #2 repro: same text, chunk 0 gains start_s/end_s (the W1-C
        # flow). The timing must land; since ids and embedding inputs are
        # unchanged, it is updated in place and the vectors stay (PR #6 should-fix 1).
        chunks = make_chunks()
        self.build_legacy_index(chunks)
        aligned = [dict(c) for c in chunks]
        aligned[0]["start_s"], aligned[0]["end_s"] = 12.5, 31.0
        write_jsonl(self.jsonl, aligned)
        self.assertEqual(sync_chunks(self.connection, self.jsonl), 3)
        row = load_chunk_rows(self.connection)[0]
        self.assertEqual((row["start_s"], row["end_s"]), (12.5, 31.0))
        self.assertEqual(self.connection.execute("SELECT count(*) FROM embeddings").fetchone()[0], 3)
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


class InPlaceMetadataTests(unittest.TestCase):
    """PR #6 should-fix 1: a timing/audio-only change keeps vectors."""

    KEY = "granite-english-r2"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.jsonl = self.dir / "chunks.jsonl"
        self.chunks = make_chunks()
        write_jsonl(self.jsonl, self.chunks)
        self.connection = connect(self.dir / "index.sqlite")
        sync_chunks(self.connection, self.jsonl)
        self.rowids = [int(r["rowid"]) for r in load_chunk_rows(self.connection)]
        self.matrix = np.eye(3, 4, dtype=np.float32)
        write_embeddings(self.connection, self.KEY, self.rowids, self.matrix)
        save_embedding_info(self.connection, self.KEY, {"fingerprint": MODELS[self.KEY].fingerprint()})

    def tearDown(self) -> None:
        self.connection.close()
        self._tmp.cleanup()

    def resync(self, chunks: list[dict]) -> int:
        write_jsonl(self.jsonl, chunks)
        return sync_chunks(self.connection, self.jsonl)

    def vectors(self) -> int:
        return self.connection.execute("SELECT count(*) FROM embeddings").fetchone()[0]

    def test_timing_and_audio_update_in_place(self) -> None:
        aligned = [dict(c) for c in self.chunks]
        for i, chunk in enumerate(aligned):
            chunk.update(start_s=10.0 * i + 0.5, end_s=10.0 * i + 9.75,
                         audio_url="https://archive.org/download/x/y.mp3", reader="Reader", text_source="canonical")
        self.assertEqual(self.resync(aligned), 3)
        rows = load_chunk_rows(self.connection)
        self.assertEqual([int(r["rowid"]) for r in rows], self.rowids)
        self.assertEqual([(r["start_s"], r["end_s"]) for r in rows], [(0.5, 9.75), (10.5, 19.75), (20.5, 29.75)])
        self.assertEqual({r["reader"] for r in rows}, {"Reader"})
        # Vectors, their meta and the fingerprint check all survive.
        self.assertEqual(self.vectors(), 3)
        Searcher(self.connection, model=self.KEY)  # no EmbeddingMismatch
        # FTS still finds the rows after the UPDATE trigger ran.
        hits = self.connection.execute("SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH 'grace'").fetchone()[0]
        self.assertEqual(hits, 3)
        # The new hash is recorded: a second sync is a no-op.
        self.assertEqual(self.resync(aligned), 3)
        self.assertEqual(self.vectors(), 3)

    def test_text_change_drops_vectors(self) -> None:
        changed = [dict(c) for c in self.chunks]
        changed[1]["text"] += " Amended."
        self.resync(changed)
        self.assertEqual(self.vectors(), 0)
        self.assertEqual(load_chunk_rows(self.connection)[1]["text"], changed[1]["text"])
        with self.assertRaises(EmbeddingMismatch):
            Searcher(self.connection, model=self.KEY)

    def test_title_or_scripture_change_drops_vectors(self) -> None:
        # Both feed the document title the vectors were built with.
        for field, value in (("sermon_title", "Another"), ("scripture", "Rom 8:16")):
            changed = [dict(c) for c in self.chunks]
            changed[0][field] = value
            self.resync(changed)
            self.assertEqual(self.vectors(), 0, field)

    def test_reorder_or_new_id_drops_vectors(self) -> None:
        self.resync(list(reversed(self.chunks)))
        self.assertEqual(self.vectors(), 0)

    def test_duplicate_ids_are_refused_before_writing(self) -> None:
        dup = [dict(c) for c in self.chunks] + [dict(self.chunks[0], text="other")]
        with self.assertRaises(DuplicateChunkId):
            self.resync(dup)
        self.assertEqual(len(load_chunk_rows(self.connection)), 3)
        self.assertEqual(self.vectors(), 3)

    def test_null_timings_are_refused_unless_forced(self) -> None:
        # The live index hazard: chunks.jsonl matches ids and text and has
        # null start_s, end_s, audio_url, and reader. The in-place update
        # would keep the vectors and wipe every playable time.
        timed = [dict(c) for c in self.chunks]
        for index, chunk in enumerate(timed):
            chunk.update(
                start_s=10.0 + index,
                end_s=20.0 + index,
                audio_url="https://archive.org/download/x/y.mp3",
                reader="Reader",
            )
        self.assertEqual(self.resync(timed), 3)
        self.assertEqual(self.vectors(), 3)
        with self.assertRaises(NullTimingRefused):
            self.resync(self.chunks)
        row = load_chunk_rows(self.connection)[0]
        self.assertEqual(row["start_s"], 10.0)
        self.assertEqual(row["reader"], "Reader")
        self.assertEqual(self.vectors(), 3)
        bare_text = [dict(c) for c in self.chunks]
        bare_text[0]["text"] += " Amended."
        with self.assertRaises(NullTimingRefused):
            self.resync(bare_text)
        self.assertNotIn("Amended", load_chunk_rows(self.connection)[0]["text"])
        self.assertEqual(self.vectors(), 3)
        write_jsonl(self.jsonl, self.chunks)
        self.assertEqual(sync_chunks(self.connection, self.jsonl, force_null_timings=True), 3)
        wiped = load_chunk_rows(self.connection)[0]
        self.assertIsNone(wiped["start_s"])
        self.assertIsNone(wiped["audio_url"])
        self.assertIsNone(wiped["reader"])
        # Ids and embedding inputs still match, so the vectors stay.
        self.assertEqual(self.vectors(), 3)


# Runs under `python -I` (no PYTHONPATH, no user site), so it must put this
# checkout's src first itself and prove the import came from there: otherwise it
# would exercise whatever copy of `preached` the venv has installed (PR #9 review).
CRASH_SCRIPT = """
import os, sys
from pathlib import Path
src = Path(sys.argv[3]).resolve()
sys.path.insert(0, str(src))
import preached.store as store
if not Path(store.__file__).resolve().is_relative_to(src):
    sys.stderr.write(f"imported {store.__file__}, not this checkout's {src}\\n")
    os._exit(3)
store._after_replace = lambda: os._exit(7)
c = store.connect(Path(sys.argv[1]))
store.sync_chunks(c, Path(sys.argv[2]))
"""


class CrashWindowTests(unittest.TestCase):
    """PR #7 should-fix: a hard exit between the chunk replace and the hash /
    meta write must leave the index fully old, never half new."""

    KEY = "granite-english-r2"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.db = self.dir / "index.sqlite"
        self.jsonl = self.dir / "chunks.jsonl"
        self.old = make_chunks()
        write_jsonl(self.jsonl, self.old)
        self.connection = connect(self.db)
        sync_chunks(self.connection, self.jsonl)
        rowids = [int(r["rowid"]) for r in load_chunk_rows(self.connection)]
        write_embeddings(self.connection, self.KEY, rowids, np.eye(3, 4, dtype=np.float32))
        save_embedding_info(self.connection, self.KEY, {"fingerprint": MODELS[self.KEY].fingerprint()})
        self.old_hash = self.meta("chunks_sha256")

    def tearDown(self) -> None:
        self.connection.close()
        self._tmp.cleanup()

    def meta(self, key: str):
        row = self.connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else row[0]

    def vectors(self) -> int:
        return self.connection.execute("SELECT count(*) FROM embeddings").fetchone()[0]

    def test_crash_after_replace_leaves_index_fully_old(self) -> None:
        self.connection.close()
        new = [dict(c, text=c["text"] + " Amended.") for c in self.old]
        write_jsonl(self.jsonl, new)
        src = str(Path(__file__).resolve().parents[1] / "src")
        proc = subprocess.run(
            [sys.executable, "-I", "-c", CRASH_SCRIPT, str(self.db), str(self.jsonl), src],
            capture_output=True, text=True,
        )
        # 3: imported a copy other than this checkout; 0: no crash hook (old code).
        self.assertEqual(proc.returncode, 7, proc.stderr)
        self.connection = connect(self.db)
        rows = load_chunk_rows(self.connection)
        self.assertEqual([r["text"] for r in rows], [c["text"] for c in self.old])
        self.assertEqual(self.meta("chunks_sha256"), self.old_hash)
        self.assertEqual(self.vectors(), 3)
        self.assertIsNotNone(self.meta(f"embeddings:{self.KEY}"))
        Searcher(self.connection, model=self.KEY)  # old fingerprint + old vectors: consistent
        # The next sync completes the rebuild and ends fully new and consistent.
        self.assertEqual(sync_chunks(self.connection, self.jsonl), 3)
        self.assertEqual([r["text"] for r in load_chunk_rows(self.connection)], [c["text"] for c in new])
        self.assertNotEqual(self.meta("chunks_sha256"), self.old_hash)
        self.assertEqual(self.vectors(), 0)
        self.assertIsNone(self.meta(f"embeddings:{self.KEY}"))
        with self.assertRaises(EmbeddingMismatch):
            Searcher(self.connection, model=self.KEY)

    def test_replace_chunks_clears_embedding_meta_itself(self) -> None:
        replace_chunks(self.connection, self.old)
        self.connection.commit()
        self.assertIsNone(self.meta(f"embeddings:{self.KEY}"))
        self.assertEqual(self.vectors(), 0)


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
