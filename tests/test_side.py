"""Side-by-side search: one library per column, one church mark, empty side."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from contextlib import ExitStack, closing, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from app.server import CSP, STATIC_DIR, App, Searcher, build_app, make_server, prepare_church
from preached.abstain import Signals, church_confidence, decide
from preached.library import (
    CHURCH_EMPTY,
    church_index_matches,
    church_shaped,
    classic_church_refusal,
    is_protected_classic,
    find_church_index,
    get_meta,
    is_your_church,
    mark_your_church,
    mark_your_church_exclusive,
    resolve_church_path,
    UnsafeOpen,
)
import preached.library as library
from preached.store import UnsafeSidecar, connect, open_readonly, save_embedding_info, write_embeddings
from preached.youtube.library import ensure_library

FIXTURE_FP = "fixture-fingerprint"
CLASSIC_AUDIO = "https://archive.org/download/sermonsfirstseries_1307_librivox/example.mp3"
CHURCH_AUDIO = "https://www.youtube.com/watch?v=samplevid01&t=11s"
CCEL = "https://ccel.org/ccel/wesley/sermons/sermons.v.i.html"
WATCH = "https://www.youtube.com/watch?v=samplevid01"
RESULT_KEYS = {
    "chunk_id",
    "chunk_ids",
    "sermon_id",
    "sermon_number",
    "sermon_title",
    "scripture",
    "text",
    "start_s",
    "end_s",
    "audio_url",
    "reader",
    "text_source",
    "source_url",
    "score",
}
SIDE_KEYS = {
    "library",
    "label",
    "sample",
    "present",
    "empty",
    "message",
    "mode",
    "results",
    "note",
    "abstain",
    "confidence",
}
COLUMNS = (
    "chunk_id",
    "sermon_id",
    "sermon_title",
    "text",
    "start_s",
    "end_s",
    "sermon_number",
    "scripture",
    "source_url",
    "word_count",
    "word_start",
    "word_end",
    "librivox_id",
    "audio_url",
    "reader",
    "text_source",
)


def encode_fixture(_query: str) -> np.ndarray:
    return np.array([1, 0, 0, 0], dtype=np.float32)


def _insert(connection, **overrides) -> None:
    row = {
        "chunk_id": "wesley-001-c0000",
        "sermon_id": "wesley-001",
        "sermon_title": "Salvation by Faith",
        "text": "By grace are ye saved through faith.",
        "start_s": 32.81,
        "end_s": 40.0,
        "sermon_number": 1,
        "scripture": "Eph 2:8",
        "source_url": CCEL,
        "word_count": 6,
        "word_start": 0,
        "word_end": 6,
        "librivox_id": "sermonsfirstseries_1307_librivox",
        "audio_url": CLASSIC_AUDIO,
        "reader": "A. Volunteer",
        "text_source": "canonical",
    }
    row.update(overrides)
    names = ", ".join(COLUMNS)
    places = ", ".join(":" + name for name in COLUMNS)
    connection.execute(f"INSERT INTO chunks ({names}) VALUES ({places})", row)


def build_library(
    path: Path,
    rows: list[dict],
    vectors: list[list[float]],
    *,
    church: bool = False,
    sample: bool = False,
    church_import: bool | None = None,
) -> None:
    """``church_import`` (default: ``church``) adds the YouTube import's
    ``videos`` table and ``chunks.video_id`` (``library.church_shaped``)."""
    connection = connect(path)
    if church if church_import is None else church_import:
        ensure_library(connection)
    for row in rows:
        _insert(connection, **row)
    connection.commit()
    rowids = [int(row[0]) for row in connection.execute("SELECT rowid FROM chunks ORDER BY rowid")]
    matrix = np.array(vectors, dtype=np.float32)
    write_embeddings(connection, "fixture", rowids, matrix)
    save_embedding_info(connection, "fixture", {"fingerprint": FIXTURE_FP})
    if church:
        mark_your_church(connection, sample=sample)
        connection.commit()
    connection.close()


def reopen(path: Path):
    connection = open_readonly(path, check_same_thread=False)
    return connection


def classic_rows() -> tuple[list[dict], list[list[float]]]:
    rows = [
        {
            "chunk_id": "classic-a",
            "sermon_id": "wesley-001",
            "sermon_title": "Salvation by Faith",
            "text": "classiconlytoken alpha from the classic library.",
            "word_start": 0,
            "word_end": 8,
        },
        {
            "chunk_id": "classic-b",
            "sermon_id": "wesley-002",
            "sermon_number": 2,
            "sermon_title": "The Almost Christian",
            "text": "classiconlytoken beta from the classic library.",
            "word_start": 100,
            "word_end": 108,
        },
        {
            "chunk_id": "classic-shared",
            "sermon_id": "wesley-003",
            "sermon_number": 3,
            "sermon_title": "Awake Thou That Sleepest",
            "text": "sharedpulpit faith from the classic library.",
            "word_start": 200,
            "word_end": 208,
        },
    ]
    return rows, [[1, 0, 0, 0], [1, 0, 0, 0], [1, 0, 0, 0]]


def church_rows() -> tuple[list[dict], list[list[float]]]:
    rows = [
        {
            "chunk_id": "church-only",
            "sermon_id": "samplevid01",
            "sermon_number": None,
            "sermon_title": "On Mercy",
            "text": "churchonlytoken mercy from the sample church.",
            "scripture": None,
            "source_url": WATCH,
            "start_s": 12.2,
            "end_s": 20.0,
            "audio_url": CHURCH_AUDIO,
            "reader": None,
            "text_source": "asr",
            "librivox_id": None,
            "word_start": 0,
            "word_end": 8,
        },
        {
            "chunk_id": "church-shared",
            "sermon_id": "samplevid02",
            "sermon_number": None,
            "sermon_title": "On Hope",
            "text": "sharedpulpit hope from the sample church.",
            "scripture": None,
            "source_url": "https://www.youtube.com/watch?v=samplevid02",
            "start_s": 40.0,
            "end_s": 55.0,
            "audio_url": "https://www.youtube.com/watch?v=samplevid02&t=39s",
            "reader": None,
            "text_source": "asr",
            "librivox_id": None,
            "word_start": 0,
            "word_end": 8,
        },
    ]
    return rows, [[0, 1, 0, 0], [0, 1, 0, 0]]


def make_app(classic_path: Path, church_path: Path | None, *, floor: float | None = 0.5) -> App:
    classic = reopen(classic_path)
    church = reopen(church_path) if church_path is not None else None
    return App(
        connection=classic,
        searcher=Searcher(classic, model="fixture", fingerprint=FIXTURE_FP),
        encode=encode_fixture,
        fallback_note=None,
        model_name="fixture",
        hosts={"127.0.0.1", "localhost"},
        static_dir=STATIC_DIR,
        library="wesley",
        floor=floor,
        church_connection=church,
        church_searcher=Searcher(church, model="fixture", fingerprint=FIXTURE_FP) if church is not None else None,
        church_library="sample" if church is not None else None,
        church_label="Your church" if church is not None else None,
    )


class Running:
    def __init__(self, app: App):
        self.server = make_server(app, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def get(self, path: str) -> tuple[int, dict, bytes]:
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()


def texts(payload: dict) -> str:
    return " ".join(hit["text"] for hit in payload["results"])


def sermon_ids(payload: dict) -> set[str]:
    return {hit["sermon_id"] for hit in payload["results"]}


class MarkTests(unittest.TestCase):
    def test_one_mark_is_found_and_two_marks_are_not_a_guess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "sample.sqlite"
            second = root / "other.sqlite"
            rows, vectors = church_rows()
            build_library(first, rows[:1], vectors[:1], church=True, sample=True)
            build_library(second, rows[:1], vectors[:1], church=True, sample=False)
            self.assertEqual(find_church_index(root), None)
            self.assertEqual(len(church_index_matches(root)), 2)
            mark_your_church_exclusive(first, root, sample=True)
            found = find_church_index(root)
            self.assertEqual(found, first)
            marked = open_readonly(first)
            cleared = open_readonly(second)
            try:
                self.assertTrue(is_your_church(marked))
                self.assertEqual(get_meta(marked, "sample"), "1")
                self.assertFalse(is_your_church(cleared))
            finally:
                marked.close()
                cleared.close()
            # The classic file is not a church side even if it shares the directory.
            wesley = root / "wesley.sqlite"
            build_library(wesley, *classic_rows())
            self.assertEqual(find_church_index(root, exclude=wesley), first)
            self.assertIsNone(resolve_church_path(root, classic=wesley, church_index=wesley))
            self.assertIsNone(resolve_church_path(root, classic=wesley, church_library="missing"))
            self.assertEqual(resolve_church_path(root, classic=wesley, church_library="sample"), first)

    def test_classic_copy_bytes_are_unchanged_and_a_sibling_is_cleared_without_wal(self) -> None:
        """A mistaken mark must not migrate wesley or turn on WAL.

        store.connect rewrites the schema and sets journal_mode=WAL. Clearing
        a sibling uses a plain sqlite3 connection. wesley, spurgeon, edwards,
        and a canonical classic path are not opened.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            classics = {
                name: root / f"{name}.sqlite" for name in ("wesley", "spurgeon", "edwards")
            }
            for path in classics.values():
                _plain_marked(path)
            before = {name: path.read_bytes() for name, path in classics.items()}
            other = root / "other.sqlite"
            _plain_marked(other, church_import=True)
            sample = root / "sample.sqlite"
            rows, vectors = church_rows()
            build_library(sample, rows[:1], vectors[:1], church_import=True)
            # A marked wesley copy is not a candidate, so it is not opened.
            self.assertEqual(church_index_matches(root), [other])
            mark_your_church_exclusive(sample, root, sample=True)
            for name, path in classics.items():
                self.assertEqual(path.read_bytes(), before[name], name)
                self.assertFalse(path.with_name(path.name + "-wal").exists(), name)
                self.assertFalse(path.with_name(path.name + "-journal").exists(), name)
                kept = sqlite3.connect(path)
                try:
                    self.assertEqual(
                        kept.execute("SELECT value FROM meta WHERE key = 'role'").fetchone()[0],
                        "church",
                    )
                    self.assertEqual(kept.execute("PRAGMA journal_mode").fetchone()[0], "delete")
                finally:
                    kept.close()
            cleared = sqlite3.connect(other)
            try:
                self.assertIsNone(
                    cleared.execute("SELECT value FROM meta WHERE key = 'role'").fetchone()
                )
                self.assertEqual(cleared.execute("PRAGMA journal_mode").fetchone()[0], "delete")
                tables = {row[0] for row in cleared.execute("SELECT name FROM sqlite_master")}
            finally:
                cleared.close()
            self.assertNotIn("chunks_fts", tables)
            self.assertNotIn("embeddings", tables)
            self.assertFalse(other.with_name(other.name + "-wal").exists())
            marked = open_readonly(sample)
            try:
                self.assertTrue(is_your_church(marked))
            finally:
                marked.close()
            # Marking the wesley copy itself must not rewrite it either.
            with self.assertRaises(ValueError):
                mark_your_church_exclusive(classics["wesley"], root)
            self.assertEqual(classics["wesley"].read_bytes(), before["wesley"])

            canonical = root / "archive.sqlite"
            _plain_marked(canonical)
            canonical_before = canonical.read_bytes()
            with patch("preached.paths.INDEX_PATH", canonical):
                mark_your_church_exclusive(sample, root, sample=True)
            self.assertEqual(canonical.read_bytes(), canonical_before)
            self.assertFalse(canonical.with_name(canonical.name + "-wal").exists())


