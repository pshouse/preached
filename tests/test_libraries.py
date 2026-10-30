"""W3-LIB fix-up: which index gets the Wesley sync, and which slugs may be
ingested or indexed as public-domain libraries."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingest"))
sys.path.insert(0, str(ROOT / "search"))

import app.server as server  # noqa: E402
import build_library  # noqa: E402
import manifest  # noqa: E402
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

    def test_plain_sqlite_index_is_opened_read_only(self) -> None:
        # The CTO repro: a plain SQLite file gained index tables and switched to WAL.
        path = self.dir / "plain.sqlite"
        raw = sqlite3.connect(path)
        raw.execute("CREATE TABLE notes (x TEXT)")
        raw.execute("INSERT INTO notes VALUES ('keep me')")
        raw.commit()
        raw.close()
        before = path.read_bytes()
        code, _ = run_main(["q", "--mode", "bm25", "--index", str(path)])
        self.assertIn("not a search index", str(code))
        self.assertEqual(path.read_bytes(), before)
        for suffix in ("-wal", "-shm", "-journal"):
            self.assertFalse(Path(f"{path}{suffix}").exists(), suffix)
        self.synced.assert_not_called()

    def test_nonexistent_index_is_refused_and_not_created(self) -> None:
        path = self.dir / "nope" / "missing.sqlite"
        code, _ = run_main(["q", "--mode", "bm25", "--index", str(path)])
        self.assertIn("missing index", str(code))
        self.assertFalse(path.exists())
        self.assertFalse(path.parent.exists())

    def test_library_flag_is_read_only_and_allow_listed(self) -> None:
        path = self.library_file("spurgeon.sqlite")
        before = path.read_bytes()
        connection = query.open_index(None, "spurgeon")
        with self.assertRaises(sqlite3.OperationalError):
            connection.execute("INSERT INTO meta (key, value) VALUES ('x', 'y')")
        connection.close()
        # The file is WAL already (build_library.py writes it so). Any reader of a
        # WAL file may create an empty -wal and the -shm index; no data is written.
        self.assertEqual(path.read_bytes(), before)
        wal = Path(f"{path}-wal")
        self.assertTrue(not wal.exists() or wal.stat().st_size == 0)
        self.library_file("cc-speech.sqlite")
        for slug in ("cc-speech", "wesley", "talmage"):
            with self.subTest(slug=slug):
                code, _ = run_main(["q", "--mode", "bm25", "--library", slug])
                self.assertIn("refused", str(code))
        # Allow-listed but not built yet: refused, not created.
        code, _ = run_main(["q", "--mode", "bm25", "--library", "edwards"])
        self.assertIn("missing index", str(code))
        self.assertFalse((self.dir / "edwards.sqlite").exists())


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


class AudioUrlTests(unittest.TestCase):
    GOOD = "https://archive.org/download/spurgeons_sermons_librivox/sermon_0191_spurgeon_64kb.mp3"

    def test_control_characters_are_refused(self) -> None:
        for bad in (self.GOOD + "\n", self.GOOD + "\r\n", self.GOOD + "\t", "\n" + self.GOOD,
                    self.GOOD.replace("download", "down\nload"), self.GOOD + "\x00", self.GOOD + "\x1b[2J",
                    self.GOOD + "\x7f", self.GOOD + "\x85", self.GOOD + " ", "https://archive.org/a b.mp3"):
            with self.subTest(url=bad), self.assertRaises(manifest.UnsafeRow):
                manifest.check_audio_url(bad)

    def test_urlsplit_value_error_becomes_unsafe_row(self) -> None:
        for bad in ("https://[gggg::1]/x.mp3", "https://[archive.org/x.mp3",
                    "https://archive.org\uff03@evil.com/x.mp3", "https://archive.org:abc/x.mp3"):
            with self.subTest(url=bad), self.assertRaises(manifest.UnsafeRow):
                manifest.check_audio_url(bad)

    def test_good_urls_still_pass(self) -> None:
        self.assertEqual(manifest.check_audio_url(self.GOOD), self.GOOD)
        for slug in ("wesley", "spurgeon", "edwards"):
            self.assertTrue(manifest.load(manifest.MANIFEST.with_name(f"{slug}.jsonl")))

    def test_backslash_host_is_refused(self) -> None:
        # urlsplit sees host "evil.com\\.archive.org"; a browser opens evil.com.
        for bad in ("https://evil.com\\.archive.org/a.mp3", "https://archive.org\\@evil.com/a.mp3",
                    "https://archive.org/download\\x/a.mp3"):
            with self.subTest(url=bad), self.assertRaises(manifest.UnsafeRow):
                manifest.check_audio_url(bad)
        self.assertEqual(query.play_url("https://evil.com\\.archive.org/a.mp3", 10.0), query.UNSAFE_URL)

    def test_play_url_hides_them(self) -> None:
        self.assertEqual(query.play_url(self.GOOD + "\n", 10.0), query.UNSAFE_URL)
        self.assertEqual(query.play_url("https://[gggg::1]/x.mp3", 10.0), query.UNSAFE_URL)
        self.assertTrue(query.play_url(self.GOOD, 10.0).startswith(self.GOOD + "#t="))



class ProvenanceTests(unittest.TestCase):
    """is_public_domain checks the provenance content, not just that the file exists."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "ingest" / "manifest").mkdir(parents=True)
        patch = mock.patch.object(libraries, "repo_root", lambda: self.root)
        patch.start()
        self.addCleanup(patch.stop)
        self.good = json.loads((ROOT / "ingest" / "manifest" / "spurgeon.provenance.json").read_text())

    def write(self, data: object, slug: str = "spurgeon") -> None:
        text = data if isinstance(data, str) else json.dumps(data)
        (self.root / "ingest" / "manifest" / f"{slug}.provenance.json").write_text(text)

    def assert_refused(self, data: object) -> None:
        self.write(data)
        self.assertFalse(libraries.is_public_domain("spurgeon"))
        with self.assertRaises(libraries.BadProvenance):
            libraries.load_provenance("spurgeon")

    def test_committed_provenance_passes(self) -> None:
        for slug in libraries.PUBLIC_DOMAIN:
            with self.subTest(slug=slug):
                self.write((ROOT / "ingest" / "manifest" / f"{slug}.provenance.json").read_text(), slug)
                self.assertEqual(libraries.load_provenance(slug)["slug"], slug)
                self.assertTrue(libraries.is_public_domain(slug))

    def test_empty_or_broken_file_is_refused(self) -> None:
        for data in ({}, [], "", "{not json", "null"):
            with self.subTest(data=data):
                self.assert_refused(data)

    def test_slug_must_match(self) -> None:
        self.assert_refused({**self.good, "slug": "edwards"})
        self.assert_refused({k: v for k, v in self.good.items() if k != "slug"})

    def test_licence_is_required(self) -> None:
        for key in ("licenseurl", "license_note"):
            with self.subTest(key=key):
                self.assert_refused({k: v for k, v in self.good.items() if k != key})
                self.assert_refused({**self.good, key: "  "})

    def test_text_edition_is_required(self) -> None:
        self.assert_refused({k: v for k, v in self.good.items() if k != "text_edition"})
        self.assert_refused({**self.good, "text_edition": {}})
        self.assert_refused({**self.good, "text_edition": {**self.good["text_edition"], "note": ""}})

    def test_audio_files_must_be_non_empty_and_valid(self) -> None:
        self.assert_refused({k: v for k, v in self.good.items() if k != "audio_files"})
        self.assert_refused({**self.good, "audio_files": []})
        bad_entries = {
            "file_name": ["../x.mp3", "a/b.mp3", "a\\b.mp3", "a b.mp3", "", None],
            "size": [0, -1, "1", None, True],
            "md5": ["x" * 32, None, "ABCDEF" * 6],
            "sha256": [None, "0" * 63, "g" * 64],
            "id": [None, "../a"],
        }
        for key, values in bad_entries.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    data = copy.deepcopy(self.good)
                    data["audio_files"][-1][key] = value
                    self.assert_refused(data)

    def test_archive_identifier_must_build_valid_urls(self) -> None:
        for ident in ("evil.com\\", "a/b", "", None, "x y"):
            with self.subTest(ident=ident):
                self.assert_refused({**self.good, "ia_identifier": ident, "ia_url": f"https://archive.org/details/{ident}"})
        self.assert_refused({**self.good, "ia_url": "https://evil.com/details/spurgeons_sermons_librivox"})

    def test_audio_url_matches_committed_manifest(self) -> None:
        prov = json.loads((ROOT / "ingest" / "manifest" / "edwards.provenance.json").read_text())
        rows = manifest.load(manifest.MANIFEST.with_name("edwards.jsonl"))
        files = {entry["id"]: entry for entry in prov["audio_files"]}
        for row in rows:
            self.assertEqual(row["audio_url"], libraries.audio_url(prov["ia_identifier"], files[row["id"]]["file_name"]))


