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

import build_library  # noqa: E402
import query  # noqa: E402
import run  # noqa: E402
from preached import libraries  # noqa: E402
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


REFUSED = ("wesley", "talmage", "gaston", "unknown-slug", "../spurgeon", "", "SPURGEON")


def exit_message(fn, *args) -> str:
    with contextlib.redirect_stderr(io.StringIO()), mock.patch.object(sys, "argv", ["x", *args]):
        try:
            fn()
        except SystemExit as exc:
            if exc.code in (0, None):
                raise AssertionError(f"{fn.__module__} exited 0 for {args}") from None
            return str(exc.code)
    raise AssertionError(f"{fn.__module__} did not exit for {args}")


class AllowListTests(unittest.TestCase):
    def test_allow_list_is_exactly_spurgeon_and_edwards(self) -> None:
        self.assertEqual(set(libraries.PUBLIC_DOMAIN), {"spurgeon", "edwards"})

    def test_each_allowed_library_has_committed_provenance(self) -> None:
        for slug in libraries.PUBLIC_DOMAIN:
            path = libraries.provenance_path(slug)
            self.assertEqual(path, ROOT / "ingest" / "manifest" / f"{slug}.provenance.json")
            self.assertTrue(path.is_file(), path)
            self.assertTrue(libraries.is_public_domain(slug))

    def test_wesley_and_unknown_slugs_are_not_public_domain(self) -> None:
        for slug in (*REFUSED, None, 3):
            with self.subTest(slug=slug):
                self.assertFalse(libraries.is_public_domain(slug))
        with self.assertRaises(ValueError):
            libraries.provenance_path("wesley")

    def test_missing_provenance_is_not_public_domain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(libraries, "repo_root", lambda: Path(tmp)):
            self.assertFalse(libraries.is_public_domain("spurgeon"))

    def test_build_library_refuses_wesley(self) -> None:
        message = exit_message(build_library.main, "wesley")
        self.assertIn("'wesley' is not a public-domain library", message)

    def test_build_library_refuses_unknown_slugs(self) -> None:
        for slug in REFUSED:
            with self.subTest(slug=slug):
                self.assertIn("not a public-domain library", exit_message(build_library.main, slug))

    def test_ingest_run_refuses_wesley(self) -> None:
        message = exit_message(run.main, "--library", "wesley", "--all")
        self.assertIn("--library 'wesley' refused", message)
        self.assertIn("leave out --library", message)

    def test_ingest_run_refuses_unknown_slugs(self) -> None:
        for slug in REFUSED:
            with self.subTest(slug=slug):
                self.assertIn("refused", exit_message(run.main, "--library", slug, "--all"))

    def test_allowed_slugs_pass(self) -> None:
        for slug in libraries.PUBLIC_DOMAIN:
            self.assertEqual(build_library.check_slug(slug), slug)
            self.assertEqual(run.check_library(slug), slug)


class BuildTargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_wesley_style_index_is_refused(self) -> None:
        path = self.dir / "spurgeon.sqlite"
        connection = connect(path)
        connection.execute(
            "INSERT INTO chunks (chunk_id, sermon_id, sermon_title, text) VALUES ('w-1', 'w', 'Salvation', 'By grace')"
        )
        connection.commit()
        connection.close()
        with self.assertRaises(SystemExit) as ctx:
            build_library.check_target(path, "spurgeon")
        self.assertIn("not a library file", str(ctx.exception.code))

    def test_other_librarys_file_is_refused(self) -> None:
        path = self.dir / "spurgeon.sqlite"
        connection = open_library(path)
        connection.execute("INSERT INTO meta (key, value) VALUES ('library', 'edwards')")
        connection.commit()
        connection.close()
        with self.assertRaises(SystemExit):
            build_library.check_target(path, "spurgeon")
        build_library.check_target(path, "edwards")

    def test_new_or_own_file_is_accepted(self) -> None:
        build_library.check_target(self.dir / "missing.sqlite", "spurgeon")
        path = self.dir / "spurgeon.sqlite"
        open_library(path).close()  # a library file from before the marker
        build_library.check_target(path, "spurgeon")


if __name__ == "__main__":
    unittest.main()