class HardlinkTests(unittest.TestCase):
    """A hardlink to a classic file is that classic (CTO round 2, must-fix 1).

    A path compare missed it: marking a church through a hardlinked
    wesley.sqlite rewrote the real Wesley file, and ``--church-index`` on a
    hardlink to the canonical spurgeon was accepted.
    """

    def test_hardlinks_to_wesley_and_spurgeon_are_refused_and_wesley_bytes_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index_dir = Path(tmp) / "index"
            work = Path(tmp) / "work"
            index_dir.mkdir()
            work.mkdir()
            wesley = index_dir / "wesley.sqlite"
            spurgeon = index_dir / "spurgeon.sqlite"
            # A mistaken role=church on both, as in the CTO repro.
            _plain_marked(wesley)
            _plain_marked(spurgeon)
            wesley_link = work / "mychurch.sqlite"
            spurgeon_link = work / "other.sqlite"
            wesley_link.hardlink_to(wesley)
            spurgeon_link.hardlink_to(spurgeon)
            sample = work / "sample.sqlite"
            rows, vectors = church_rows()
            build_library(sample, rows[:1], vectors[:1], church_import=True)
            before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (wesley, spurgeon)}
            with (
                patch("preached.paths.INDEX_DIR", index_dir),
                patch("preached.paths.INDEX_PATH", wesley),
            ):
                for link in (wesley_link, spurgeon_link):
                    self.assertTrue(is_protected_classic(link), link.name)
                    self.assertIsNotNone(classic_church_refusal(None, link), link.name)
                    with self.assertRaises(SystemExit) as caught:
                        prepare_church(church_index=link, church_library=None)
                    self.assertIn("classic", str(caught.exception))
                    with self.assertRaises(ValueError):
                        mark_your_church_exclusive(link, work)
                # Both links are marked role=church siblings; neither is cleared.
                mark_your_church_exclusive(sample, work, sample=True)
            for path, digest in before.items():
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest, path.name)
                self.assertFalse(path.with_name(path.name + "-wal").exists(), path.name)
                self.assertFalse(path.with_name(path.name + "-shm").exists(), path.name)

    def test_any_hardlinked_file_is_protected_even_without_a_known_classic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / "elsewhere.sqlite"
            _plain_marked(original, church_import=True)
            link = root / "church.sqlite"
            link.hardlink_to(original)
            self.assertTrue(is_protected_classic(link))
            self.assertTrue(is_protected_classic(original))

    def test_wesley_shaped_or_classic_marked_content_is_never_written(self) -> None:
        """Not a link, not a classic name: still not written unless it is a church import."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wesley_copy = root / "copied.sqlite"
            _plain_marked(wesley_copy)
            tagged = root / "tagged.sqlite"
            _plain_marked(tagged, church_import=True)
            labelled = sqlite3.connect(tagged)
            labelled.execute("INSERT INTO meta (key, value) VALUES ('library', 'spurgeon')")
            labelled.commit()
            labelled.close()
            sample = root / "sample.sqlite"
            rows, vectors = church_rows()
            build_library(sample, rows[:1], vectors[:1], church_import=True)
            before = {path: path.read_bytes() for path in (wesley_copy, tagged)}
            self.assertFalse(church_shaped(wesley_copy))
            self.assertFalse(church_shaped(tagged))
            mark_your_church_exclusive(sample, root, sample=True)
            for path in (wesley_copy, tagged):
                self.assertEqual(path.read_bytes(), before[path], path.name)
                with self.assertRaises(ValueError):
                    mark_your_church_exclusive(path, root)
                self.assertEqual(path.read_bytes(), before[path], path.name)


class InodeAndLinkTests(unittest.TestCase):
    """CTO round 3: S2 (the inode compare on its own) and S3 (hardlink messages)."""

    def test_same_inode_with_one_link_is_the_classic(self) -> None:
        """Only the (st_dev, st_ino) compare can say this file is wesley.

        Not the stem, not the realpath, not #14's canonical paths, and one
        link. On one mount two names with one link cannot share an inode
        (a bind mount can, which a test cannot make without root), so
        ``_file_id`` reports wesley's identity for the church path.
        """
        with tempfile.TemporaryDirectory() as tmp:
            index_dir = Path(tmp) / "index"
            work = Path(tmp) / "work"
            index_dir.mkdir()
            work.mkdir()
            wesley = index_dir / "wesley.sqlite"
            _plain_marked(wesley)
            church = work / "church.sqlite"
            _plain_marked(church, church_import=True)
            before = church.read_bytes()
            real = library._file_id
            wesley_id = real(wesley)
            self.assertEqual(wesley_id[2], 1)

            def same_inode(path):
                if Path(path).resolve() == church.resolve():
                    return wesley_id
                return real(path)

            with (
                patch("preached.paths.INDEX_DIR", index_dir),
                patch("preached.paths.INDEX_PATH", wesley),
            ):
                self.assertFalse(is_protected_classic(church))
                with patch.object(library, "_file_id", same_inode):
                    self.assertEqual(library._links(church), 1)
                    self.assertTrue(is_protected_classic(church))
                    self.assertIn("is a classic library", classic_church_refusal(None, church))
                    with self.assertRaises(ValueError) as caught:
                        mark_your_church_exclusive(church, work)
                    self.assertIn("is a classic library", str(caught.exception))
                    self.assertEqual(church_index_matches(work), [])
            self.assertEqual(church.read_bytes(), before)

    def test_hardlinked_church_has_its_own_message_and_its_mark_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index_dir = Path(tmp) / "index"
            work = Path(tmp) / "work"
            elsewhere = Path(tmp) / "elsewhere"
            for directory in (index_dir, work, elsewhere):
                directory.mkdir()
            wesley = index_dir / "wesley.sqlite"
            _plain_marked(wesley)
            # A church import with a second name somewhere else, and a stale mark.
            stale = work / "stale.sqlite"
            _plain_marked(stale, church_import=True)
            (elsewhere / "copy.sqlite").hardlink_to(stale)
            # A sibling that is marked but is not a church import.
            shaped = work / "notchurch.sqlite"
            _plain_marked(shaped)
            sample = work / "sample.sqlite"
            rows, vectors = church_rows()
            build_library(sample, rows[:1], vectors[:1], church_import=True)
            before = {path: path.read_bytes() for path in (wesley, stale, shaped)}
            with (
                patch("preached.paths.INDEX_DIR", index_dir),
                patch("preached.paths.INDEX_PATH", wesley),
            ):
                refusal = classic_church_refusal(None, stale)
                self.assertIn("has 2 hard links", refusal)
                self.assertNotIn("classic", refusal)
                self.assertIn("is a classic library", classic_church_refusal(None, wesley))
                with self.assertRaises(ValueError) as caught:
                    mark_your_church_exclusive(stale, work)
                self.assertIn("has 2 hard links", str(caught.exception))
                self.assertNotIn("classic", str(caught.exception))
                skipped = mark_your_church_exclusive(sample, work, sample=True)
            self.assertEqual(
                skipped,
                [(shaped, "is not a church import"), (stale, "has 2 hard links")],
            )
            for path, data in before.items():
                self.assertEqual(path.read_bytes(), data, path.name)


class _SwapOnConnect:
    """Swap ``name`` for ``replacement`` the moment ``sqlite3.connect`` opens it for writing.

    That is after every check by name (``is_protected_classic``,
    ``church_shaped``, the sibling scan) and before SQLite opens the file.
    The write open is the ``file:...?mode=rw`` URI (``library._rw_uri``);
    read-only opens (``store.open_readonly``, ``mode=ro``) pass through.
    ``how`` is ``"link"`` (a hardlink to ``replacement``), ``"copy"`` (a
    separate copy: one link, a new inode) or ``"symlink"`` (a symlink to
    ``replacement``, which may not exist), renamed over the name.
    """

    def __init__(self, name: Path, replacement: Path, *, how: str = "link") -> None:
        self.name = name
        self.replacement = replacement
        self.how = how
        self.fired = False
        self._real = sqlite3.connect

    def _is_write_open(self, database, kwargs) -> bool:
        if not kwargs.get("uri") or not isinstance(database, str):
            return False
        parts = urllib.parse.urlsplit(database)
        return parts.query == "mode=rw" and urllib.parse.unquote(parts.path) == os.path.abspath(self.name)

    def __call__(self, database, *args, **kwargs):
        if not self.fired and self._is_write_open(database, kwargs):
            self.fired = True
            temp = self.name.with_name(self.name.name + ".swap")
            if self.how == "link":
                os.link(self.replacement, temp)
            elif self.how == "copy":
                temp.write_bytes(self.replacement.read_bytes())
            else:
                os.symlink(self.replacement, temp)
            os.replace(temp, self.name)
        return self._real(database, *args, **kwargs)

    def patch(self):
        return patch.object(library.sqlite3, "connect", self)


class OpenRaceTests(unittest.TestCase):
    """CTO round 3, S1: the name is swapped for a classic between the checks and the open.

    Before the fix both the target write (``store.connect``: WAL, schema,
    the mark) and the sibling clear wrote into the classic file. The fd
    SQLite opened is now fstat'ed (one link, not a classic inode), and the
    church shape is read through that connection, before the first write.
    """

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.index_dir = Path(tmp.name) / "index"
        self.work = Path(tmp.name) / "work"
        self.index_dir.mkdir()
        self.work.mkdir()
        self.wesley = self.index_dir / "wesley.sqlite"
        _plain_marked(self.wesley)
        # Church-shaped, at a classic location: only the fd check refuses it.
        self.archive = self.index_dir / "archive.sqlite"
        _plain_marked(self.archive, church_import=True)
        self.sample = self.work / "sample.sqlite"
        rows, vectors = church_rows()
        build_library(self.sample, rows[:1], vectors[:1], church_import=True)
        for target in (
            patch("preached.paths.INDEX_DIR", self.index_dir),
            patch("preached.paths.INDEX_PATH", self.wesley),
        ):
            target.start()
            self.addCleanup(target.stop)

    def snapshot(self, path: Path) -> tuple[bytes, int]:
        return path.read_bytes(), path.stat().st_mtime_ns

    def assert_untouched(self, path: Path, before: tuple[bytes, int]) -> None:
        self.assertEqual(self.snapshot(path), before, path.name)
        for suffix in ("-wal", "-shm", "-journal"):
            self.assertFalse(Path(f"{path}{suffix}").exists(), f"{path.name}{suffix}")

    def classics(self):
        """wesley (Wesley-shaped) and a classic file that is church-shaped.

        ``archive.sqlite`` is made a classic by naming it in ``_classic_files``;
        the church shape read through the connection would pass it, so only
        the descriptor check keeps it from being written.
        """
        real = library._classic_files
        return patch.object(library, "_classic_files", lambda: [*real(), self.archive])

    def test_target_swapped_for_a_classic_link_is_not_written(self) -> None:
        with self.classics():
            for classic in (self.wesley, self.archive):
                with self.subTest(classic=classic.name):
                    rows, vectors = church_rows()
                    self.sample.unlink()
                    build_library(self.sample, rows[:1], vectors[:1], church_import=True)
                    before = self.snapshot(classic)
                    swap = _SwapOnConnect(self.sample, classic)
                    with swap.patch(), self.assertRaises(UnsafeOpen) as caught:
                        mark_your_church_exclusive(self.sample, self.work, sample=True)
                    self.assertTrue(swap.fired)
                    self.assertIn("hard links once opened", str(caught.exception))
                    self.assert_untouched(classic, before)

    def test_sibling_swapped_for_a_classic_link_is_not_cleared(self) -> None:
        with self.classics():
            for classic in (self.wesley, self.archive):
                with self.subTest(classic=classic.name):
                    other = self.work / f"other-{classic.stem}.sqlite"
                    _plain_marked(other, church_import=True)
                    before = self.snapshot(classic)
                    swap = _SwapOnConnect(other, classic)
                    with swap.patch():
                        skipped = mark_your_church_exclusive(self.sample, self.work, sample=True)
                    self.assertTrue(swap.fired)
                    self.assertEqual(skipped, [(other, "has 2 hard links once opened")])
                    self.assert_untouched(classic, before)
                    other.unlink()
                    marked = open_readonly(self.sample)
                    try:
                        self.assertTrue(is_your_church(marked))
                    finally:
                        marked.close()

    def test_classic_inode_with_one_link_once_opened_is_refused(self) -> None:
        """The inode check on the descriptor, without the link count to lean on.

        A hardlink swap leaves the classic with two links, so the nlink check
        also fires. Here fstat reports one link for the classic's inode (as a
        bind mount would), so only the ``(st_dev, st_ino)`` compare refuses it.
        """
        real_fstat = os.fstat
        with self.classics():
            for classic in (self.wesley, self.archive):
                ident = os.stat(classic)

                def one_link(fd, ident=ident):
                    st = real_fstat(fd)
                    if (st.st_dev, st.st_ino) != (ident.st_dev, ident.st_ino):
                        return st
                    return SimpleNamespace(st_mode=st.st_mode, st_dev=st.st_dev, st_ino=st.st_ino, st_nlink=1)

                with self.subTest(classic=classic.name, side="target"):
                    before = self.snapshot(classic)
                    swap = _SwapOnConnect(self.sample, classic)
                    with swap.patch(), patch.object(library.os, "fstat", one_link), self.assertRaises(UnsafeOpen) as caught:
                        mark_your_church_exclusive(self.sample, self.work, sample=True)
                    self.assertTrue(swap.fired)
                    self.assertIn("is a classic library file once opened", str(caught.exception))
                    self.assert_untouched(classic, before)
                    rows, vectors = church_rows()
                    self.sample.unlink()
                    build_library(self.sample, rows[:1], vectors[:1], church_import=True)
                with self.subTest(classic=classic.name, side="sibling"):
                    other = self.work / "other.sqlite"
                    _plain_marked(other, church_import=True)
                    before = self.snapshot(classic)
                    swap = _SwapOnConnect(other, classic)
                    with swap.patch(), patch.object(library.os, "fstat", one_link):
                        skipped = mark_your_church_exclusive(self.sample, self.work, sample=True)
                    self.assertTrue(swap.fired)
                    self.assertEqual(skipped, [(other, "is a classic library file once opened")])
                    self.assert_untouched(classic, before)
                    other.unlink()

    def test_swap_for_a_wesley_shaped_copy_is_caught_by_the_shape_read_on_the_open_file(self) -> None:
        """One link, a new inode: the descriptor check passes; the shape check on the connection does not."""
        before = self.snapshot(self.wesley)
        copy_source = self.work / "wesley-copy.bin"
        copy_source.write_bytes(self.wesley.read_bytes())
        other = self.work / "other.sqlite"
        _plain_marked(other, church_import=True)
        swap = _SwapOnConnect(other, copy_source, how="copy")
        with swap.patch():
            skipped = mark_your_church_exclusive(self.sample, self.work, sample=True)
        self.assertTrue(swap.fired)
        self.assertEqual(skipped, [(other, "is not a church import (no videos table)")])
        self.assertEqual(other.read_bytes(), copy_source.read_bytes())
        swap = _SwapOnConnect(self.sample, copy_source, how="copy")
        with swap.patch(), self.assertRaises(ValueError) as caught:
            mark_your_church_exclusive(self.sample, self.work, sample=True)
        self.assertTrue(swap.fired)
        self.assertIn("is not a church import", str(caught.exception))
        self.assertEqual(self.sample.read_bytes(), copy_source.read_bytes())
        self.assert_untouched(self.wesley, before)


class SidecarTests(unittest.TestCase):
    """CTO round 1 on PR #27, must-fix 1: a -wal, -shm or -journal name that is
    a hardlink to wesley.sqlite.

    SQLite opens those by name, after any check on the main file, so no race
    is needed. Before the fix a -wal or -shm link made the mark (and the
    sibling clear, and even a read-only ``church_shaped``) write the WAL or
    the shm index into Wesley, then delete the name. Now the sidecars are
    lstat'ed before any open: the target raises ``UnsafeOpen``, a sibling is
    reported and not opened, and the read-only helpers say not church.
    """

    SUFFIXES = ("-wal", "-shm", "-journal")

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.index_dir = Path(tmp.name) / "index"
        self.work = Path(tmp.name) / "work"
        self.index_dir.mkdir()
        self.work.mkdir()
        self.wesley = self.index_dir / "wesley.sqlite"
        _plain_marked(self.wesley)
        self.sample = self.work / "sample.sqlite"
        self.build_sample()
        for target in (
            patch("preached.paths.INDEX_DIR", self.index_dir),
            patch("preached.paths.INDEX_PATH", self.wesley),
        ):
            target.start()
            self.addCleanup(target.stop)

    def build_sample(self) -> None:
        for leftover in (self.sample, *(Path(f"{self.sample}{suffix}") for suffix in self.SUFFIXES)):
            leftover.unlink(missing_ok=True)
        rows, vectors = church_rows()
        build_library(self.sample, rows[:1], vectors[:1], church_import=True)

    def wesley_state(self) -> tuple[str, int, int]:
        st = self.wesley.stat()
        return hashlib.sha256(self.wesley.read_bytes()).hexdigest(), st.st_size, st.st_mtime_ns

    def plant(self, church: Path, suffix: str) -> Path:
        # A read-only open of a WAL file leaves an empty -wal and -shm behind.
        sidecar = Path(f"{church}{suffix}")
        sidecar.unlink(missing_ok=True)
        os.link(self.wesley, sidecar)
        self.addCleanup(sidecar.unlink, missing_ok=True)
        return sidecar

    def is_marked(self, path: Path) -> bool:
        connection = sqlite3.connect(path)
        try:
            return is_your_church(connection)
        finally:
            connection.close()

    def test_target_with_a_hardlinked_sidecar_is_refused_and_wesley_is_unchanged(self) -> None:
        for suffix in self.SUFFIXES:
            with self.subTest(suffix=suffix):
                self.build_sample()
                before = self.wesley_state()
                sidecar = self.plant(self.sample, suffix)
                with self.assertRaises(UnsafeOpen) as caught:
                    mark_your_church_exclusive(self.sample, self.work, sample=True)
                self.assertIn(f"has a {suffix} file with 2 hard links", str(caught.exception))
                self.assertEqual(self.wesley_state(), before)
                self.assertEqual(os.stat(self.wesley).st_nlink, 2)
                self.assertTrue(sidecar.exists())
                sidecar.unlink()
                self.assertFalse(self.is_marked(self.sample))

    def test_sibling_with_a_hardlinked_sidecar_is_reported_and_not_opened(self) -> None:
        rows, vectors = church_rows()
        for mode in ("rollback", "wal"):
            for suffix in self.SUFFIXES:
                with self.subTest(mode=mode, suffix=suffix):
                    self.build_sample()
                    other = self.work / "other.sqlite"
                    if mode == "rollback":
                        _plain_marked(other, church_import=True)
                    else:
                        build_library(other, rows[:1], vectors[:1], church=True)
                    with closing(sqlite3.connect(other)) as probe:
                        journal = probe.execute("PRAGMA journal_mode").fetchone()[0]
                    self.assertEqual(journal, "wal" if mode == "wal" else "delete")
                    other_before = other.read_bytes()
                    before = self.wesley_state()
                    sidecar = self.plant(other, suffix)
                    skipped = mark_your_church_exclusive(self.sample, self.work, sample=True)
                    self.assertEqual(skipped, [(other, f"has a {suffix} file with 2 hard links (not opened)")])
                    self.assertEqual(self.wesley_state(), before)
                    self.assertEqual(other.read_bytes(), other_before)
                    self.assertTrue(self.is_marked(self.sample))
                    sidecar.unlink()
                    self.assertTrue(self.is_marked(other))
                    other.unlink()

    def test_read_only_helpers_do_not_open_a_file_with_a_hardlinked_sidecar(self) -> None:
        rows, vectors = church_rows()
        church = self.work / "church.sqlite"
        build_library(church, rows[:1], vectors[:1], church=True)
        self.assertTrue(church_shaped(church))
        self.assertTrue(library._is_church_file(church))
        for suffix in self.SUFFIXES:
            with self.subTest(suffix=suffix):
                before = self.wesley_state()
                sidecar = self.plant(church, suffix)
                self.assertFalse(church_shaped(church))
                self.assertFalse(library._is_church_file(church))
                self.assertEqual(church_index_matches(self.work), [])
                self.assertEqual(find_church_index(self.work), None)
                self.assertEqual(self.wesley_state(), before)
                sidecar.unlink()
        self.assertEqual(church_index_matches(self.work), [church])

    def test_symlinked_or_classic_sidecars_are_refused(self) -> None:
        cases = {
            "symlink": lambda sidecar: os.symlink(self.wesley, sidecar),
            "directory": lambda sidecar: sidecar.mkdir(),
        }
        for what, make in cases.items():
            with self.subTest(what=what):
                self.build_sample()
                sidecar = Path(f"{self.sample}-wal")
                make(sidecar)
                before = self.wesley_state()
                with self.assertRaises(UnsafeOpen) as caught:
                    mark_your_church_exclusive(self.sample, self.work)
                self.assertIn("-wal file that is", str(caught.exception))
                self.assertEqual(self.wesley_state(), before)
                sidecar.rmdir() if what == "directory" else sidecar.unlink()
        # One link on Wesley's inode (a bind mount): only the classic-id check refuses it.
        self.build_sample()
        Path(f"{self.sample}-shm").write_bytes(b"")
        wesley = os.stat(self.wesley)
        real_lstat = os.lstat

        def as_wesley(name, *args, **kwargs):
            st = real_lstat(name, *args, **kwargs)
            if os.fspath(name) == f"{self.sample}-shm":
                return SimpleNamespace(st_mode=st.st_mode, st_dev=wesley.st_dev, st_ino=wesley.st_ino, st_nlink=1)
            return st

        with patch.object(library.os, "lstat", as_wesley), self.assertRaises(UnsafeOpen) as caught:
            mark_your_church_exclusive(self.sample, self.work)
        self.assertIn("has a -shm file that is a classic library file", str(caught.exception))

    def test_sidecar_planted_after_the_connect_is_caught_before_the_first_write(self) -> None:
        """The name check passed; a -wal link appears once the main file is open.

        The first read opens it (WAL mode), and the check on the new
        descriptors refuses it before anything is written.
        """
        for side in ("target", "sibling"):
            with self.subTest(side=side):
                self.build_sample()
                rows, vectors = church_rows()
                other = self.work / "other.sqlite"
                other.unlink(missing_ok=True)
                build_library(other, rows[:1], vectors[:1], church=True)
                victim = self.sample if side == "target" else other
                real = sqlite3.connect
                fired = []

                def plant_after(database, *args, **kwargs):
                    connection = real(database, *args, **kwargs)
                    if not fired and kwargs.get("uri") and database.endswith("?mode=rw") and victim.name in database:
                        fired.append(database)
                        Path(f"{victim}-wal").unlink(missing_ok=True)
                        os.link(self.wesley, f"{victim}-wal")
                    return connection

                before = self.wesley_state()
                with patch.object(library.sqlite3, "connect", plant_after):
                    if side == "target":
                        with self.assertRaises(UnsafeOpen) as caught:
                            mark_your_church_exclusive(self.sample, self.work)
                        self.assertIn("2 hard links", str(caught.exception))
                    else:
                        skipped = mark_your_church_exclusive(self.sample, self.work)
                        self.assertEqual([path for path, _why in skipped], [other])
                        self.assertIn("2 hard links", skipped[0][1])
                self.assertTrue(fired)
                Path(f"{victim}-wal").unlink(missing_ok=True)
                self.assertEqual(self.wesley_state(), before)
                other.unlink()

    def test_the_descriptor_recheck_refuses_a_sidecar_the_name_check_misses(self) -> None:
        """Only the fstat of the new -wal descriptor refuses it here.

        The by-name check is faked to pass once the main file is open (as if
        the name were swapped back between the lstat and the open).
        """
        real_connect = sqlite3.connect
        real_problem = library._sidecar_problem
        opened = []

        def plant_after(database, *args, **kwargs):
            connection = real_connect(database, *args, **kwargs)
            if kwargs.get("uri") and database.endswith("?mode=rw") and not opened:
                opened.append(database)
                Path(f"{self.sample}-wal").unlink(missing_ok=True)
                os.link(self.wesley, f"{self.sample}-wal")
            return connection

        def name_check(path):
            return real_problem(path) if not opened else None

        before = self.wesley_state()
        with (
            patch.object(library.sqlite3, "connect", plant_after),
            patch.object(library, "_sidecar_problem", name_check),
            self.assertRaises(UnsafeOpen) as caught,
        ):
            mark_your_church_exclusive(self.sample, self.work)
        self.assertTrue(opened)
        self.assertIn("has a sidecar with 2 hard links once opened", str(caught.exception))
        # SQLite drops the -wal name when the refused connection closes.
        Path(f"{self.sample}-wal").unlink(missing_ok=True)
        self.assertEqual(self.wesley_state(), before)


class _Served(Exception):
    """``make_server`` was reached: the file passed every check at start."""


class ReadOnlyOpenSidecarTests(unittest.TestCase):
    """CTO round 2 on PR #27, item 1: the read-only church opens outside library.py.

    ``search/query.py --library <church slug>`` (``open_index``) and
    ``app/server.py --library <church slug>`` both open the church file with
    ``store.open_readonly``. A WAL church file whose -shm (or -wal) name is a
    hardlink to wesley.sqlite made the first read write the shm index into
    Wesley ("file is not a database" afterwards), with no race needed. Now
    ``open_readonly`` checks the sidecars (``library._sidecar_problem``)
    before it connects, so both entry points refuse the file.
    """

    SLUG = "mychurch"
    SUFFIXES = ("-wal", "-shm", "-journal")

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.index_dir = Path(tmp.name) / "index"
        self.index_dir.mkdir()
        self.wesley = self.index_dir / "wesley.sqlite"
        self.church = self.index_dir / f"{self.SLUG}.sqlite"
        self.build()
        self.query = _load_query()
        import app.server as server

        self.server = server
        privacy = Path(__file__).resolve().parents[1] / "privacy.example.toml"
        for target in (
            patch("preached.paths.INDEX_DIR", self.index_dir),
            patch("preached.paths.INDEX_PATH", self.wesley),
            patch.object(self.query, "INDEX_DIR", self.index_dir),
            patch.object(self.query, "INDEX_PATH", self.wesley),
            patch.object(server, "INDEX_DIR", self.index_dir),
            patch.object(server, "INDEX_PATH", self.wesley),
            patch.object(server, "bundle_problem", lambda _index: None),
            patch.object(server, "make_server", self._no_server),
            patch.dict(os.environ, {"PREACHED_PRIVACY": str(privacy)}),
        ):
            target.start()
            self.addCleanup(target.stop)

    def build(self) -> None:
        """A fresh Wesley and a fresh WAL-mode church file, so no subtest sees another's damage."""
        for path in (self.wesley, self.church):
            for leftover in (path, *(Path(f"{path}{suffix}") for suffix in self.SUFFIXES)):
                leftover.unlink(missing_ok=True)
        build_library(self.wesley, *classic_rows())
        rows, vectors = church_rows()
        build_library(self.church, rows, vectors, church=True, sample=True)
        with closing(sqlite3.connect(self.church)) as probe:
            self.assertEqual(probe.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    @staticmethod
    def _no_server(*_args, **_kwargs):
        raise _Served

    def wesley_state(self) -> tuple[str, int, int]:
        st = self.wesley.stat()
        return hashlib.sha256(self.wesley.read_bytes()).hexdigest(), st.st_size, st.st_mtime_ns

    def plant(self, suffix: str) -> Path:
        sidecar = Path(f"{self.church}{suffix}")
        sidecar.unlink(missing_ok=True)
        os.link(self.wesley, sidecar)
        self.addCleanup(sidecar.unlink, missing_ok=True)
        return sidecar

    def entry_points(self):
        yield "query.open_index", lambda: self.query.open_index(None, self.SLUG).close()
        yield "server.main", lambda: self.server.main(["--library", self.SLUG, "--bm25-only", "--port", "0"])
        # --index <church file> is refused as a library, but only after a read.
        yield "query.open_index --index", lambda: self.query.open_index(self.church, None).close()
        yield "server.main --index", lambda: self.server.main(["--index", str(self.church), "--bm25-only", "--port", "0"])

    def test_both_entry_points_open_the_church_file_when_its_sidecars_are_safe(self) -> None:
        # The open itself works; the server then stops at the gate it has today.
        before = self.wesley_state()
        self.query.open_index(None, self.SLUG).close()
        with self.assertRaises(_Served):
            self.server.main(["--library", self.SLUG, "--bm25-only", "--port", "0"])
        self.assertEqual(self.wesley_state(), before)

    def test_a_hardlinked_sidecar_is_refused_by_both_entry_points_and_wesley_is_unchanged(self) -> None:
        for name, run in self.entry_points():
            for suffix in self.SUFFIXES:
                with self.subTest(entry=name, suffix=suffix):
                    self.build()
                    before = self.wesley_state()
                    sidecar = self.plant(suffix)
                    try:
                        run()
                        refusal = None
                    except (SystemExit, _Served) as exc:
                        refusal = exc
                    self.assertEqual(self.wesley_state(), before)
                    self.assertIsInstance(refusal, SystemExit)
                    self.assertIn(f"has a {suffix} file with 2 hard links", str(refusal))
                    self.assertTrue(sidecar.exists())
                    self.assertEqual(os.stat(self.wesley).st_nlink, 2)
                    sidecar.unlink()
                    with closing(sqlite3.connect(f"{self.wesley.as_uri()}?mode=ro", uri=True)) as probe:
                        self.assertEqual(probe.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_open_readonly_refuses_a_symlinked_sidecar(self) -> None:
        sidecar = Path(f"{self.church}-shm")
        sidecar.unlink(missing_ok=True)
        os.symlink(self.wesley, sidecar)
        self.addCleanup(sidecar.unlink, missing_ok=True)
        before = self.wesley_state()
        with self.assertRaises(UnsafeSidecar) as caught:
            open_readonly(self.church)
        self.assertIn("-shm file that is a symlink", str(caught.exception))
        self.assertEqual(self.wesley_state(), before)


class RecheckPositionTests(unittest.TestCase):
    """CTO round 2 on PR #27, item 3: each ``_Checked.recheck`` call has its own test.

    A link planted at one point is caught by every later recheck too, so a
    test that only asserts a refusal passes with any one recheck removed.
    Each test here plants a -wal (or -shm) link to wesley.sqlite at one point
    and asserts what that recheck keeps from happening before the next one:
    no sibling cleared, no WAL switch, no schema or mark written, no commit,
    no sibling mark dropped. The planted names cannot redirect a descriptor
    SQLite already holds, so these assert where the refusal lands, not that
    Wesley would be written without it.
    """

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.index_dir = Path(tmp.name) / "index"
        self.work = Path(tmp.name) / "work"
        self.index_dir.mkdir()
        self.work.mkdir()
        self.wesley = self.index_dir / "wesley.sqlite"
        _plain_marked(self.wesley)
        self.sample = self.work / "sample.sqlite"
        self.other = self.work / "other.sqlite"
        for target in (
            patch("preached.paths.INDEX_DIR", self.index_dir),
            patch("preached.paths.INDEX_PATH", self.wesley),
        ):
            target.start()
            self.addCleanup(target.stop)

    def plant(self, church: Path, suffix: str = "-wal") -> None:
        sidecar = Path(f"{church}{suffix}")
        sidecar.unlink(missing_ok=True)
        os.link(self.wesley, sidecar)
        self.addCleanup(sidecar.unlink, missing_ok=True)

    def unplant(self, church: Path, suffix: str = "-wal") -> None:
        sidecar = Path(f"{church}{suffix}")
        if sidecar.exists() and os.stat(sidecar).st_ino == os.stat(self.wesley).st_ino:
            sidecar.unlink()

    def wal_church(self, path: Path, *, marked: bool = False) -> None:
        rows, vectors = church_rows()
        build_library(path, rows[:1], vectors[:1], church=marked, church_import=True)

    def journal_mode(self, path: Path) -> str:
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as probe:
            return probe.execute("PRAGMA journal_mode").fetchone()[0]

    def is_marked(self, path: Path) -> bool:
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as probe:
            return is_your_church(probe)

    def test_the_name_half_of_recheck_refuses_a_name_swapped_after_the_open(self) -> None:
        """The -shm descriptor is already open, so only the by-name half sees the swap."""
        self.wal_church(self.sample)
        checked = library._Checked(self.sample)
        self.addCleanup(checked.close)
        self.assertTrue(Path(f"{self.sample}-shm").exists())
        self.plant(self.sample, "-shm")
        with self.assertRaises(UnsafeOpen) as caught:
            checked.recheck()
        self.assertIn("has a -shm file with 2 hard links", str(caught.exception))

    def test_the_recheck_after_the_first_read_refuses_before_any_sibling_is_cleared(self) -> None:
        """Planted once the target is connected: the first read opens it (WAL mode)."""
        self.wal_church(self.sample)
        self.wal_church(self.other, marked=True)
        real = sqlite3.connect
        fired = []

        def plant_after(database, *args, **kwargs):
            connection = real(database, *args, **kwargs)
            if not fired and kwargs.get("uri") and database.endswith("?mode=rw") and self.sample.name in database:
                fired.append(database)
                self.plant(self.sample)
            return connection

        cleared = []
        real_clear = library._clear_church_mark

        def clear(path):
            cleared.append(path)
            return real_clear(path)

        with (
            patch.object(library.sqlite3, "connect", plant_after),
            patch.object(library, "_clear_church_mark", clear),
            self.assertRaises(UnsafeOpen) as caught,
        ):
            mark_your_church_exclusive(self.sample, self.work)
        self.assertTrue(fired)
        self.assertIn("2 hard links", str(caught.exception))
        self.assertEqual(cleared, [])
        self.unplant(self.sample)
        self.assertTrue(self.is_marked(self.other))

    def test_the_recheck_before_the_wal_switch_leaves_a_rollback_target_unswitched(self) -> None:
        """Planted while the siblings are cleared; the target is in rollback mode."""
        _plain_marked(self.sample, church_import=True)
        with closing(sqlite3.connect(self.sample)) as writer:
            writer.execute("DELETE FROM meta")
            writer.commit()
        self.assertEqual(self.journal_mode(self.sample), "delete")
        before = self.sample.read_bytes()
        real_siblings = library._marked_siblings_not_cleared

        def siblings(index_dir, target):
            found = real_siblings(index_dir, target)
            self.plant(self.sample)
            return found

        with patch.object(library, "_marked_siblings_not_cleared", siblings), self.assertRaises(UnsafeOpen) as caught:
            mark_your_church_exclusive(self.sample, self.work)
        self.assertIn("has a -wal file with 2 hard links", str(caught.exception))
        self.unplant(self.sample)
        self.assertEqual(self.journal_mode(self.sample), "delete")
        self.assertEqual(self.sample.read_bytes(), before)

    def test_the_recheck_after_the_wal_switch_refuses_before_the_schema_is_written(self) -> None:
        """Planted just before ``PRAGMA journal_mode=WAL`` on a rollback target,
        so the switch opens the planted -wal. Seen by SQLite's trace hook."""
        _plain_marked(self.sample, church_import=True)
        with closing(sqlite3.connect(self.sample)) as writer:
            writer.execute("DELETE FROM meta")
            writer.commit()
        fired = []
        real_checked = library._Checked

        class Traced(real_checked):
            def __init__(inner, path):
                super().__init__(path)

                def trace(statement):
                    if not fired and statement.startswith("PRAGMA journal_mode=WAL"):
                        fired.append(statement)
                        self.plant(self.sample)

                inner.connection.set_trace_callback(trace)

        migrated = []
        real_migrate = library.migrate

        def migrate(connection):
            migrated.append(connection)
            return real_migrate(connection)

        with (
            patch.object(library, "_Checked", Traced),
            patch.object(library, "migrate", migrate),
            self.assertRaises(UnsafeOpen) as caught,
        ):
            mark_your_church_exclusive(self.sample, self.work)
        self.assertTrue(fired)
        self.assertIn("2 hard links", str(caught.exception))
        self.assertEqual(migrated, [])
        self.unplant(self.sample)
        self.assertFalse(self.is_marked(self.sample))

    def test_the_recheck_before_the_commit_leaves_the_target_unmarked(self) -> None:
        """Planted after the mark is written; the -wal descriptor is already open."""
        self.wal_church(self.sample)
        real_mark = library.mark_your_church

        def mark(connection, **kwargs):
            real_mark(connection, **kwargs)
            self.plant(self.sample)

        with patch.object(library, "mark_your_church", mark), self.assertRaises(UnsafeOpen) as caught:
            mark_your_church_exclusive(self.sample, self.work)
        self.assertIn("has a -wal file with 2 hard links", str(caught.exception))
        self.unplant(self.sample)
        self.assertFalse(self.is_marked(self.sample))

    def test_the_recheck_in_clear_church_mark_keeps_the_sibling_mark(self) -> None:
        """Planted on the sibling once it is open for writing and its shape is
        read, before the delete (the read-only ``church_shaped`` reads are skipped)."""
        self.wal_church(self.sample)
        self.wal_church(self.other, marked=True)
        real_shape = library._church_shape_problem
        fired = []

        def shape(connection):
            problem = real_shape(connection)
            files = {Path(row[2]) for row in connection.execute("PRAGMA database_list") if row[2]}
            writable = not connection.execute("PRAGMA query_only").fetchone()[0]
            if not fired and writable and self.other.resolve() in files:
                fired.append(True)
                self.plant(self.other)
            return problem

        with patch.object(library, "_church_shape_problem", shape):
            skipped = mark_your_church_exclusive(self.sample, self.work)
        self.assertTrue(fired)
        self.assertEqual([path for path, _why in skipped], [self.other])
        self.assertIn("has a -wal file with 2 hard links", skipped[0][1])
        self.unplant(self.other)
        self.assertTrue(self.is_marked(self.other))
        self.assertTrue(self.is_marked(self.sample))


class DescriptorTests(unittest.TestCase):
    """CTO round 1 on PR #27, should-fixes 1, 2 and 4."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.index_dir = Path(tmp.name) / "index"
        self.work = Path(tmp.name) / "work"
        self.index_dir.mkdir()
        self.work.mkdir()
        self.wesley = self.index_dir / "wesley.sqlite"
        _plain_marked(self.wesley)
        self.sample = self.work / "sample.sqlite"
        rows, vectors = church_rows()
        build_library(self.sample, rows[:1], vectors[:1], church_import=True)
        for target in (
            patch("preached.paths.INDEX_DIR", self.index_dir),
            patch("preached.paths.INDEX_PATH", self.wesley),
        ):
            target.start()
            self.addCleanup(target.stop)

    def test_a_reused_descriptor_number_counts_as_new(self) -> None:
        """SQLite gets a number that was open before; a benign file opens next.

        A diff of fd numbers alone saw only the benign file and passed, while
        the main file was the classic. The ``(st_dev, st_ino)`` snapshot sees
        both, and more than one new file is refused.
        """
        before = self.wesley.read_bytes()
        held = os.open(self.work / "held.bin", os.O_CREAT | os.O_RDWR)
        benign = []
        reused = []
        real = sqlite3.connect
        wesley_ino = os.stat(self.wesley).st_ino

        def reuse(database, *args, **kwargs):
            if kwargs.get("uri") and database.endswith("?mode=rw") and not reused:
                temp = self.work / "swap"
                os.link(self.wesley, temp)
                os.replace(temp, self.sample)
                os.close(held)
                connection = real(database, *args, **kwargs)
                reused.append(os.fstat(held).st_ino == wesley_ino)
                benign.append(os.open(self.work / "benign.bin", os.O_CREAT | os.O_RDWR))
                return connection
            return real(database, *args, **kwargs)

        try:
            with patch.object(library.sqlite3, "connect", reuse), self.assertRaises(UnsafeOpen) as caught:
                mark_your_church_exclusive(self.sample, self.work)
        finally:
            for fd in benign:
                os.close(fd)
        self.assertEqual(reused, [True])
        self.assertIn("2 new files, not 1", str(caught.exception))
        self.assertEqual(self.wesley.read_bytes(), before)

    def test_the_opened_file_must_be_the_one_the_name_points_at_after_the_connect(self) -> None:
        real = sqlite3.connect
        other = self.work / "elsewhere.sqlite"
        other.write_bytes(self.sample.read_bytes())

        def rename_after(database, *args, **kwargs):
            connection = real(database, *args, **kwargs)
            if kwargs.get("uri") and database.endswith("?mode=rw"):
                # The opened inode keeps its one link, under another name.
                os.rename(self.sample, self.work / "moved.sqlite")
                os.rename(other, self.sample)
            return connection

        with patch.object(library.sqlite3, "connect", rename_after), self.assertRaises(UnsafeOpen) as caught:
            mark_your_church_exclusive(self.sample, self.work)
        self.assertIn("is not the file SQLite opened", str(caught.exception))

    def test_a_dangling_symlink_swap_creates_no_file(self) -> None:
        """``mode=rw`` never creates: a swap for a link to a missing classic path writes nothing there."""
        spurgeon = self.index_dir / "spurgeon.sqlite"
        swap = _SwapOnConnect(self.sample, spurgeon, how="symlink")
        with swap.patch(), self.assertRaises(UnsafeOpen) as caught:
            mark_your_church_exclusive(self.sample, self.work)
        self.assertTrue(swap.fired)
        self.assertIn("could not be opened for writing", str(caught.exception))
        self.assertFalse(os.path.lexists(spurgeon))
        other = self.work / "other.sqlite"
        _plain_marked(other, church_import=True)
        rows, vectors = church_rows()
        self.sample.unlink()
        build_library(self.sample, rows[:1], vectors[:1], church_import=True)
        swap = _SwapOnConnect(other, spurgeon, how="symlink")
        with swap.patch():
            skipped = mark_your_church_exclusive(self.sample, self.work)
        self.assertTrue(swap.fired)
        self.assertEqual([path for path, _why in skipped], [other])
        self.assertIn("could not be opened for writing", skipped[0][1])
        self.assertFalse(os.path.lexists(spurgeon))

    def test_a_target_that_fails_once_opened_clears_no_sibling(self) -> None:
        other = self.work / "other.sqlite"
        _plain_marked(other, church_import=True)
        before = other.read_bytes()
        swap = _SwapOnConnect(self.sample, self.wesley)
        with swap.patch(), self.assertRaises(UnsafeOpen):
            mark_your_church_exclusive(self.sample, self.work)
        self.assertTrue(swap.fired)
        self.assertEqual(other.read_bytes(), before)
        with closing(sqlite3.connect(other)) as connection:
            self.assertTrue(is_your_church(connection))


class ChurchGateTripwireTests(unittest.TestCase):
    """Fails unless every church searcher goes through #12's publish gate.

    The church side is not served in this PR. When it is wired, it must use
    ``Searcher(gated=True)`` (``store.visible_sql``: approved sermons only),
    with no slug, so the public-domain exemption can never apply to it.
    """

    GATE = {"gated": True, "library": None}

    def _recorder(self, fail_model: Exception | None = None):
        built: list[dict] = []

        class Recorder:
            def __init__(self, connection, model=None, fingerprint=None, **gate):
                built.append(gate)
                if model and fail_model is not None:
                    raise fail_model
                self.connection = connection
                self._matrix = None

            def bm25(self, *_a, **_k):
                return []

            dense = hybrid = bm25

        return Recorder, built

    def test_server_church_searcher_is_gated_on_every_path(self) -> None:
        import app.server as server
        from preached.store import EmbeddingMismatch

        for kwargs, failure in (
            ({"bm25_only": True}, None),
            ({"bm25_only": False}, None),
            ({"bm25_only": False}, EmbeddingMismatch("stale")),
            ({"bm25_only": False}, RuntimeError("no vectors")),
        ):
            recorder, built = self._recorder(failure)
            with patch.object(server, "Searcher", recorder), patch.object(server.logging, "exception"):
                server.load_church_searcher(object(), "fixture", **kwargs)
            self.assertTrue(built)
            for gate in built:
                self.assertEqual(gate, self.GATE, (kwargs, failure))

    def test_cli_church_searcher_is_gated_on_every_path(self) -> None:
        from preached.store import EmbeddingMismatch

        module = _load_query()
        signals = Signals(bm25_hits=0, dense_top=None, agreement=False)
        for mode, failure in (("bm25", None), ("dense", None), ("hybrid", EmbeddingMismatch("stale"))):
            recorder, built = self._recorder(failure)
            args = SimpleNamespace(query="q", k=5, mode=mode, fusion="rrf", rrf_k=60, dense_weight=0.5)
            with (
                patch.object(module, "Searcher", recorder),
                patch.object(module, "compute_signals", lambda *_a, **_k: signals),
            ):
                module.search_index(None, args, np.ones(4, dtype=np.float32), "fixture", fallback_bm25=True, church=True, library="spurgeon")
            self.assertTrue(built)
            for gate in built:
                self.assertEqual(gate, self.GATE, mode)

    def test_unapproved_church_sermon_is_not_found_through_either_entry_point(self) -> None:
        import app.server as server

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.sqlite"
            rows, vectors = church_rows()
            build_library(path, rows, vectors, church=True, sample=True)
            writer = sqlite3.connect(path)
            writer.execute("UPDATE chunks SET video_id = sermon_id")
            # samplevid01 (churchonlytoken) is unapproved; samplevid02 (sharedpulpit) is approved
            # with its ASR coverage checked and nothing open.
            writer.executemany(
                "INSERT INTO videos (video_id, status, review_sha256, approved_sha256, coverage_gaps) VALUES (?, 'ok', 'abc', ?, '[]')",
                [("samplevid01", None), ("samplevid02", "abc")],
            )
            writer.commit()
            writer.close()
            connection = open_readonly(path)
            try:
                searcher, _note = server.load_church_searcher(connection, "fixture", bm25_only=True)
                self.assertEqual(searcher.bm25("churchonlytoken", 5), [])
                self.assertEqual([hit.chunk_id for hit in searcher.bm25("sharedpulpit", 5)], ["church-shared"])
                module = _load_query()
                for word, expected in (("churchonlytoken", []), ("sharedpulpit", ["church-shared"])):
                    args = SimpleNamespace(query=word, k=5, mode="bm25", fusion="rrf", rrf_k=60, dense_weight=0.5)
                    hits, *_rest = module.search_index(connection, args, None, None, fallback_bm25=True, church=True)
                    self.assertEqual([hit.chunk_id for hit in hits], expected, word)
            finally:
                connection.close()

    def test_every_searcher_passes_the_gate_or_is_a_named_classic_builder(self) -> None:
        """Source scan: every ``Searcher`` built in the server and the CLI passes ``gated=True``.

        The only exceptions are ``CLASSIC_BUILDERS``, and those may not
        mention church at all.
        """
        repo = Path(__file__).resolve().parents[1]
        offenders = []
        for rel in ("app/server.py", "search/query.py"):
            offenders += _ungated_searchers((repo / rel).read_text(), rel)
        self.assertEqual(offenders, [])

    def test_source_scan_requires_the_constant_true(self) -> None:
        """CTO round 1 on PR #27, should-fix 3: each of these used to pass."""
        source = """
import app.server as server
from preached.search import Searcher as Finder

def church_param(connection, **kwargs):
    return Searcher(connection, **kwargs)

def church_call(connection):
    return Searcher(connection, **make_gate())

def church_dict_without_gate(connection):
    gate = {"library": None}
    return Searcher(connection, **gate)

def church_reassigned(connection, other):
    gate = {"gated": True, "library": None}
    gate = other
    return Searcher(connection, **gate)

def church_false_keyword(connection):
    return Searcher(connection, gated=False)

def church_false_dict(connection):
    return Searcher(connection, **{"gated": False})

def church_either(connection, flag):
    gate = {"gated": True, "library": None} if flag else {"gated": False, "library": "wesley"}
    return Searcher(connection, **gate)

def church_updated(connection):
    gate = {"gated": True, "library": None}
    gate.update(gated=False)
    return Searcher(connection, **gate)

def church_item(connection):
    gate = {"gated": True, "library": None}
    gate["gated"] = False
    return Searcher(connection, **gate)

def church_variable(connection, flag):
    return Searcher(connection, gated=flag)

def church_positional(connection):
    return Searcher(connection, None, None, False)

def builder(connection):
    return server.Searcher(connection)

def aliased(connection):
    make = Searcher
    return make(connection)

def imported_alias(connection):
    return Finder(connection)

def passed_around(connection):
    return functools.partial(Searcher, connection)()

def load_search(connection):
    church = None
    return Searcher(connection)

class Holder:
    def build(self):
        return Searcher(self.connection, gated=self.gated)

def ok(connection, flag):
    gate = {"gated": True, "library": None}
    if flag:
        gate = {"gated": True, "library": None}
    return (
        Searcher(connection, **gate),
        Searcher(connection, gated=True),
        server.Searcher(connection, model="m", gated=True),
        Finder(connection, None, None, True),
        Searcher(connection, **{"gated": True}),
    )

def load_search(connection):
    return Searcher(connection)
"""
        flagged = [entry.split(" in ")[1] for entry in _ungated_searchers(source, "x.py", classic_builders={"load_search"})]
        self.assertEqual(
            flagged,
            [
                "church_param", "church_call", "church_dict_without_gate", "church_reassigned",
                "church_false_keyword", "church_false_dict", "church_either", "church_updated",
                "church_item", "church_variable", "church_positional", "builder", "aliased",
                "imported_alias", "passed_around", "load_search (a classic builder that mentions church)",
                "Holder.build",
            ],
        )

    def test_app_does_not_keep_an_ungated_church_searcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            classic_path = root / "wesley.sqlite"
            church_path = root / "sample.sqlite"
            build_library(classic_path, *classic_rows())
            build_library(church_path, *church_rows(), church=True, sample=True)
            connection = reopen(classic_path)
            church = reopen(church_path)
            try:
                app = App(
                    connection=connection,
                    searcher=Searcher(connection),
                    encode=None,
                    fallback_note=None,
                    model_name="fixture",
                    hosts={"127.0.0.1"},
                    static_dir=STATIC_DIR,
                    church_connection=church,
                    church_searcher=Searcher(church),
                    church_library="sample",
                )
                kept = app.church_searcher
                self.assertTrue(kept is None or kept.gated is True)
            finally:
                connection.close()
                church.close()


# Functions that build a classic-library Searcher, whose gate depends on the
# slug (App.gated, query.classic_searcher). None of them may mention church.
CLASSIC_BUILDERS = {
    "app/server.py": {"default_loader", "load_search", "App._searcher"},
    "search/query.py": {"classic_searcher"},
}


def _ungated_searchers(source: str, rel: str, classic_builders: set[str] | None = None) -> list[str]:
    """``Searcher`` uses that do not pass the constant ``gated=True``.

    A ``Searcher`` is the name, any alias of it (``import ... as X``,
    ``X = Searcher``), or any ``<module>.Searcher``. A call passes with a
    ``gated=True`` keyword, a fourth positional ``True``, ``**{"gated": True}``,
    or ``**name`` where ``name`` is not a parameter, is never mutated
    (``.update``, ``name[...] = ``, ``|=``), and every assignment to it in
    that function is a dict literal whose ``"gated"`` is the constant True.
    Any other use (``gated=flag``, ``partial(Searcher, ...)``) is flagged,
    except inside ``classic_builders`` (default ``CLASSIC_BUILDERS[rel]``),
    and a classic builder that mentions church is flagged too.
    """
    import ast

    builders = CLASSIC_BUILDERS.get(rel, set()) if classic_builders is None else classic_builders
    tree = ast.parse(source)
    aliases = {"Searcher"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            aliases |= {alias.asname for alias in node.names if alias.name == "Searcher" and alias.asname}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and _is_searcher(node.value, aliases):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id not in aliases:
                        aliases.add(target.id)
                        changed = True

    def true_gate_dict(node) -> bool:
        if not isinstance(node, ast.Dict):
            return False
        values = [v for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant) and k.value == "gated"]
        return len(values) == 1 and None not in node.keys and _is_true(values[0])

    def gated_true(call, func) -> bool:
        assigned: dict[str, list] = {}
        mutated: set[str] = set()
        for node in ast.walk(func):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned.setdefault(target.id, []).append(node.value)
                    elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                        mutated.add(target.value.id)
                    else:
                        mutated |= {leaf.id for leaf in ast.walk(target) if isinstance(leaf, ast.Name)}
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
                target = node.target
                if isinstance(target, ast.Subscript):
                    target = target.value
                if isinstance(target, ast.Name):
                    mutated.add(target.id)
            elif isinstance(node, ast.Delete):
                mutated |= {leaf.id for leaf in ast.walk(node) if isinstance(leaf, ast.Name)}
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                mutated.add(node.func.value.id)
        params = {arg.arg for arg in ast.walk(func.args) if isinstance(arg, ast.arg)} if func is not tree else set()
        if len(call.args) > 3 and _is_true(call.args[3]):
            return True
        for kw in call.keywords:
            if kw.arg == "gated" and _is_true(kw.value):
                return True
            if kw.arg is None and true_gate_dict(kw.value):
                return True
            if kw.arg is None and isinstance(kw.value, ast.Name):
                name = kw.value.id
                values = assigned.get(name, [])
                if name not in params and name not in mutated and values and all(true_gate_dict(v) for v in values):
                    return True
        return False

    def mentions_church(func) -> bool:
        names = {func.name}
        for node in ast.walk(func):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.arg):
                names.add(node.arg)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.keyword) and node.arg:
                names.add(node.arg)
        return any("church" in name.casefold() for name in names)

    offenders = []
    reported = set()

    def visit(node, qualname: str, func) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{qualname}.{child.name}" if qualname else child.name
                if isinstance(child, ast.ClassDef):
                    visit(child, name, func)
                    continue
                if name in builders and mentions_church(child):
                    offenders.append(f"{rel}:{child.lineno} in {name} (a classic builder that mentions church)")
                    continue
                visit(child, name, child)
                continue
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                continue
            if isinstance(child, ast.Assign) and _is_searcher(child.value, aliases):
                continue
            if isinstance(child, ast.Call) and _is_searcher(child.func, aliases):
                if qualname not in builders and not gated_true(child, func or tree):
                    offenders.append(f"{rel}:{child.lineno} in {qualname or '<module>'}")
                reported.add(id(child.func))
                for part in [*child.args, *child.keywords]:
                    visit(part, qualname, func)
                continue
            if _is_searcher(child, aliases) and id(child) not in reported and not _in_annotation(child, tree):
                if qualname not in builders:
                    offenders.append(f"{rel}:{child.lineno} in {qualname or '<module>'}")
                continue
            visit(child, qualname, func)

    visit(tree, "", None)
    seen = set()
    unique = []
    for entry in offenders:
        if entry not in seen:
            seen.add(entry)
            unique.append(entry)
    return unique


