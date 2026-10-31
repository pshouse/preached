"""#19 CTO review at dd33e2f: secure delete on --redo, the checked checkpoint, and the should-fixes.

- must-fix 2: ``--redo`` replaces rows with ``secure_delete`` on, then merges
  FTS and checkpoints; a canary word is gone from the raw db and ``-wal``.
- must-fix 3: the checkpoint result is checked; a concurrent reader makes
  ``--ack-review`` exit non-zero without approving, and a retry succeeds.
- should-fix: ``--redo`` keeps reviewer-added stretches; the ASR ``--out``
  file drops newly excluded words; previews are purged on approval; the
  review and kept-words files are opened with O_NOFOLLOW.
- ruling: the review file header says to listen to the whole recording.

Every name and marker word is invented.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for sub in ("align", "tests"):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

import asr_chunks  # noqa: E402
from preached.exclusions import REVIEWER_MUST, words_file  # noqa: E402
from preached.search import Searcher  # noqa: E402
from preached.store import open_readonly  # noqa: E402
from preached.youtube import library  # noqa: E402
from preached.youtube.cli import main as youtube_main  # noqa: E402
from preached.youtube.listing import Video  # noqa: E402
from test_priv_skip import MARKERS, SERVICE  # noqa: E402
from test_privacy_wire import CHANNEL, FILLER, ID_A, Base, embedder, words_for  # noqa: E402
from coverage_stub import stub_audio

CANARY = "velvetlantern"
FAST = {"CHECKPOINT_WAITS": (0.01, 0.02), "CHECKPOINT_BUSY_MS": 10}


def raw(index: Path) -> bytes:
    """The main file and -wal, as on disk now."""
    wal = Path(f"{index}-wal")
    return index.read_bytes() + (wal.read_bytes() if wal.exists() else b"")


def free_pages(index: Path) -> list[tuple[int, bytes]]:
    """Every freelist page (trunk and leaf) as (number, bytes).

    SQLite reuses the first free page as the trunk without wiping it, so a
    trunk keeps the old b-tree page's header and cell-pointer array (offsets,
    no text). Those first 64 bytes are left out; cell content sits at the
    page end and must be zero.
    """
    data = index.read_bytes()
    size = int.from_bytes(data[16:18], "big")
    size = 65536 if size == 1 else size
    trunk = int.from_bytes(data[32:36], "big")
    pages = []
    while trunk:
        page = data[(trunk - 1) * size : trunk * size]
        following = int.from_bytes(page[0:4], "big")
        count = int.from_bytes(page[4:8], "big")
        for i in range(count):
            leaf = int.from_bytes(page[8 + 4 * i : 12 + 4 * i], "big")
            pages.append((leaf, data[(leaf - 1) * size : leaf * size]))
        pages.append((trunk, page[64:]))
        trunk = following
    return pages


def chunk(i: int, text: str) -> dict:
    return {"chunk_id": f"v-c{i:04d}", "text": text, "start_s": float(i), "end_s": i + 0.9, "source_url": None,
            "word_count": len(text.split()), "word_start": i * 10, "word_end": i * 10 + 10, "audio_url": None}


class SecureDeleteTests(unittest.TestCase):
    """index_video on an open church library: the canary is gone from the db and -wal bytes."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.index = Path(tmp.name) / "church.sqlite"

    def replace_twice(self, connection) -> None:
        first = [chunk(i, f"{FILLER} {CANARY} said it {i}") for i in range(30)]
        second = [chunk(i, f"{FILLER} plain words {i}") for i in range(30)]
        for chunks in (first, second):
            library.index_video(connection, video_id="v", title="t", published=date(2024, 1, 1), duration_s=None,
                                license_text=None, uploader=None, chunks=chunks, matrix=np.ones((len(chunks), 8)))

    def test_canary_gone_from_db_and_wal_while_open(self) -> None:
        connection = library.open_library(self.index)
        self.addCleanup(connection.close)
        self.assertEqual(connection.execute("PRAGMA secure_delete").fetchone()[0], 1)
        self.replace_twice(connection)
        self.assertEqual(Path(f"{self.index}-wal").stat().st_size, 0)  # checkpointed (TRUNCATE)
        self.assertNotIn(CANARY.encode(), raw(self.index))
        self.assertNotIn(CANARY[:8].encode(), raw(self.index))  # nor an FTS prefix of it

    def test_control_without_secure_delete_the_canary_survives(self) -> None:
        connection = library.open_library(self.index)
        self.addCleanup(connection.close)
        connection.execute("PRAGMA secure_delete = OFF")
        with patch.object(library, "scrub", lambda c: None):
            self.replace_twice(connection)
        self.assertIn(CANARY.encode(), raw(self.index))


class CheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.index = Path(tmp.name) / "church.sqlite"
        for name, value in FAST.items():
            patcher = patch.object(library, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_busy_reader_is_retried_then_refused(self) -> None:
        connection = library.open_library(self.index)
        self.addCleanup(connection.close)
        connection.execute("CREATE TABLE IF NOT EXISTS t (x)")
        connection.execute("INSERT INTO t VALUES (1)")
        connection.commit()
        reader = sqlite3.connect(self.index)
        self.addCleanup(reader.close)
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM t").fetchone()
        connection.execute("INSERT INTO t VALUES (2)")
        connection.commit()
        calls = []
        with patch("time.sleep", lambda s: calls.append(s)):
            with self.assertRaises(library.CheckpointBusy):
                library.checkpoint(connection)
        self.assertEqual(calls, list(FAST["CHECKPOINT_WAITS"]))  # backoff, then refused
        reader.rollback()
        library.checkpoint(connection)
        self.assertEqual(Path(f"{self.index}-wal").stat().st_size, 0)


class YouTubeFixupTests(Base):
    def run_import(self, text: str = SERVICE, extra: list[str] | None = None):
        video = Video(ID_A, "Sunday service", 400, date(2024, 6, 2), f"https://www.youtube.com/watch?v={ID_A}")
        return self.cli(
            [CHANNEL, "--library", "wire", *(extra or [])],
            lister=lambda _url: [video],
            metadata=lambda v: {"title": v.title, "duration": 400, "upload_date": "20240602"},
            downloader=lambda v, dest: dest / f"{v.id}.m4a",
            transcriber=lambda path: words_for(text),
            embedder=embedder,
            coverage=lambda *_a, **_k: [],
        )

    def ack(self):
        return self.cli(["--library", "wire", "--ack-review", ID_A], embedder=embedder)

    def lines(self) -> list[dict]:
        return [json.loads(line) for line in self.review_file(ID_A).read_text().splitlines()]

    def write_lines(self, lines: list[dict]) -> None:
        self.review_file(ID_A).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines))

    def add_canary_stretch(self, by: str = "time") -> None:
        words = words_for(SERVICE)
        index = next(i for i, w in enumerate(words) if w.text == CANARY)
        line = {"field": "exclude", "note": "reviewer"}
        if by == "time":
            line.update(start_s=words[index - 1].start, end_s=words[index + 3].end)
        else:
            line.update(start_word=index - 1, end_word=index + 4)
        self.write_lines([*self.lines(), line])

    def approved(self) -> tuple:
        connection = open_readonly(self.index)
        try:
            return connection.execute("SELECT review_sha256, approved_sha256 FROM videos WHERE video_id = ?", (ID_A,)).fetchone()
        finally:
            connection.close()

    def test_redo_secure_deletes_and_keeps_reviewer_stretches(self) -> None:
        self.assertEqual(self.run_import()[0], 0)
        self.add_canary_stretch()
        self.assertEqual(self.ack()[0], 0)
        self.assertNotIn(CANARY.encode(), raw(self.index))
        # --redo with the same words: the reviewer's stretch is carried over and stays excluded.
        code, _out, err = self.run_import(extra=["--redo"])
        self.assertEqual(code, 0, err)
        self.assertNotIn(CANARY.encode(), raw(self.index))
        carried = [x for x in self.lines() if x.get("field") == "exclude" and x.get("proposed_by") == "previous review"]
        self.assertEqual(len(carried), 1, self.lines())
        self.assertEqual(self.approved()[1], None)  # unpublished until approved again
        self.assertEqual(self.ack()[0], 0)
        # --redo with a longer transcript (different word count): the time range still applies.
        code, _out, err = self.run_import(SERVICE + FILLER * 3, ["--redo"])
        self.assertEqual(code, 0, err)
        self.assertNotIn(CANARY.encode(), raw(self.index))

    def test_redo_canary_removed_from_db_and_wal(self) -> None:
        # The first import is long and holds the canary; the --redo transcript is
        # much shorter and has none, so the redo frees pages that held it.
        self.assertEqual(self.run_import(SERVICE + FILLER * 40)[0], 0)
        self.assertIn(CANARY.encode(), raw(self.index))
        seen = []
        real_open = library.open_library

        def spy(path):
            connection = real_open(path)
            seen.append(connection.execute("PRAGMA secure_delete").fetchone()[0])
            return connection

        with patch.object(library, "open_library", spy), patch("preached.youtube.pipeline.open_library", spy):
            code, _out, err = self.run_import(SERVICE.replace(CANARY, "plainword"), ["--redo"])
        self.assertEqual(code, 0, err)
        self.assertTrue(seen and all(v == 1 for v in seen), seen)  # PRAGMA secure_delete is on for the --redo connection
        self.assertNotIn(CANARY.encode(), self.index.read_bytes())
        wal = Path(f"{self.index}-wal")
        self.assertNotIn(CANARY.encode(), wal.read_bytes() if wal.exists() else b"")
        free = free_pages(self.index)
        self.assertTrue(free, "the shrinking redo should have freed pages")
        for number, page in free:
            self.assertFalse(any(page), f"free page {number} holds stale bytes")

    def test_redo_word_only_line_on_a_changed_transcript_is_refused(self) -> None:
        self.assertEqual(self.run_import()[0], 0)
        self.add_canary_stretch(by="word")
        code, _out, err = self.run_import(SERVICE + FILLER, ["--redo"])
        self.assertEqual(code, 1)
        self.assertIn("only a word range", err)

    def test_redo_with_a_busy_reader_fails_loudly(self) -> None:
        self.assertEqual(self.run_import()[0], 0)
        reader = sqlite3.connect(self.index)
        self.addCleanup(reader.close)
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM chunks").fetchone()
        with patch.multiple(library, **FAST):
            code, _out, err = self.run_import(SERVICE.replace(CANARY, "plainword"), ["--redo"])
        self.assertEqual(code, 1)
        self.assertIn("checkpoint", err)
        self.assertIn(str(self.index), err)
        self.assertIn(f"{self.index}-wal", err)
        self.assertIn(f"sermon {ID_A} is now offline until re-reviewed", err)

    def test_ack_with_a_concurrent_reader_exits_nonzero_then_retries(self) -> None:
        self.assertEqual(self.run_import()[0], 0)
        self.add_canary_stretch()
        reader = sqlite3.connect(self.index)
        self.addCleanup(reader.close)
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM chunks").fetchone()  # the server mid-read
        with patch.multiple(library, **FAST):
            code, _out, err = self.ack()
        self.assertEqual(code, 1)
        self.assertIn("not approved", err)
        self.assertIn("checkpoint", err)
        self.assertIsNone(self.approved()[1])
        self.assertTrue(words_file(self.review_file(ID_A)).exists())
        reader.rollback()
        code, _out, err = self.ack()
        self.assertEqual(code, 0, err)
        self.assertNotIn(CANARY.encode(), raw(self.index))
        review, approved = self.approved()
        self.assertEqual(review, approved)
        self.assertFalse(words_file(self.review_file(ID_A)).exists())

    def test_unchanged_ack_with_a_reader_is_refused_too(self) -> None:
        self.assertEqual(self.run_import()[0], 0)
        reader = sqlite3.connect(self.index)
        self.addCleanup(reader.close)
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM chunks").fetchone()
        writer = sqlite3.connect(self.index)
        writer.execute("UPDATE meta SET value = value")  # leave frames in -wal
        writer.commit()
        writer.close()
        with patch.multiple(library, **FAST):
            self.assertEqual(self.ack()[0], 1)
        self.assertIsNone(self.approved()[1])

    def test_previews_are_purged_and_the_sermon_stays_published(self) -> None:
        self.assertEqual(self.run_import()[0], 0)
        before = self.review_file(ID_A).read_bytes()
        self.assertTrue(any(m.encode() in before for m in MARKERS))  # previews show excluded words
        self.assertEqual(self.ack()[0], 0)
        after = self.review_file(ID_A).read_bytes()
        for marker in MARKERS:
            self.assertNotIn(marker.encode(), after)
        excludes = [x for x in self.lines() if x.get("field") == "exclude"]
        self.assertTrue(excludes)
        self.assertFalse(any("opening" in x or "closing" in x for x in excludes))
        review, approved = self.approved()
        self.assertEqual(review, approved)
        connection = open_readonly(self.index)
        self.addCleanup(connection.close)
        self.assertTrue(Searcher(connection, gated=True).bm25("zephyrgrace", 5))
        self.assertEqual(self.ack()[0], 0)  # re-acknowledging the purged file is fine
        self.write_lines([*self.lines(), {"field": "exclude", "start_word": 0, "end_word": 2}])
        code, _out, err = self.ack()
        self.assertEqual(code, 1)
        self.assertIn("changed after approval", err)

    def test_review_header_says_listen_to_the_whole_recording(self) -> None:
        self.assertEqual(self.run_import()[0], 0)
        header = next(x for x in self.lines() if x.get("field") == "exclusions")
        self.assertEqual(header["reviewer_must"], REVIEWER_MUST)
        self.assertIn("whole recording", REVIEWER_MUST)
        self.assertIn("0.870", REVIEWER_MUST)

    def test_symlinked_review_or_words_file_is_refused(self) -> None:
        self.assertEqual(self.run_import()[0], 0)
        review = self.review_file(ID_A)
        self.add_canary_stretch()
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        for target in (review, words_file(review)):
            copy = elsewhere / target.name
            copy.write_bytes(target.read_bytes())
            original = target.read_bytes()
            target.unlink()
            target.symlink_to(copy)
            code, _out, err = self.ack()
            self.assertEqual(code, 1, target)
            self.assertIn("not approved", err)
            self.assertIsNone(self.approved()[1])
            target.unlink()
            target.write_bytes(original)
            os.chmod(target, 0o600)
        self.assertEqual(self.ack()[0], 0)


class AsrOutTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = {k: v for k, v in os.environ.items() if not k.startswith("PREACHED_PRIVACY") and k != "PREACHED_FLAGGED_AUDIO"}
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.toml = self.root / "privacy.toml"
        self.toml.write_text("# none\n")
        self.paths = []
        for sermon_id, text in (("church-1", SERVICE), ("church-2", FILLER * 30 + f"{CANARY} other sermon.")):
            path = self.root / f"{sermon_id}.json"
            words = words_for(text)
            path.write_text(json.dumps({"meta": {"id": sermon_id, "title": "Sunday"},
                                        "segments": [{"words": [[w.start, w.end, w.text] for w in words]}]}))
            self.paths.append(path)
        self.out = self.root / "c.jsonl"
        self.index = self.root / "church.sqlite"

    def test_out_file_drops_newly_excluded_words_and_keeps_other_sermons(self) -> None:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            asr_chunks.main([*map(str, self.paths), "--out", str(self.out), "--library", "church",
                             "--privacy", str(self.toml), "--index", str(self.index), *stub_audio(*self.paths)], embedder=embedder, coverage=lambda *_a, **_k: [])
        before = [json.loads(x) for x in self.out.read_text().splitlines()]
        self.assertIn(CANARY, " ".join(r["text"] for r in before if r["sermon_id"] == "church-1"))
        review = self.root / "church" / "review" / "church-1.review.jsonl"
        lines = [json.loads(x) for x in review.read_text().splitlines()]
        words = words_for(SERVICE)
        index = next(i for i, w in enumerate(words) if w.text == CANARY)
        lines.append({"field": "exclude", "start_s": words[index - 1].start, "end_s": words[index + 3].end})
        review.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines))
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()) as err:
            code = youtube_main(["--library", "church", "--ack-review", "church-1", "--privacy", str(self.toml)],
                                index_dir=self.root, embedder=embedder)
        self.assertEqual(code, 0, err.getvalue())
        after = [json.loads(x) for x in self.out.read_text().splitlines()]
        self.assertNotIn(CANARY, " ".join(r["text"] for r in after if r["sermon_id"] == "church-1"))
        # church-2 (unreviewed) is untouched and in the same place.
        self.assertEqual([r for r in after if r["sermon_id"] == "church-2"], [r for r in before if r["sermon_id"] == "church-2"])
        self.assertEqual(after[0]["sermon_id"], "church-1")
        connection = open_readonly(self.index)
        self.addCleanup(connection.close)
        stored = [r[0] for r in connection.execute("SELECT text FROM chunks WHERE sermon_id = 'church-1' ORDER BY rowid")]
        self.assertEqual(stored, [r["text"] for r in after if r["sermon_id"] == "church-1"])

    def test_rerun_keeps_reviewer_stretches(self) -> None:
        argv = [str(self.paths[0]), "--out", str(self.out), "--library", "church", "--privacy", str(self.toml), "--index", str(self.index), *stub_audio(*self.paths)]
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            asr_chunks.main(argv, embedder=embedder, coverage=lambda *_a, **_k: [])
        review = self.root / "church" / "review" / "church-1.review.jsonl"
        words = words_for(SERVICE)
        index = next(i for i, w in enumerate(words) if w.text == CANARY)
        lines = [json.loads(x) for x in review.read_text().splitlines()]
        lines.append({"field": "exclude", "start_s": words[index - 1].start, "end_s": words[index + 3].end})
        review.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines))
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            asr_chunks.main(argv, embedder=embedder, coverage=lambda *_a, **_k: [])
        self.assertNotIn(CANARY, self.out.read_text())
        self.assertNotIn(CANARY.encode(), raw(self.index))


if __name__ == "__main__":
    unittest.main()