class BuildShaTests(unittest.TestCase):
    """build_library.py checks each audio file's sha256 against provenance before indexing it."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audio = Path(self.tmp.name)
        self.rows = manifest.load(manifest.MANIFEST.with_name("spurgeon.jsonl"))

    def test_committed_manifest_matches_provenance(self) -> None:
        entries = build_library.provenance_files("spurgeon", self.rows)
        self.assertEqual(set(entries), {row["id"] for row in self.rows})

    def test_manifest_row_disagreeing_with_provenance_is_refused(self) -> None:
        for key, value in (("md5", "0" * 32), ("size", 1), ("file_name", "other_64kb.mp3"),
                           ("audio_url", "https://archive.org/download/other/x.mp3"), ("id", "spurgeon-999")):
            with self.subTest(key=key):
                rows = copy.deepcopy(self.rows)
                rows[0][key] = value
                with self.assertRaises(SystemExit):
                    build_library.provenance_files("spurgeon", rows)

    def entry(self, data: bytes) -> dict:
        import hashlib

        (self.audio / "a_64kb.mp3").write_bytes(data)
        return {"file_name": "a_64kb.mp3", "sha256": hashlib.sha256(b"the real audio").hexdigest()}

    def test_matching_sha256_passes(self) -> None:
        self.assertIsNone(build_library.audio_problem(self.entry(b"the real audio"), self.audio))

    def test_wrong_sha256_is_refused(self) -> None:
        # Same size, different bytes: a size check alone would pass it.
        problem = build_library.audio_problem(self.entry(b"the fake audio"), self.audio)
        self.assertIn("sha256", problem)

    def test_missing_audio_is_refused(self) -> None:
        entry = self.entry(b"x")
        (self.audio / entry["file_name"]).unlink()
        self.assertIn("no audio", build_library.audio_problem(entry, self.audio))


class Stop(Exception):
    """Raised by the patched build_app: main() got past every check."""


class ServerGateTests(unittest.TestCase):
    """app/server.py serves only the Wesley index and allow-listed public-domain libraries."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.wesley = self.dir / "wesley.sqlite"
        connection = connect(self.wesley)
        connection.execute(
            "INSERT INTO chunks (chunk_id, sermon_id, sermon_title, text) VALUES ('wesley-001-c0', 'wesley-001', 'S', 'grace')"
        )
        connection.commit()
        connection.close()
        patches = [
            mock.patch.object(server, "INDEX_PATH", self.wesley),
            mock.patch.object(server, "INDEX_DIR", self.dir),
            mock.patch.object(server, "build_app", side_effect=Stop),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def library_file(self, name: str, marker: str | None) -> Path:
        path = self.dir / f"{name}.sqlite"
        connection = open_library(path)
        if marker is not None:
            connection.execute("INSERT INTO meta (key, value) VALUES ('library', ?)", (marker,))
            connection.commit()
        connection.close()
        return path

    def served(self, *argv: str) -> bool:
        try:
            server.main(["--bm25-only", *argv])
        except Stop:
            return True
        raise AssertionError("main returned without serving")

    def refused(self, *argv: str) -> str:
        with self.assertRaises(SystemExit) as ctx:
            server.main(["--bm25-only", *argv])
        self.assertNotIn(ctx.exception.code, (0, None))
        return str(ctx.exception.code)

    def test_wesley_spurgeon_edwards_are_served(self) -> None:
        self.assertTrue(self.served())
        self.assertTrue(self.served("--index", str(self.wesley)))
        for slug in ("spurgeon", "edwards"):
            with self.subTest(slug=slug):
                path = self.library_file(slug, slug)
                self.assertTrue(self.served("--library", slug))
                self.assertTrue(self.served("--library", slug, "--index", str(path)))

    def test_church_and_unknown_libraries_are_refused(self) -> None:
        self.library_file("cc-speech", None)  # a YouTube import has no library marker
        self.library_file("talmage", "talmage")
        for slug in ("cc-speech", "talmage", "unknown-slug"):
            with self.subTest(slug=slug):
                self.assertIn("refused", self.refused("--library", slug))

    def test_index_with_non_allow_listed_library_file_is_refused(self) -> None:
        church = self.library_file("church-copy", None)
        talmage = self.library_file("old", "talmage")
        for path in (church, talmage):
            for library in ("wesley", "spurgeon"):
                with self.subTest(path=path.name, library=library):
                    self.assertIn("not a public-domain library", self.refused("--library", library, "--index", str(path)))

    def test_index_library_must_match_slug(self) -> None:
        spurgeon = self.library_file("spurgeon", "spurgeon")
        self.assertIn("--library spurgeon", self.refused("--library", "edwards", "--index", str(spurgeon)))
        self.assertIn("--library spurgeon", self.refused("--index", str(spurgeon)))
        self.assertIn("--library wesley", self.refused("--library", "spurgeon", "--index", str(self.wesley)))

    def test_unknown_files_are_refused(self) -> None:
        plain = self.dir / "plain.sqlite"
        raw = sqlite3.connect(plain)
        raw.execute("CREATE TABLE notes (x TEXT)")
        raw.commit()
        raw.close()
        empty = self.dir / "empty-index.sqlite"
        connect(empty).close()
        other = self.dir / "other.sqlite"
        connection = connect(other)
        connection.execute(
            "INSERT INTO chunks (chunk_id, sermon_id, sermon_title, text) VALUES ('x-c0', 'pastor-01', 'S', 'grace')"
        )
        connection.commit()
        connection.close()
        not_db = self.dir / "notes.txt"
        not_db.write_text("not a database " * 100)
        for path in (plain, empty, other):
            with self.subTest(path=path.name):
                self.assertIn("not the Wesley index", self.refused("--index", str(path)))
        self.assertIn("not a SQLite index", self.refused("--index", str(not_db)))
        self.assertIn("missing index", self.refused("--index", str(self.dir / "missing.sqlite")))
        self.assertFalse((self.dir / "missing.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