def _is_true(node) -> bool:
    import ast

    return isinstance(node, ast.Constant) and node.value is True


def _is_searcher(node, aliases: set[str]) -> bool:
    import ast

    if isinstance(node, ast.Name):
        return node.id in aliases
    return isinstance(node, ast.Attribute) and node.attr == "Searcher"


def _in_annotation(node, tree) -> bool:
    """True when ``node`` sits in a type annotation (``-> Searcher``, ``x: Searcher``)."""
    import ast

    for parent in ast.walk(tree):
        annotations = []
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotations.append(parent.returns)
        elif isinstance(parent, ast.arg):
            annotations.append(parent.annotation)
        elif isinstance(parent, ast.AnnAssign):
            annotations.append(parent.annotation)
        for annotation in annotations:
            if annotation is not None and any(sub is node for sub in ast.walk(annotation)):
                return True
    return False


def _plain_marked(path: Path, *, church_import: bool = False) -> None:
    """A church-marked file that did not go through store.connect (no WAL).

    Wesley-shaped unless ``church_import`` adds a ``videos`` table and
    ``chunks.video_id`` (``library.church_shaped``).
    """
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO meta (key, value) VALUES ('role', 'church')")
        if church_import:
            connection.execute("CREATE TABLE chunks (chunk_id TEXT, text TEXT, video_id TEXT)")
            connection.execute("CREATE TABLE videos (video_id TEXT PRIMARY KEY, status TEXT)")
        else:
            connection.execute("CREATE TABLE chunks (chunk_id TEXT, text TEXT)")
        connection.execute(
            "INSERT INTO chunks (chunk_id, text) VALUES ('wesley-001-c0000', ?)",
            ("By grace are ye saved through faith. " * 20,),
        )
        connection.commit()
    finally:
        connection.close()


class SideApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.classic_path = root / "wesley.sqlite"
        cls.church_path = root / "sample.sqlite"
        build_library(cls.classic_path, *classic_rows())
        build_library(cls.church_path, *church_rows(), church=True, sample=True)
        cls.both = Running(make_app(cls.classic_path, cls.church_path))
        cls.classic_only = Running(make_app(cls.classic_path, None))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.both.close()
        cls.classic_only.close()
        cls.tmp.cleanup()

    def test_search_stays_inside_one_library(self) -> None:
        status, headers, body = self.both.get(
            "/api/search?q=classiconlytoken&library=wesley&mode=bm25&k=5"
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Security-Policy"], CSP)
        self.assertNotIn("unsafe-inline", headers["Content-Security-Policy"])
        payload = json.loads(body)
        self.assertGreaterEqual(len(payload["results"]), 1)
        self.assertLessEqual(len(payload["results"]), 5)
        self.assertIn("classiconlytoken", texts(payload))
        self.assertNotIn("churchonlytoken", texts(payload))
        self.assertTrue(sermon_ids(payload) <= {"wesley-001", "wesley-002", "wesley-003"})
        for hit in payload["results"]:
            self.assertEqual(set(hit), RESULT_KEYS)
            self.assertEqual(hit["audio_url"], CLASSIC_AUDIO)

        # A church slug is not an open library. Same 400 as a server with no church file.
        for slug in ("sample", "spurgeon"):
            status, _, body = self.both.get(f"/api/search?q=churchonlytoken&library={slug}&mode=bm25")
            self.assertEqual(status, 400, slug)
            self.assertEqual(json.loads(body)["error"], "library must be wesley")
            self.assert_no_church_payload(body)
            only_status, _, only_body = self.classic_only.get(
                f"/api/search?q=churchonlytoken&library={slug}&mode=bm25"
            )
            self.assertEqual(status, only_status)
            self.assertEqual(json.loads(body)["error"], json.loads(only_body)["error"])

        status, _, body = self.both.get("/api/search?q=churchonlytoken&library=wesley&mode=bm25")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["results"], [])
        self.assert_no_church_payload(body)

        status, _, body = self.both.get("/api/search?q=classiconlytoken&mode=bm25&k=1")
        self.assertEqual(status, 200)
        scoped = json.loads(body)
        self.assertEqual(len(scoped["results"]), 1)
        self.assertNotIn("churchonlytoken", texts(scoped))

    def test_side_by_side_abstains_per_side_and_labels_sample_data(self) -> None:
        status, headers, body = self.both.get("/api/side?q=classiconlytoken&mode=bm25&k=1")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Security-Policy"], CSP)
        payload = json.loads(body)
        self.assertEqual(set(payload), {"query", "mode", "k", "took_ms", "classic", "church"})
        self.assertEqual(payload["k"], 1)
        self.assertEqual(payload["mode"], "bm25")
        classic = payload["classic"]
        church = payload["church"]
        self.assertEqual(set(classic), SIDE_KEYS)
        self.assertEqual(set(church), SIDE_KEYS)
        self.assertEqual(classic["library"], "wesley")
        self.assertEqual(classic["label"], "John Wesley")
        self.assertFalse(classic["sample"])
        self.assertTrue(classic["present"])
        self.assertFalse(classic["empty"])
        self.assertIsNone(classic["message"])
        self.assertFalse(classic["abstain"])
        self.assertEqual(classic["confidence"]["level"], "unrated")
        self.assertEqual(len(classic["results"]), 1)
        self.assertIn("classiconlytoken", texts(classic))
        self.assertNotIn("churchonlytoken", texts(classic))
        self.assert_missing_church(church)
        self.assert_no_church_payload(json.dumps(church).encode())

        only_status, _, only_body = self.classic_only.get("/api/side?q=classiconlytoken&mode=bm25&k=1")
        self.assertEqual(only_status, 200)
        only = json.loads(only_body)
        self.assertEqual(_without_took(payload), _without_took(only))

        status, _, body = self.both.get("/api/side?q=churchonlytoken&mode=bm25&k=5")
        swapped = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(swapped["classic"]["abstain"])
        self.assertEqual(swapped["classic"]["results"], [])
        self.assert_missing_church(swapped["church"])
        self.assert_no_church_payload(body)

    def test_configured_church_matches_the_no_church_responses(self) -> None:
        """A fixture church file must not change /api/side, /api/search, or /healthz."""
        side_both = self.both.get("/api/side?q=sharedpulpit&mode=bm25&k=5")
        side_only = self.classic_only.get("/api/side?q=sharedpulpit&mode=bm25&k=5")
        self.assertEqual(side_both[0], 200)
        self.assertEqual(side_only[0], 200)
        both_payload = json.loads(side_both[2])
        only_payload = json.loads(side_only[2])
        self.assertEqual(_without_took(both_payload), _without_took(only_payload))
        self.assert_missing_church(both_payload["church"])
        self.assertFalse(both_payload["church"]["present"])
        self.assert_no_church_payload(side_both[2])

        health_both = json.loads(self.both.get("/healthz")[2])
        health_only = json.loads(self.classic_only.get("/healthz")[2])
        self.assertIsNone(health_both["church"])
        self.assertEqual(health_both, health_only)

    def test_low_confidence_is_per_side(self) -> None:
        status, _, body = self.both.get("/api/side?q=sharedpulpit&mode=hybrid&k=5")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        classic = payload["classic"]
        church = payload["church"]
        self.assertFalse(classic["abstain"])
        self.assertEqual(classic["confidence"]["level"], "strong")
        self.assert_missing_church(church)
        self.assertIn("sharedpulpit", texts(classic))
        self.assertTrue(all(hit["audio_url"] == CLASSIC_AUDIO for hit in classic["results"]))
        self.assert_no_church_payload(json.dumps(church).encode())
        only = json.loads(self.classic_only.get("/api/side?q=sharedpulpit&mode=hybrid&k=5")[2])
        self.assertEqual(_without_took(payload), _without_took(only))

    def test_missing_church_is_an_empty_side_not_an_error(self) -> None:
        status, _, body = self.classic_only.get("/api/side?q=classiconlytoken&mode=bm25")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        church = payload["church"]
        self.assertFalse(church["present"])
        self.assertTrue(church["empty"])
        self.assertIsNone(church["library"])
        self.assertEqual(church["message"], CHURCH_EMPTY)
        self.assertEqual(church["results"], [])
        self.assertFalse(church["abstain"])
        self.assertIsNone(church["confidence"])
        self.assertGreaterEqual(len(payload["classic"]["results"]), 1)

        status, _, body = self.classic_only.get("/api/side?q=classiconlytoken&library=sample&mode=bm25")
        self.assertEqual(status, 400)
        self.assertIn("library must be wesley", json.loads(body)["error"])

        status, _, body = self.both.get("/api/side")
        self.assertEqual(status, 400)

    def test_church_without_vectors_does_not_drop_the_classic_side(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            classic_path = root / "wesley.sqlite"
            bare_path = root / "sample.sqlite"
            build_library(classic_path, *classic_rows())
            bare = connect(bare_path)
            _insert(
                bare,
                chunk_id="bare",
                sermon_id="samplevid01",
                sermon_title="On Mercy",
                text="churchonlytoken mercy with no vectors yet.",
                audio_url=CHURCH_AUDIO,
                text_source="asr",
                reader=None,
                sermon_number=None,
            )
            bare.commit()
            bare.close()

            def loader(connection, _model_key):
                return Searcher(connection, model="fixture", fingerprint=FIXTURE_FP), encode_fixture

            app = build_app(
                reopen(classic_path),
                model_key="granite-english-r2",
                bm25_only=False,
                hosts={"127.0.0.1", "localhost"},
                static_dir=STATIC_DIR,
                loader=loader,
                floor=0.5,
                library="wesley",
                church_connection=reopen(bare_path),
                church_library="sample",
            )
            payload = app.side("churchonlytoken", 5, "hybrid")
            self.assert_missing_church(payload["church"])
            self.assert_no_church_payload(json.dumps(payload["church"]).encode())
            classic = app.side("classiconlytoken", 5, "hybrid")
            self.assertIn("classiconlytoken", texts(classic["classic"]))
            self.assertTrue(all(hit["audio_url"] == CLASSIC_AUDIO for hit in classic["classic"]["results"]))
            self.assert_missing_church(classic["church"])

    def test_classic_side_covers_spurgeon_and_edwards(self) -> None:
        """Spurgeon and edwards are classic libraries. The church column stays empty."""
        for slug in ("spurgeon", "edwards"):
            with self.subTest(slug=slug), tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
                root = Path(tmp)
                # #12 gates a public-domain slug unless the file is its own
                # canonical owner-only build (store.public_domain_file). The
                # temp dir is 0700 and ours; INDEX_DIR under it is 0755, so
                # the real classic_file_problem passes INDEX_DIR/<slug>.sqlite.
                index_dir = root / "index"
                index_dir.mkdir(mode=0o755)
                stack.enter_context(patch("preached.paths.INDEX_DIR", index_dir))
                classic_path = index_dir / f"{slug}.sqlite"
                church_path = root / "sample.sqlite"
                build_library(classic_path, *classic_rows())
                build_library(church_path, *church_rows(), church=True, sample=True)
                marked = sqlite3.connect(classic_path)
                marked.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('library', ?)", (slug,))
                marked.commit()
                marked.close()
                from preached.store import classic_file_problem

                probe = reopen(classic_path)
                try:
                    self.assertIsNone(classic_file_problem(probe, slug))
                finally:
                    probe.close()
                connection = reopen(classic_path)
                app = App(
                    connection=connection,
                    searcher=Searcher(connection, model="fixture", fingerprint=FIXTURE_FP),
                    encode=encode_fixture,
                    fallback_note=None,
                    model_name="fixture",
                    hosts={"127.0.0.1", "localhost"},
                    static_dir=STATIC_DIR,
                    library=slug,
                    floor=0.5,
                    church_connection=reopen(church_path),
                    church_library="sample",
                    church_label="Your church",
                )
                running = Running(app)
                try:
                    status, _, body = running.get(
                        f"/api/search?q=classiconlytoken&library={slug}&mode=bm25&k=5"
                    )
                    self.assertEqual(status, 200, slug)
                    payload = json.loads(body)
                    self.assertIn("classiconlytoken", texts(payload))
                    self.assertNotIn("churchonlytoken", texts(payload))
                    self.assert_no_church_payload(body)
                    bad, _, bad_body = running.get(
                        "/api/search?q=classiconlytoken&library=sample&mode=bm25"
                    )
                    self.assertEqual(bad, 400, slug)
                    self.assertEqual(json.loads(bad_body)["error"], f"library must be {slug}")
                    side_status, _, side_body = running.get(
                        "/api/side?q=classiconlytoken&mode=bm25&k=1"
                    )
                    self.assertEqual(side_status, 200, slug)
                    side = json.loads(side_body)
                    self.assertEqual(side["classic"]["library"], slug)
                    self.assertEqual(side["classic"]["label"], slug)
                    self.assertIn("classiconlytoken", texts(side["classic"]))
                    self.assert_missing_church(side["church"])
                    self.assert_no_church_payload(json.dumps(side["church"]).encode())
                    health = json.loads(running.get("/healthz")[2])
                    self.assertEqual(health["library"], slug)
                    self.assertIsNone(health["church"])
                finally:
                    running.close()

    def assert_missing_church(self, church: dict) -> None:
        self.assertEqual(
            church,
            {
                "library": None,
                "label": "Your church",
                "sample": False,
                "present": False,
                "empty": True,
                "message": CHURCH_EMPTY,
                "mode": None,
                "results": [],
                "note": None,
                "abstain": False,
                "confidence": None,
            },
        )

    def assert_no_church_payload(self, body: bytes) -> None:
        """Church fixture text must not appear outside the echoed query."""
        payload = json.loads(body)
        scrubbed = json.dumps(_drop_query(payload), ensure_ascii=False).encode()
        self.assertNotIn(b"churchonlytoken", scrubbed)
        self.assertNotIn(b"samplevid01", scrubbed)
        self.assertNotIn(b"samplevid02", scrubbed)
        self.assertNotIn(b"youtube.com", scrubbed)
        self.assertNotIn(b"On Mercy", scrubbed)
        self.assertNotIn(b"On Hope", scrubbed)
        self.assertNotIn(WATCH.encode(), scrubbed)
        self.assertNotIn(CHURCH_AUDIO.encode(), scrubbed)


class SideCliTests(unittest.TestCase):
    def test_side_flag_prints_both_columns(self) -> None:
        module = _load_query()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            classic = root / "wesley.sqlite"
            church = root / "sample.sqlite"
            build_library(classic, *classic_rows())
            build_library(church, *church_rows(), church=True, sample=True)
            out = StringIO()
            with redirect_stdout(out):
                module.main(
                    [
                        "classiconlytoken",
                        "--mode",
                        "bm25",
                        "-k",
                        "5",
                        "--side",
                        "--index",
                        str(classic),
                        "--church-index",
                        str(church),
                    ]
                )
            text = out.getvalue()
            classic_body = _section(text, "Classic library: John Wesley")
            church_body = _section(text, "Your church")
            self.assertIn("classiconlytoken", classic_body)
            self.assertNotIn("churchonlytoken", classic_body)
            self.assertIn("confidence: unrated", classic_body)
            self.assertIn(CLASSIC_AUDIO, classic_body)
            self.assertIn(CHURCH_EMPTY, church_body)
            self.assertNotIn("confidence:", church_body)
            self.assertNotIn("sample data", church_body)
            self.assertNotIn("churchonlytoken", text)
            self.assertNotIn("youtube.com", text)
            self.assertNotIn(CHURCH_AUDIO, text)

            missing = StringIO()
            with redirect_stdout(missing):
                module.main(
                    [
                        "classiconlytoken",
                        "--mode",
                        "bm25",
                        "-k",
                        "5",
                        "--side",
                        "--index",
                        str(classic),
                        "--church-index",
                        str(root / "absent.sqlite"),
                    ]
                )
            absent = missing.getvalue()
            self.assertEqual(text, absent)
            self.assertIn("## Your church\n", absent)
            self.assertIn(CHURCH_EMPTY, _section(absent, "Your church"))

    def test_classic_church_slug_is_refused(self) -> None:
        module = _load_query()
        for slug in ("wesley", "spurgeon", "edwards"):
            with self.assertRaises(SystemExit) as caught:
                module.main(
                    [
                        "mercy",
                        "--mode",
                        "bm25",
                        "--side",
                        "--church-library",
                        slug,
                    ]
                )
            self.assertIn("classic", str(caught.exception))

    def test_classic_side_prints_spurgeon_and_edwards(self) -> None:
        module = _load_query()
        for slug in ("spurgeon", "edwards"):
            with self.subTest(slug=slug), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                classic = root / f"{slug}.sqlite"
                church = root / "sample.sqlite"
                build_library(classic, *classic_rows())
                build_library(church, *church_rows(), church=True, sample=True)
                out = StringIO()
                with redirect_stdout(out):
                    module.main(
                        [
                            "classiconlytoken",
                            "--mode",
                            "bm25",
                            "-k",
                            "5",
                            "--side",
                            "--index",
                            str(classic),
                            "--church-index",
                            str(church),
                        ]
                    )
                text = out.getvalue()
                self.assertIn(f"## Classic library: {slug}", text)
                self.assertIn("classiconlytoken", _section(text, f"Classic library: {slug}"))
                self.assertIn(CHURCH_EMPTY, _section(text, "Your church"))
                self.assertNotIn("churchonlytoken", text)
                self.assertNotIn("sample data", text)
                self.assertNotIn("youtube.com", text)

    def test_church_confidence_is_unrated_not_the_wesley_floor(self) -> None:
        signals = Signals(bm25_hits=1, dense_top=0.2, agreement=True)
        self.assertEqual(decide(signals, 0.5, has_results=True).level, "weak")
        rated = church_confidence(signals, has_results=True)
        self.assertEqual(rated.level, "unrated")
        self.assertFalse(rated.calibrated)
        self.assertIsNone(rated.floor)
        self.assertFalse(rated.abstain)
        strong = Signals(bm25_hits=2, dense_top=0.9, agreement=True)
        self.assertEqual(decide(strong, 0.5, has_results=True).level, "strong")
        self.assertEqual(church_confidence(strong, has_results=True).level, "unrated")
        low = Signals(bm25_hits=0, dense_top=0.1, agreement=False)
        self.assertEqual(decide(low, 0.5, has_results=True).level, "none")
        self.assertEqual(church_confidence(low, has_results=True).level, "unrated")
        empty = church_confidence(signals, has_results=False)
        self.assertEqual(empty.level, "none")
        self.assertFalse(empty.calibrated)
        self.assertIsNone(empty.floor)

        module = _load_query()

        built: list[dict] = []

        class FakeSearcher:
            def __init__(self, connection, model=None, **gate):
                built.append(gate)
                self.connection = connection
                self._matrix = np.ones((1, 4), dtype=np.float32)
                self._rowids = [1]

            def hybrid(self, *_args, **_kwargs):
                return [object()]

            def dense(self, *_args, **_kwargs):
                return [object()]

            def bm25(self, *_args, **_kwargs):
                return [object()]

        args = SimpleNamespace(
            query="classiconlytoken",
            k=5,
            mode="hybrid",
            fusion="rrf",
            rrf_k=60,
            dense_weight=0.5,
        )
        floors: list = []

        def floor_for(*pos, **_kwargs):
            floors.append(pos)
            return 0.5

        vector = np.ones(4, dtype=np.float32)
        with (
            patch.object(module, "Searcher", FakeSearcher),
            patch.object(module, "compute_signals", lambda *_a, **_k: signals),
            patch.object(module, "floor_for", floor_for),
        ):
            _hits, confidence, *_rest = module.search_index(
                None, args, vector, "fixture", fallback_bm25=True, church=True
            )
        self.assertEqual(confidence.level, "unrated")
        self.assertEqual(floors, [])
        self.assertEqual(built, [{"gated": True, "library": None}])
        with (
            patch.object(module, "Searcher", FakeSearcher),
            patch.object(module, "compute_signals", lambda *_a, **_k: signals),
            patch.object(module, "floor_for", floor_for),
        ):
            _hits, wesley, *_rest = module.search_index(
                None, args, vector, "fixture", fallback_bm25=False, church=False
            )
        self.assertEqual(wesley.level, "weak")
        self.assertTrue(floors)


class ChurchRefusalTests(unittest.TestCase):
    def test_explicit_classic_slug_is_refused_and_a_marked_copy_is_not_opened(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            classic = root / "built.sqlite"
            build_library(classic, *classic_rows())
            for slug in ("wesley", "spurgeon", "edwards"):
                path = root / f"{slug}.sqlite"
                _plain_marked(path)
                before = path.read_bytes()
                with self.assertRaises(SystemExit) as caught:
                    prepare_church(church_index=None, church_library=slug)
                self.assertIn(slug, str(caught.exception))
                self.assertIn("classic", str(caught.exception))
                with self.assertRaises(SystemExit):
                    prepare_church(church_index=path, church_library=None)
                self.assertEqual(path.read_bytes(), before)
            # A missing classic name is still refused.
            absent = root / "gone" / "edwards.sqlite"
            with self.assertRaises(SystemExit):
                prepare_church(church_index=absent, church_library=None)
            titled = root / "Wesley.sqlite"
            _plain_marked(titled)
            titled_before = titled.read_bytes()
            with self.assertRaises(SystemExit) as titled_exit:
                prepare_church(church_index=titled, church_library=None)
            self.assertIn("classic", str(titled_exit.exception))
            self.assertEqual(titled.read_bytes(), titled_before)
            # No church named: nothing is scanned, opened, or refused.
            self.assertIsNone(prepare_church(church_index=None, church_library=None))
            sample = root / "sample.sqlite"
            rows, vectors = church_rows()
            build_library(sample, rows[:1], vectors[:1], church=True, sample=True)
            before = sample.read_bytes()
            # Startup output is the same with or without a church: no log line.
            with self.assertNoLogs(level="DEBUG"):
                self.assertIsNone(prepare_church(church_index=None, church_library="sample"))
                self.assertIsNone(prepare_church(church_index=sample, church_library=None))
                self.assertIsNone(prepare_church(church_index=root / "missing.sqlite", church_library=None))
            self.assertEqual(sample.read_bytes(), before)
            self.assertFalse(sample.with_name(sample.name + "-shm").exists())
            self.assertFalse(sample.with_name(sample.name + "-wal").exists())

    def test_canonical_path_refusal_uses_classic_index_problem(self) -> None:
        """A path #14 would serve as spurgeon cannot be the church, whatever its name."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            classic = root / "built.sqlite"
            build_library(classic, *classic_rows())
            weird = root / "copy.sqlite"
            _plain_marked(weird)
            before = weird.read_bytes()

            def gate(slug, path, index_dir=None):
                if slug == "spurgeon" and Path(path) == weird:
                    return None
                from preached.libraries import classic_index_problem as real

                return real(slug, path, index_dir)

            with patch("preached.library.classic_index_problem", side_effect=gate):
                with self.assertRaises(SystemExit) as caught:
                    prepare_church(church_index=weird, church_library=None)
            self.assertIn("classic", str(caught.exception))
            self.assertEqual(weird.read_bytes(), before)
            self.assertFalse(weird.with_name(weird.name + "-wal").exists())


def _without_took(payload: dict) -> dict:
    copy = json.loads(json.dumps(payload))
    copy.pop("took_ms", None)
    return copy


def _drop_query(value):
    """Remove echoed ``query`` fields so a church-token query is not a hit."""
    if isinstance(value, dict):
        return {key: _drop_query(item) for key, item in value.items() if key != "query"}
    if isinstance(value, list):
        return [_drop_query(item) for item in value]
    return value


def _section(text: str, heading: str) -> str:
    marker = f"## {heading}"
    start = text.index(marker)
    rest = text[start + len(marker) :]
    nxt = rest.find("\n## ")
    return rest if nxt < 0 else rest[:nxt]


def _load_query():
    path = Path(__file__).resolve().parents[1] / "search" / "query.py"
    spec = importlib.util.spec_from_file_location("preached_query_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
