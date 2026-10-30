"""W3-LIB fix-up: which index gets the Wesley sync, and which slugs may be
ingested or indexed as public-domain libraries."""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingest"))
sys.path.insert(0, str(ROOT / "search"))

import query  # noqa: E402
from preached.store import connect  # noqa: E402
from preached.youtube.library import open_library  # noqa: E402


def run_main(argv: list[str]) -> tuple[int | str | None, str]:
    """Run query.main with argv; return (exit code or message, stderr)."""
    err = io.StringIO()
    with mock.patch.object(sys, "argv", ["query.py", *argv]), contextlib.redirect_stderr(err):
        try:
            query.main()
        except SystemExit as exc:
            return exc.code, err.getvalue()
    return None, err.getvalue()


class QueryIndexTargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.wesley = self.dir / "wesley.sqlite"
        patches = [
            mock.patch.object(query, "INDEX_PATH", self.wesley),
            mock.patch.object(query, "INDEX_DIR", self.dir),
            mock.patch.object(query, "ensure_chunks"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.synced = query.ensure_chunks

    def library_file(self, name: str) -> Path:
        path = self.dir / name
        open_library(path).close()
        return path

    def test_index_and_library_are_mutually_exclusive(self) -> None:
        self.library_file("spurgeon.sqlite")
        code, err = run_main(["q", "--mode", "bm25", "--index", str(self.wesley), "--library", "spurgeon"])
        self.assertEqual(code, 2)
        self.assertIn("not allowed with argument", err)
        self.synced.assert_not_called()

    def test_library_style_index_is_refused_unchanged(self) -> None:
        # The CTO repro: a classics file passed as --index became Wesley chunks.
        path = self.library_file("spurgeon.sqlite")
        before = path.read_bytes()
        code, _ = run_main(["q", "--mode", "bm25", "--index", str(path)])
        self.assertIn("is a library index", str(code))
        self.assertIn("--library spurgeon", str(code))
        self.synced.assert_not_called()
        self.assertEqual(path.read_bytes(), before)

    def test_library_marker_in_meta_is_refused(self) -> None:
        path = self.dir / "copy.sqlite"
        connection = connect(path)
        connection.execute("INSERT INTO meta (key, value) VALUES ('library', 'edwards')")
        connection.commit()
        connection.close()
        self.assertTrue(query.is_library_file(path))
        with self.assertRaises(SystemExit):
            query.open_index(path, None)
        self.synced.assert_not_called()

    def test_wesley_index_is_synced(self) -> None:
        query.open_index(None, None).close()
        query.open_index(self.wesley, None).close()
        self.assertEqual(self.synced.call_count, 2)

    def test_other_index_path_is_not_synced(self) -> None:
        other = self.dir / "wesley-onnx-int8.sqlite"
        connect(other).close()
        self.assertFalse(query.is_library_file(other))
        query.open_index(other, None).close()
        self.synced.assert_not_called()

    def test_library_flag_never_syncs(self) -> None:
        self.library_file("edwards.sqlite")
        query.open_index(None, "edwards").close()
        self.synced.assert_not_called()
        with self.assertRaises(SystemExit):
            query.open_index(None, "../edwards")


if __name__ == "__main__":
    unittest.main()
