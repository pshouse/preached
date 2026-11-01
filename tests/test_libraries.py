"""W3-LIB fix-up: which index query.py opens (read-only, never synced), and
which slugs may be ingested, indexed or served as public-domain libraries."""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import contextlib
import copy
import io
import json
import os
import shutil
import sqlite3
import stat
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


def setUpModule() -> None:
    # The classics gate refuses group/world-writable files and directories.
    global _umask
    _umask = os.umask(0o022)


def tearDownModule() -> None:
    os.umask(_umask)


def private_index_dir(tmp: str) -> Path:
    """<tmp>/index, mode 0755 under a 0700 temp dir, both owned by this uid."""
    path = Path(tmp) / "index"
    path.mkdir(mode=0o755)
    path.chmod(0o755)
    return path


def restore_sidecars(index: Path) -> None:
    """SQLite gives a -wal/-shm it creates the database file's mode at that moment;
    after a test chmods the file back, give its sidecars the same mode again."""
    for suffix in libraries.SIDECAR_SUFFIXES:
        sidecar = Path(f"{index}{suffix}")
        if sidecar.exists():
            sidecar.chmod(stat.S_IMODE(index.stat().st_mode))


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
        # INDEX_DIR one level down: classic_index_problem checks its parent too,
        # and a shared /tmp (root, mode 1777) would not pass.
        self.dir = private_index_dir(self.tmp.name)
        self.wesley = self.dir / "wesley.sqlite"
        patches = [
            mock.patch.object(query, "INDEX_PATH", self.wesley),
            mock.patch.object(query, "INDEX_DIR", self.dir),
            # Main (#10) made query.py read-only with no chunk sync; nothing may sync.
            mock.patch("preached.store.sync_chunks"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        import preached.store

        self.synced = preached.store.sync_chunks

    def library_file(self, name: str) -> Path:
        path = self.dir / name
        open_library(path).close()
        return path

    def test_index_and_library_are_mutually_exclusive(self) -> None:
        self.library_file("spurgeon.sqlite")
        code, err = run_main(["q", "--mode", "bm25", "--index", str(self.wesley), "--library", "spurgeon"])
        self.assertEqual(code, 2)
        self.assertIn("not allowed with argument", err)

    def test_library_style_index_is_refused_unchanged(self) -> None:
        # The CTO repro: a classics file passed as --index became Wesley chunks.
        path = self.library_file("spurgeon.sqlite")
        before = path.read_bytes()
        code, _ = run_main(["q", "--mode", "bm25", "--index", str(path)])
        self.assertIn("is a library index", str(code))
        self.assertIn("--library spurgeon", str(code))
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

    def test_wesley_index_is_never_synced(self) -> None:
        connect(self.wesley).close()
        before = self.wesley.read_bytes()
        query.open_index(None, None).close()
        query.open_index(self.wesley, None).close()
        self.synced.assert_not_called()
        self.assertEqual(self.wesley.read_bytes(), before)

    def test_wesley_search_connection_is_read_only(self) -> None:
        connect(self.wesley).close()
        before = self.wesley.read_bytes()
        for index in (None, self.wesley):
            connection = query.open_index(index, None)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("INSERT INTO meta (key, value) VALUES ('x', 'y')")
            connection.close()
        self.assertEqual(self.wesley.read_bytes(), before)

    def test_other_index_path_is_opened(self) -> None:
        other = self.dir / "wesley-onnx-int8.sqlite"
        connect(other).close()
        self.assertFalse(query.is_library_file(other))
        query.open_index(other, None).close()

    def test_library_flag_is_allow_listed_by_slug(self) -> None:
        self.library_file("edwards.sqlite")
        query.open_index(None, "edwards").close()
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


class WesleyNeverSyncedTests(unittest.TestCase):
    """query.py never syncs or writes the Wesley index (main #10 removed the sync:
    a text-only chunks.jsonl would null every timing and audio field)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.wesley = self.dir / "wesley.sqlite"
        patches = [
            mock.patch.object(query, "INDEX_PATH", self.wesley),
            mock.patch.object(query, "INDEX_DIR", self.dir),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_missing_index_is_refused_not_created(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            query.open_index(None, None)
        self.assertIn("missing index", str(ctx.exception.code))
        self.assertFalse(self.wesley.exists())

    def test_existing_index_is_opened_read_only_and_unchanged(self) -> None:
        connection = connect(self.wesley)
        connection.execute(
            "INSERT INTO chunks (chunk_id, sermon_id, sermon_title, text) VALUES ('wesley-001-c0', 'wesley-001', 'S', 'grace')"
        )
        connection.commit()
        connection.close()
        before = self.wesley.read_bytes()
        connection = query.open_index(None, None)
        self.assertEqual([row[0] for row in connection.execute("SELECT text FROM chunks")], ["grace"])
        with self.assertRaises(sqlite3.OperationalError):
            connection.execute("DELETE FROM chunks")
        connection.close()
        self.assertEqual(self.wesley.read_bytes(), before)


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

    def test_non_ascii_is_refused(self) -> None:
        # U+2028/U+2029 split a log line; U+200B/U+FEFF are invisible; U+00A0 looks like a space.
        for char in ("\u2028", "\u2029", "\u200b", "\ufeff", "\u00a0", "\u00e9", "\uff0e"):
            for bad in (self.GOOD + char, self.GOOD.replace("/download/", f"/download/{char}"),
                        f"https://archive{char}.org/a.mp3", f"https://evil.com{char}archive.org/a.mp3"):
                with self.subTest(url=bad), self.assertRaises(manifest.UnsafeRow):
                    manifest.check_audio_url(bad)
        self.assertEqual(query.play_url(self.GOOD + "\u2028", 10.0), query.UNSAFE_URL)
        self.assertEqual(query.play_url(self.GOOD + "\u200b", 10.0), query.UNSAFE_URL)
        self.assertFalse(libraries._archive_url(self.GOOD + "\u200b"))
        self.assertTrue(libraries._archive_url(self.GOOD))

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
        manifest_copy = self.root / "ingest" / "manifest" / f"{slug}.jsonl"
        if not manifest_copy.exists():
            manifest_copy.write_text((ROOT / "ingest" / "manifest" / f"{slug}.jsonl").read_text())

    def write_manifest(self, rows: list[dict], slug: str = "spurgeon") -> None:
        text = "".join(json.dumps(row) + "\n" for row in rows)
        (self.root / "ingest" / "manifest" / f"{slug}.jsonl").write_text(text)

    def test_manifest_must_match_provenance_at_runtime(self) -> None:
        # is_public_domain (used by query.py and app/server.py, not just the build)
        # checks the committed manifest against provenance.
        rows = [json.loads(line) for line in (ROOT / "ingest" / "manifest" / "spurgeon.jsonl").read_text().splitlines()]
        self.write(self.good)
        self.assertTrue(libraries.is_public_domain("spurgeon"))
        other = "https://archive.org/download/spurgeons_sermons_librivox/other.mp3"
        bad = {
            "size": [{**rows[0], "size": rows[0]["size"] + 1}, *rows[1:]],
            "md5": [{**rows[0], "md5": "0" * 32}, *rows[1:]],
            "file_name": [{**rows[0], "file_name": "other.mp3"}, *rows[1:]],
            "audio_url": [{**rows[0], "audio_url": other}, *rows[1:]],
            "missing row": rows[1:],
            "extra row": [*rows, {**rows[0], "id": "spurgeon-999"}],
            "duplicate row": [*rows, rows[0]],
            "not an object": [*rows[1:], []],
        }
        for name, manifest_rows in bad.items():
            with self.subTest(case=name):
                self.write_manifest(manifest_rows)
                self.assertFalse(libraries.is_public_domain("spurgeon"))
                with self.assertRaises(libraries.BadProvenance):
                    libraries.check_manifest("spurgeon", libraries.load_provenance("spurgeon"))
        (self.root / "ingest" / "manifest" / "spurgeon.jsonl").unlink()
        self.assertFalse(libraries.is_public_domain("spurgeon"))

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
        # INDEX_DIR one level down: classic_index_problem checks its parent too,
        # and a shared /tmp (root, mode 1777) would not pass.
        self.dir = private_index_dir(self.tmp.name)
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
            with self.subTest(path=path.name, library="wesley"):
                self.assertIn("not a public-domain library", self.refused("--library", "wesley", "--index", str(path)))
            with self.subTest(path=path.name, library="spurgeon"):
                self.assertIn("served only from", self.refused("--library", "spurgeon", "--index", str(path)))

    def test_index_library_must_match_slug(self) -> None:
        spurgeon = self.library_file("spurgeon", "spurgeon")
        self.library_file("edwards", "spurgeon")  # canonical edwards path, wrong marker
        self.assertIn("served only from", self.refused("--library", "edwards", "--index", str(spurgeon)))
        self.assertIn("not marked as the 'edwards' library", self.refused("--library", "edwards"))
        self.assertIn("--library spurgeon", self.refused("--index", str(spurgeon)))
        self.assertIn("served only from", self.refused("--library", "spurgeon", "--index", str(self.wesley)))

    def test_forged_classic_marker_elsewhere_is_refused(self) -> None:
        # CTO round-3 repro: a church import given a spurgeon marker, served with
        # --library spurgeon --index <other>, was served ungated.
        self.library_file("spurgeon", "spurgeon")
        elsewhere = self.dir / "elsewhere"
        elsewhere.mkdir()
        forged = elsewhere / "spurgeon.sqlite"  # same file name, other directory
        connection = open_library(forged)
        connection.execute("INSERT INTO meta (key, value) VALUES ('library', 'spurgeon')")
        connection.commit()
        connection.close()
        other = self.library_file("church-forged", "spurgeon")
        for path in (forged, other):
            with self.subTest(path=str(path)):
                self.assertIn("served only from", self.refused("--library", "spurgeon", "--index", str(path)))
        # The canonical file is still served, by slug or by an equivalent path.
        self.assertTrue(self.served("--library", "spurgeon"))
        self.assertTrue(self.served("--library", "spurgeon", "--index", str(self.dir / "." / "spurgeon.sqlite")))

    def test_symlinks_to_or_at_the_canonical_path_are_refused(self) -> None:
        canonical = self.library_file("spurgeon", "spurgeon")
        link = self.dir / "link.sqlite"
        link.symlink_to(canonical)
        self.assertIn("symlink", self.refused("--library", "spurgeon", "--index", str(link)))
        # The canonical path itself a symlink to a forged file elsewhere.
        canonical.unlink()
        forged = self.dir / "forged" / "x.sqlite"
        forged.parent.mkdir()
        connection = open_library(forged)
        connection.execute("INSERT INTO meta (key, value) VALUES ('library', 'spurgeon')")
        connection.commit()
        connection.close()
        canonical.symlink_to(forged)
        self.assertIn("symlink", self.refused("--library", "spurgeon"))
        self.assertIn("symlink", self.refused("--library", "spurgeon", "--index", str(canonical)))

    def test_classic_index_problem_is_the_reusable_gate(self) -> None:
        canonical = self.library_file("edwards", "edwards")
        self.assertIsNone(libraries.classic_index_problem("edwards", canonical, self.dir))
        with mock.patch.object(libraries.paths, "INDEX_DIR", self.dir):
            self.assertIsNone(libraries.classic_index_problem("edwards", canonical))
        self.assertIn("served only from", libraries.classic_index_problem("edwards", self.wesley, self.dir))
        self.assertIn("not a public-domain library", libraries.classic_index_problem("wesley", self.wesley, self.dir))
        self.assertIn("not a public-domain library", libraries.classic_index_problem("cc-speech", canonical, self.dir))
        self.assertIn("missing index", libraries.classic_index_problem("spurgeon", self.dir / "spurgeon.sqlite", self.dir))

    def church_as_wesley(self, name: str) -> Path:
        """CTO round-3 repro: a church import with ids renamed wesley-*, the
        videos table dropped, video_id (and the other import columns) kept,
        and no library marker."""
        path = self.dir / f"{name}.sqlite"
        connection = open_library(path)
        connection.execute(
            "INSERT INTO chunks (chunk_id, sermon_id, sermon_title, text, video_id) "
            "VALUES ('wesley-900-c0', 'wesley-900', 'S', 'a member named in a story', 'abc123')"
        )
        connection.execute("DROP TABLE videos")
        connection.execute("DELETE FROM meta WHERE key = 'library'")
        connection.commit()
        connection.close()
        return path

    def test_church_import_renamed_wesley_is_refused(self) -> None:
        path = self.church_as_wesley("renamed")
        message = self.refused("--index", str(path))
        self.assertIn("church-import columns", message)
        self.assertIn("video_id", message)

    def test_any_church_or_review_column_is_refused_as_wesley(self) -> None:
        for column in ("video_id", "title", "published", "flag_end_s", "review_sha256", "approved_sha256",
                       "approval_status", "reviewed_by"):
            with self.subTest(column=column):
                path = self.dir / f"col-{column}.sqlite"
                connection = connect(path)
                connection.execute(f"ALTER TABLE chunks ADD COLUMN {column} TEXT")
                connection.execute(
                    "INSERT INTO chunks (chunk_id, sermon_id, sermon_title, text) "
                    "VALUES ('wesley-001-c0', 'wesley-001', 'S', 'grace')"
                )
                connection.commit()
                connection.close()
                self.assertIn(column, self.refused("--index", str(path)))
        # The Wesley schema itself (store.connect) is still served.
        self.assertTrue(self.served("--index", str(self.wesley)))

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


class ClassicIndexBase(unittest.TestCase):
    """A private INDEX_DIR holding a built edwards.sqlite, and ways to check it."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = private_index_dir(self.tmp.name)
        self.canonical = self.dir / "edwards.sqlite"
        connection = open_library(self.canonical)
        connection.execute("INSERT INTO meta (key, value) VALUES ('library', 'edwards')")
        connection.commit()
        connection.close()

    def problem(self, index_dir: Path | None = None) -> str | None:
        index_dir = self.dir if index_dir is None else index_dir
        return libraries.classic_index_problem("edwards", index_dir / "edwards.sqlite", index_dir)

    def refused_by_server(self, index_dir: Path) -> str:
        with mock.patch.object(server, "INDEX_DIR", index_dir), \
                mock.patch.object(server, "build_app", side_effect=Stop), \
                self.assertRaises(SystemExit) as ctx:
            server.main(["--bm25-only", "--library", "edwards"])
        return str(ctx.exception.code)


class ClassicOwnerModeTests(ClassicIndexBase):
    """classic_index_problem: owner, mode, symlink and link-count checks (CTO round 4)."""

    def test_private_layout_passes(self) -> None:
        self.assertIsNone(self.problem())
        with mock.patch.object(server, "INDEX_DIR", self.dir), mock.patch.object(server, "build_app", side_effect=Stop):
            with self.assertRaises(Stop):
                server.main(["--bm25-only", "--library", "edwards"])

    def test_world_or_group_writable_is_refused(self) -> None:
        for target, label in ((self.dir.parent, "parent"), (self.dir, "index directory"), (self.canonical, "index")):
            original = target.stat().st_mode & 0o777
            for bits in (0o002, 0o020):
                with self.subTest(target=label, bits=oct(bits)):
                    target.chmod(original | bits)
                    try:
                        message = self.problem()
                        self.assertIn("writable", message or "")
                        self.assertIn(str(target), message)
                        self.assertIn("writable", self.refused_by_server(self.dir))
                        with mock.patch.object(query, "INDEX_DIR", self.dir):
                            code, _ = run_main(["q", "--mode", "bm25", "--library", "edwards"])
                        self.assertIn("writable", str(code))
                    finally:
                        target.chmod(original)
                        restore_sidecars(self.canonical)
        self.assertIsNone(self.problem())

    def test_symlinked_index_dir_is_refused(self) -> None:
        link = Path(self.tmp.name) / "linked-index"
        link.symlink_to(self.dir, target_is_directory=True)
        self.assertIn("symlink", self.problem(link))
        self.assertIn("symlink", self.refused_by_server(link))

    def test_hardlinked_file_is_refused(self) -> None:
        other = Path(self.tmp.name) / "elsewhere.sqlite"
        os.link(self.canonical, other)
        self.assertIn("hard links", self.problem())
        self.assertIn("hard links", self.refused_by_server(self.dir))
        other.unlink()
        self.assertIsNone(self.problem())

    def test_wrong_owner_is_refused(self) -> None:
        real_stat, real_lstat = os.stat, os.lstat

        def foreign(real, target):
            def fake(path, *args, **kwargs):
                st = real(path, *args, **kwargs)
                if os.path.abspath(path) != os.path.abspath(target):
                    return st
                fields = list(st[:10])
                fields[4] = st.st_uid + 1  # st_uid
                return os.stat_result(fields)
            return fake

        for target in (self.dir.parent, self.dir, self.canonical):
            with self.subTest(target=target.name), \
                    mock.patch.object(libraries.os, "stat", foreign(real_stat, target)), \
                    mock.patch.object(libraries.os, "lstat", foreign(real_lstat, target)):
                message = self.problem()
                self.assertIn("owned by uid", message or "")
                self.assertIn(str(target), message)
        with mock.patch.object(libraries.os, "geteuid", return_value=os.geteuid() + 1):
            self.assertIn("owned by uid", self.problem())
            self.assertIn("owned by uid", self.refused_by_server(self.dir))


def fake_owner(real, target: Path, uid: int):
    """``real`` (os.stat / os.lstat) reporting ``uid`` as the owner of ``target`` only."""
    def fake(path, *args, **kwargs):
        st = real(path, *args, **kwargs)
        if os.path.abspath(path) != os.path.abspath(target):
            return st
        fields = list(st[:10])
        fields[4] = uid  # st_uid
        return os.stat_result(fields)
    return fake


class ClassicRootOwnerTests(ClassicIndexBase):
    """CTO ruling S2 (#14 final gate): root may own the index, its directory and
    their parent, as well as the server's euid; still no group or world write."""

    def test_root_owned_layout_passes(self) -> None:
        real_stat, real_lstat = os.stat, os.lstat
        for target in (self.dir.parent, self.dir, self.canonical):
            with self.subTest(target=target.name), \
                    mock.patch.object(libraries.os, "stat", fake_owner(real_stat, target, 0)), \
                    mock.patch.object(libraries.os, "lstat", fake_owner(real_lstat, target, 0)):
                self.assertIsNone(self.problem())
                with mock.patch.object(server, "INDEX_DIR", self.dir), \
                        mock.patch.object(server, "build_app", side_effect=Stop), self.assertRaises(Stop):
                    server.main(["--bm25-only", "--library", "edwards"])

    def test_root_owned_but_writable_is_refused(self) -> None:
        real_stat, real_lstat = os.stat, os.lstat
        for target in (self.dir, self.canonical):
            original = stat.S_IMODE(target.stat().st_mode)
            with self.subTest(target=target.name), \
                    mock.patch.object(libraries.os, "stat", fake_owner(real_stat, target, 0)), \
                    mock.patch.object(libraries.os, "lstat", fake_owner(real_lstat, target, 0)):
                target.chmod(original | 0o002)
                try:
                    self.assertIn("writable", self.problem() or "")
                finally:
                    target.chmod(original)

    def test_other_users_are_still_refused(self) -> None:
        real_lstat = os.lstat
        other = os.geteuid() + 1
        with mock.patch.object(libraries.os, "lstat", fake_owner(real_lstat, self.canonical, other)):
            self.assertIn(f"owned by uid {other}", self.problem() or "")


class ClassicSidecarTests(ClassicIndexBase):
    """CTO ruling S1 (#14 final gate): a -wal, -shm or -journal next to a classic
    index gets the owner, mode, symlink and link-count checks of the index."""

    TEXT = "church member secret story"
    # Non-empty: SQLite resets an empty sidecar to the database file's mode when
    # it opens it (and an empty one holds nothing to replay).
    JUNK = b"\0" * 32

    def plant_wal(self) -> Path:
        """CTO repro (/workspace/pr14r5/wal.py): a WAL written elsewhere, copied next
        to the real classic file, is replayed into what the read-only reader sees."""
        scratch = Path(self.tmp.name) / "scratch.sqlite"
        shutil.copy(self.canonical, scratch)
        writer = sqlite3.connect(scratch)
        writer.execute("PRAGMA wal_autocheckpoint = 0")
        writer.execute(
            "INSERT INTO chunks (chunk_id, sermon_id, sermon_title, text) VALUES ('edwards-x-c0', 'edwards-x', 'S', ?)",
            (self.TEXT,),
        )
        writer.commit()
        wal = Path(f"{self.canonical}-wal")
        shutil.copy(f"{scratch}-wal", wal)
        writer.close()
        return wal

    def served_texts(self) -> list[str]:
        connection = server.open_readonly(self.canonical)
        try:
            return [row[0] for row in connection.execute("SELECT text FROM chunks")]
        finally:
            connection.close()

    def test_world_writable_wal_is_refused(self) -> None:
        wal = self.plant_wal()
        wal.chmod(0o666)
        # The repro is real: without the sidecar check this file serves the planted text.
        with mock.patch.object(libraries, "SIDECAR_SUFFIXES", ()):
            self.assertIsNone(self.problem())
        self.assertIn(self.TEXT, self.served_texts())
        message = self.problem()
        self.assertIn("writable", message or "")
        self.assertIn(str(wal), message)
        self.assertIn("writable", self.refused_by_server(self.dir))
        with mock.patch.object(query, "INDEX_DIR", self.dir):
            code, _ = run_main(["q", "--mode", "bm25", "--library", "edwards"])
        self.assertIn("writable", str(code))

    def test_every_sidecar_is_checked(self) -> None:
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(f"{self.canonical}{suffix}")
            for label, make in (
                ("group-writable", lambda p: (p.write_bytes(self.JUNK), p.chmod(0o664))),
                ("symlink", lambda p: p.symlink_to(Path(self.tmp.name) / "elsewhere")),
                ("hardlink", lambda p: (p.write_bytes(self.JUNK), p.chmod(0o644),
                                        os.link(p, Path(self.tmp.name) / "linked"))),
                ("directory", lambda p: p.mkdir(mode=0o755)),
            ):
                with self.subTest(suffix=suffix, case=label):
                    make(sidecar)
                    try:
                        self.assertIsNotNone(self.problem())
                        self.assertIn(str(sidecar), self.problem())
                        self.refused_by_server(self.dir)
                    finally:
                        if sidecar.is_dir() and not sidecar.is_symlink():
                            sidecar.rmdir()
                        else:
                            sidecar.unlink()
                        (Path(self.tmp.name) / "linked").unlink(missing_ok=True)
            with self.subTest(suffix=suffix, case="other owner"):
                sidecar.write_bytes(b"")
                sidecar.chmod(0o644)
                other = os.geteuid() + 1
                try:
                    with mock.patch.object(libraries.os, "lstat", fake_owner(os.lstat, sidecar, other)):
                        self.assertIn(f"owned by uid {other}", self.problem() or "")
                    with mock.patch.object(libraries.os, "lstat", fake_owner(os.lstat, sidecar, 0)):
                        self.assertIsNone(self.problem())
                finally:
                    sidecar.unlink()
        self.assertIsNone(self.problem())

    def test_private_sidecars_pass(self) -> None:
        wal = self.plant_wal()
        wal.chmod(0o644)
        self.assertIsNone(self.problem())


class WesleyAllowListTests(unittest.TestCase):
    """The Wesley schema is an allow-list, compared case-insensitively (CTO round 4)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = private_index_dir(self.tmp.name)

    def wesley(self, name: str, *sql: str) -> Path:
        path = self.dir / f"{name}.sqlite"
        connection = connect(path)
        connection.execute(
            "INSERT INTO chunks (chunk_id, sermon_id, sermon_title, text) VALUES ('wesley-001-c0', 'wesley-001', 'S', 'grace')"
        )
        for statement in sql:
            connection.execute(statement)
        connection.commit()
        connection.close()
        return path

    def check(self, path: Path) -> None:
        connection = server.open_readonly(path)
        try:
            server.check_servable(connection, "wesley", path)
        finally:
            connection.close()

    def test_store_schema_is_exactly_the_allow_list(self) -> None:
        path = self.wesley("plain")
        connection = server.open_readonly(path)
        try:
            self.assertEqual(server.foreign_schema(connection), [])
            names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            connection.close()
        self.assertEqual(names, set(server.WESLEY_SCHEMA))
        self.check(path)

    def test_mixed_case_church_columns_are_refused(self) -> None:
        for column in ("Video_ID", "VIDEO_ID", "Title", "Approved_SHA256", "flag_END_s"):
            with self.subTest(column=column):
                path = self.wesley(f"col-{column}", f"ALTER TABLE chunks ADD COLUMN {column} TEXT")
                with self.assertRaises(SystemExit) as ctx:
                    self.check(path)
                self.assertIn(column, str(ctx.exception.code))

    def test_side_tables_and_views_are_refused(self) -> None:
        cases = {
            "side": "CREATE TABLE side (Video_ID TEXT)",
            "videos-upper": "CREATE TABLE VIDEOS (video_id TEXT)",
            "meta-col": "ALTER TABLE meta ADD COLUMN video_id TEXT",
            "emb-col": "ALTER TABLE embeddings ADD COLUMN reviewed_by TEXT",
            "view": "CREATE VIEW v AS SELECT chunk_id AS video_id FROM chunks",
        }
        for name, sql in cases.items():
            with self.subTest(case=name):
                path = self.wesley(name, sql)
                with self.assertRaises(SystemExit):
                    self.check(path)

    def test_upper_case_sermon_ids_are_not_wesley(self) -> None:
        path = self.wesley("upper", "UPDATE chunks SET sermon_id = 'WESLEY-001'")
        with self.assertRaises(SystemExit) as ctx:
            self.check(path)
        self.assertIn("not the Wesley index", str(ctx.exception.code))


class ServeIdentityAndReloadTests(unittest.TestCase):
    """The opened file is the checked file, and every reload re-runs the gate (CTO round 4)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = private_index_dir(self.tmp.name)
        self.path = self.dir / "wesley.sqlite"
        self.write(self.path, "grace")
        patches = [
            mock.patch.object(server, "INDEX_PATH", self.path),
            mock.patch.object(server, "INDEX_DIR", self.dir),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def write(self, path: Path, text: str) -> None:
        connection = connect(path)
        connection.execute(
            "INSERT INTO chunks (chunk_id, sermon_id, sermon_title, text) VALUES ('wesley-001-c0', 'wesley-001', 'S', ?)",
            (text,),
        )
        connection.execute("INSERT INTO meta (key, value) VALUES ('chunks_sha256', ?)", (text,))
        connection.commit()
        connection.close()

    def start(self, *argv: str) -> dict:
        """Run main up to build_app; return its keyword arguments."""
        captured = {}

        def fake_build_app(connection, **kwargs):
            captured.update(kwargs, connection=connection)
            raise Stop

        with mock.patch.object(server, "build_app", side_effect=fake_build_app), self.assertRaises(Stop):
            server.main(["--bm25-only", *argv])
        self.addCleanup(captured["connection"].close)
        return captured

    def test_inode_change_across_the_open_is_refused(self) -> None:
        identities = iter([(1, 1), (1, 2)])
        with mock.patch.object(server, "file_identity", side_effect=lambda _path: next(identities)), \
                mock.patch.object(server, "build_app", side_effect=Stop), \
                self.assertRaises(SystemExit) as ctx:
            server.main(["--bm25-only"])
        self.assertIn("was replaced", str(ctx.exception.code))

    def test_replaced_file_is_refused_on_reload(self) -> None:
        servable = self.start()["servable"]
        connection = server.open_readonly(self.path)
        try:
            servable(connection)  # same file: passes
            replacement = self.dir / "new.sqlite"
            self.write(replacement, "faith")
            os.replace(replacement, self.path)
            with self.assertRaises(SystemExit) as ctx:
                servable(connection)
            self.assertIn("was replaced", str(ctx.exception.code))
        finally:
            connection.close()

    def test_reload_runs_check_servable_before_any_searcher(self) -> None:
        captured = self.start()
        connection = captured["connection"]
        app = server.App(
            connection=connection,
            searcher=server.Searcher(connection),
            encode=None,
            fallback_note=None,
            model_name=None,
            hosts={"127.0.0.1"},
            static_dir=server.STATIC_DIR,
            servable=captured["servable"],
        )
        self.assertEqual(len(app.search("grace", 5, "bm25")["results"]), 1)
        writer = connect(self.path)
        try:
            # In-place edit: a church column (any case) and a new chunk hash.
            writer.execute("ALTER TABLE chunks ADD COLUMN Video_ID TEXT")
            writer.execute("UPDATE meta SET value = 'church' WHERE key = 'chunks_sha256'")
            writer.commit()
            built = []
            real_searcher = server.Searcher
            with mock.patch.object(server, "Searcher", side_effect=lambda *a, **k: built.append(1) or real_searcher(*a, **k)):
                for call in (lambda: app.search("grace", 5, "bm25"), app.health, lambda: app.sermon("wesley-001")):
                    with self.assertRaises(server.BadRequest) as ctx:
                        call()
                    self.assertEqual(ctx.exception.status, 503)
            self.assertEqual(built, [])
            self.assertIsNone(app.searcher)
            self.assertIn("Video_ID", app.refused)
            # Put right in place: the gate passes again and a searcher is rebuilt.
            writer.execute("ALTER TABLE chunks DROP COLUMN Video_ID")
            writer.commit()
            self.assertEqual(len(app.search("grace", 5, "bm25")["results"]), 1)
            self.assertIsNone(app.refused)
        finally:
            writer.close()


    def test_healthz_reports_a_refusal_the_stamp_did_not_notice(self) -> None:
        """A swapped -wal can leave the index stamp unchanged: /healthz still says 503."""
        captured = self.start()
        connection = captured["connection"]
        state = {"ok": True}

        def servable(conn) -> None:
            if not state["ok"]:
                raise SystemExit("error: a -wal next to the index was swapped; refused")

        app = server.App(
            connection=connection, searcher=server.Searcher(connection), encode=None, fallback_note=None,
            model_name=None, hosts={"127.0.0.1"}, static_dir=server.STATIC_DIR, servable=servable,
        )
        self.assertTrue(app.health()["ok"])
        state["ok"] = False  # nothing in the file changed, so the stamp is the same
        with self.assertRaises(server.BadRequest) as ctx:
            app.health()
        self.assertEqual(ctx.exception.status, 503)
        with self.assertRaises(server.BadRequest) as ctx:
            app.search("grace", 5, "bm25")
        self.assertEqual(ctx.exception.status, 503)
        state["ok"] = True
        self.assertEqual(app.health()["chunks"], 1)
        self.assertEqual(len(app.search("grace", 5, "bm25")["results"]), 1)


if __name__ == "__main__":
    unittest.main()
