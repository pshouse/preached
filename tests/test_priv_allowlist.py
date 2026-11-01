"""W3-PRIV-WIRE x #14: the shared public-domain allow-list, fail-closed church
paths, the fixed ``none`` audio policy and /api/sermon links.

Every name below is invented. The classics fixture is built by the real
``search/build_library.py`` from a synthetic transcript of a real manifest row.
"""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import contextlib
import hashlib
import io
import json
import os
import sqlite3
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for sub in ("ingest", "search", "align"):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

import asr_chunks  # noqa: E402
import build_library  # noqa: E402
import query  # noqa: E402
import run as ingest_run  # noqa: E402
from app.server import STATIC_DIR, App  # noqa: E402
from preached import paths as preached_paths  # noqa: E402
from preached.libraries import PUBLIC_DOMAIN  # noqa: E402
from preached.search import Searcher, touches_flagged  # noqa: E402
from preached.store import open_readonly, public_domain_file  # noqa: E402
from preached.youtube.cli import main as youtube_main  # noqa: E402
from preached.youtube.library import open_library  # noqa: E402
from preached.youtube.listing import policy_watch_url, watch_url, youtube_watch_url  # noqa: E402
from test_privacy_wire import CHANNEL, FILLER, ID_A, ID_B, Base, embedder, words_for  # noqa: E402
from coverage_stub import stub_audio

SPURGEON_ROW = "spurgeon-191"
CLASSIC_WORDS = "the builder of his church lays every living stone upon the chief corner stone " * 30


def clean_env() -> dict[str, str]:
    """os.environ without any privacy or flagged-audio setting."""
    return {k: v for k, v in os.environ.items() if not k.startswith("PREACHED_PRIVACY") and k != "PREACHED_FLAGGED_AUDIO"}


def make_app(connection, library: str) -> App:
    return App(connection=connection, searcher=Searcher(connection), encode=None, fallback_note=None,
               model_name=None, hosts={"127.0.0.1"}, static_dir=STATIC_DIR, library=library)


class ClassicsBase(unittest.TestCase):
    """A real classics build at the canonical (patched) INDEX_DIR/spurgeon.sqlite."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        patcher = patch.dict(os.environ, clean_env(), clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.index_dir = self.root / "index"
        self.index_dir.mkdir(mode=0o755)
        # The exemption binds to the canonical INDEX_DIR/<slug>.sqlite (store.classic_file_problem).
        paths_patch = patch.object(preached_paths, "INDEX_DIR", self.index_dir)
        paths_patch.start()
        self.addCleanup(paths_patch.stop)
        self.index = self.build("spurgeon")

    def build(self, slug: str) -> Path:
        """Run search/build_library.py on one synthetic transcript (no Granite)."""
        tdir = self.root / "transcripts" / slug
        tdir.mkdir(parents=True, exist_ok=True)
        words = [[w.start, w.end, w.text] for w in words_for(CLASSIC_WORDS)]
        (tdir / f"{SPURGEON_ROW}.json").write_text(json.dumps({
            "searchable_start": 0.0, "searchable_end": 1e9, "segments": [{"words": words}],
        }))
        # #14 checks each sermon's audio sha256 against provenance before indexing it.
        # Synthetic audio, with the committed provenance entry's sha256 swapped for its hash.
        audio = b"synthetic audio for " + SPURGEON_ROW.encode()
        real_files = build_library.provenance_files

        def provenance_files(lib: str, rows: list[dict]) -> dict[str, dict]:
            entries = real_files(lib, rows)
            entry = entries[SPURGEON_ROW] = dict(entries[SPURGEON_ROW])
            entry["sha256"] = hashlib.sha256(audio).hexdigest()
            adir = self.root / "audio" / lib
            adir.mkdir(parents=True, exist_ok=True)
            (adir / entry["file_name"]).write_bytes(audio)
            return entries

        with patch.object(build_library, "CACHE_ROOT", self.root), \
                patch.object(build_library, "INDEX_DIR", self.index_dir), \
                patch.object(build_library, "provenance_files", provenance_files), \
                patch.object(build_library, "_embed_on_cpu", embedder), \
                patch.object(sys, "argv", ["build_library.py", slug]), redirect_stderr(StringIO()):
            self.assertEqual(build_library.main(), 0)
        return self.index_dir / f"{slug}.sqlite"

    def connection(self, path: Path | None = None):
        connection = open_readonly(path or self.index, check_same_thread=False)
        self.addCleanup(connection.close)
        return connection


class ClassicsVisibleTests(ClassicsBase):
    """The classics are exempt from the gate by slug and canonical file; nothing else is."""

    def test_classics_stay_visible_in_the_server(self) -> None:
        connection = self.connection()
        total = connection.execute("SELECT count(*) FROM chunks").fetchone()[0]
        self.assertGreater(total, 1)
        self.assertTrue(public_domain_file(connection, "spurgeon"))
        app = make_app(connection, "spurgeon")
        results = app.search("corner stone", 5, "bm25")["results"]
        self.assertTrue(results)
        self.assertTrue(all(r["sermon_id"] == SPURGEON_ROW for r in results))
        self.assertTrue(results[0]["audio_url"].startswith("https://archive.org/download/spurgeons_sermons_librivox/"))
        self.assertIsNotNone(results[0]["start_s"])
        health = app.health()
        self.assertEqual(health["chunks"], total)
        self.assertNotIn("pending_review", health)
        sermon = app.sermon(SPURGEON_ROW)
        self.assertIsNotNone(sermon)
        self.assertTrue(sermon["audio_url"].startswith("https://archive.org/download/"))

    def test_without_the_slug_the_gate_hides_the_classics(self) -> None:
        """What the exemption fixes: the classics file has the gate columns and no approvals."""
        connection = self.connection()
        self.assertEqual(Searcher(connection).bm25("corner stone", 5), [])
        self.assertEqual(Searcher(connection, gated=True, library="church").bm25("corner stone", 5), [])
        self.assertTrue(Searcher(connection, gated=True, library="spurgeon").bm25("corner stone", 5))

    def test_the_file_must_be_that_librarys_own_build(self) -> None:
        connection = self.connection()
        # Served under another slug, allow-listed or not: gated, so hidden.
        for slug in ("edwards", "church", "talmage", "wesley-copy"):
            with self.subTest(slug=slug):
                self.assertFalse(public_domain_file(connection, slug))
                self.assertEqual(make_app(connection, slug).search("corner stone", 5, "bm25")["results"], [])
        # Church chunks written into a classics file (a review hash or a flag): the whole file is gated again.
        clean_build = self.index.read_bytes()
        for column, value in (("review_sha256", "videos"), ("flag_end_s", "chunks")):
            with self.subTest(column=column):
                copy = self.index  # the canonical path, so only the taint decides
                copy.write_bytes(clean_build)
                writer = sqlite3.connect(copy)
                writer.execute(f"UPDATE {value} SET {column} = {'1.0' if column == 'flag_end_s' else repr('x' * 64)}")
                writer.commit()
                writer.close()
                tainted = self.connection(copy)
                self.assertFalse(public_domain_file(tainted, "spurgeon"))
                self.assertEqual(make_app(tainted, "spurgeon").search("corner stone", 5, "bm25")["results"], [])
        # No library marker (any file that is not build_library.py's): gated.
        bare = self.root / "bare.sqlite"
        open_library(bare).close()
        self.assertFalse(public_domain_file(self.connection(bare), "spurgeon"))

    def test_query_cli_library_flag(self) -> None:
        def search(library: str) -> str:
            out = io.StringIO()
            argv = ["query.py", "corner stone", "--mode", "bm25", "-k", "3", "--library", library]
            with patch.object(query, "INDEX_DIR", self.index_dir), patch.object(sys, "argv", argv), \
                    redirect_stdout(out):
                query.main()
            return out.getvalue()

        self.assertIn(SPURGEON_ROW, search("spurgeon"))
        # The same file under a church slug: refused without a privacy config ...
        (self.index_dir / "church.sqlite").write_bytes(self.index.read_bytes())
        with self.assertRaises(SystemExit) as ctx:
            search("church")
        self.assertIn("privacy config", str(ctx.exception.code))
        # ... and with one it is gated: nothing approved, nothing shown.
        toml = self.root / "privacy.toml"
        toml.write_text("# none\n")
        with patch.dict(os.environ, {"PREACHED_PRIVACY": str(toml)}):
            self.assertIn("Nothing found", search("church"))


class ForgedMarkerTests(ClassicsBase):
    """CTO repro (#12 must-fix 1): a church file carrying the spurgeon marker at any
    --index path was served as public domain. The exemption now needs the canonical
    path, owner-only, no symlinks (store.classic_file_problem)."""

    PASSAGES = 14

    def forged(self, where: Path) -> Path:
        """A copy of a real classics build (marker 'spurgeon', no approvals) outside the canonical path."""
        where.parent.mkdir(parents=True, exist_ok=True)
        where.write_bytes(self.index.read_bytes())
        return where

    def assert_gated(self, connection) -> None:
        self.assertFalse(public_domain_file(connection, "spurgeon"))
        self.assertEqual(Searcher(connection, gated=True, library="spurgeon").bm25("corner stone", self.PASSAGES), [])
        app = make_app(connection, "spurgeon")
        self.assertEqual(app.search("corner stone", self.PASSAGES, "bm25")["results"], [])
        self.assertIsNone(app.sermon(SPURGEON_ROW))
        self.assertEqual(app.health()["chunks"], 0)
        self.assertIn("pending_review", app.health())

    def test_canonical_build_is_served(self) -> None:
        self.assertEqual(len(make_app(self.connection(), "spurgeon").search("corner stone", self.PASSAGES, "bm25")["results"]),
                         min(self.PASSAGES, self.connection().execute("SELECT count(*) FROM chunks").fetchone()[0]))

    def test_forged_marker_at_any_other_path_is_church_content(self) -> None:
        for where in (self.root / "tmp" / "forged.sqlite", self.root / "spurgeon.sqlite",
                      self.index_dir / "sub" / "spurgeon.sqlite", self.index_dir / "edwards.sqlite"):
            with self.subTest(where=where):
                self.assert_gated(self.connection(self.forged(where)))

    def test_server_and_cli_refuse_the_forged_file(self) -> None:
        from app import server

        forged = self.forged(self.root / "tmp" / "forged.sqlite")
        with self.assertRaises(SystemExit) as ctx:
            server.main(["--library", "spurgeon", "--index", str(forged), "--bm25-only"])
        self.assertIn("served only from", str(ctx.exception.code))
        # query.py --index on a library file is refused; --library only opens the canonical path.
        with patch.object(query, "INDEX_DIR", self.index_dir), self.assertRaises(SystemExit):
            query.open_index(forged, None)

    def test_symlink_at_the_canonical_path_is_not_exempt(self) -> None:
        forged = self.forged(self.root / "tmp" / "forged.sqlite")
        self.index.unlink()
        self.index.symlink_to(forged)
        self.assert_gated(self.connection(self.index))
        with patch.object(query, "INDEX_DIR", self.index_dir), self.assertRaises(SystemExit):
            query.open_index(None, "spurgeon")

    def test_symlinked_index_dir_is_not_exempt(self) -> None:
        real = self.root / "real-index"
        self.index_dir.rename(real)
        self.index_dir.symlink_to(real)
        self.assert_gated(self.connection(real / "spurgeon.sqlite"))

    def test_group_or_world_writable_is_not_exempt(self) -> None:
        for target in (self.index_dir, self.index):
            for mode in (0o775, 0o757):
                with self.subTest(target=target.name, mode=oct(mode)):
                    before = stat.S_IMODE(target.stat().st_mode)
                    target.chmod(mode if target.is_dir() else mode & 0o666)
                    try:
                        self.assert_gated(self.connection())
                    finally:
                        target.chmod(before)
                        # SQLite gave any -wal/-shm it made the file's mode at the time.
                        for suffix in ("-wal", "-shm"):
                            sidecar = Path(f"{self.index}{suffix}")
                            if sidecar.exists():
                                sidecar.chmod(stat.S_IMODE(self.index.stat().st_mode))
        self.assertTrue(public_domain_file(self.connection(), "spurgeon"))

    def test_another_owner_is_not_exempt(self) -> None:
        real = os.geteuid()
        with patch("preached.libraries.os.geteuid", return_value=real + 1):
            self.assert_gated(self.connection())

    def test_in_memory_or_unknown_file_is_not_exempt(self) -> None:
        memory = sqlite3.connect(":memory:")
        self.addCleanup(memory.close)
        memory.execute("CREATE TABLE meta (key TEXT, value TEXT)")
        memory.execute("CREATE TABLE chunks (rowid INTEGER PRIMARY KEY)")
        memory.execute("INSERT INTO meta VALUES ('library', 'spurgeon')")
        self.assertFalse(public_domain_file(memory, "spurgeon"))


class ChurchServeTests(Base):
    """#14 refuses church libraries in check_servable; #12 relaxes it ONLY with a
    privacy config loaded and the publish gate on."""

    def setUp(self) -> None:
        super().setUp()
        self.assertEqual(self.importer()[0], 0)

    def serve(self, env: dict[str, str]):
        from app import server

        class Started(Exception):
            pass

        def fake_build_app(connection, **kwargs):
            app = server.App(connection=connection, searcher=Searcher(connection), encode=None, fallback_note=None,
                             model_name=None, hosts=kwargs["hosts"], static_dir=STATIC_DIR, library=kwargs["library"])
            raise Started(app)

        with patch.dict(os.environ, env), patch.object(server, "INDEX_DIR", self.root), \
                patch.object(server, "build_app", fake_build_app):
            server.main(["--library", "wire", "--bm25-only"])

    def test_refused_without_a_privacy_config(self) -> None:
        os.environ.pop("PREACHED_PRIVACY", None)
        with self.assertRaises(SystemExit) as ctx:
            self.serve({})
        self.assertIn("privacy config", str(ctx.exception.code))

    def test_refused_without_the_gate(self) -> None:
        from app import server

        os.environ.pop("PREACHED_PRIVACY", None)
        connection = open_readonly(self.root / "wire.sqlite")
        self.addCleanup(connection.close)
        with self.assertRaises(SystemExit):
            server.check_servable(connection, "wire", self.root / "wire.sqlite")
        server.check_servable(connection, "wire", self.root / "wire.sqlite", church_gate=True)

    def test_served_gated_with_a_privacy_config(self) -> None:
        with self.assertRaises(Exception) as ctx:
            self.serve({"PREACHED_PRIVACY": str(self.empty_config)})
        app = ctx.exception.args[0]
        self.assertIsInstance(app, App)
        self.assertTrue(app.gated)
        self.assertEqual(app.health()["chunks"], 0)  # nothing approved yet
        self.assertEqual(app.health()["pending_review"], 2)
        app.connection.close()

    def test_bad_privacy_config_is_refused(self) -> None:
        bad = self.root / "bad.toml"
        bad.write_text("flagged_audio = 'play'\n")
        with self.assertRaises(SystemExit):
            self.serve({"PREACHED_PRIVACY": str(bad)})


class FailClosedTests(Base):
    """A slug that is not allow-listed, with no privacy config, exits non-zero on every path."""

    def setUp(self) -> None:
        super().setUp()
        os.environ.pop("PREACHED_PRIVACY", None)  # Base sets an empty config; these tests have none.

    def never(self, *_args, **_kwargs):
        raise AssertionError("must not run without a privacy config")

    def test_youtube_import(self) -> None:
        for extra in ([], ["--dry-run"]):
            with self.subTest(extra=extra):
                code, out, err = self.cli([CHANNEL, "--library", "church", *extra], lister=self.never,
                                          metadata=self.never, downloader=self.never, transcriber=self.never,
                                          embedder=self.never)
                self.assertEqual(code, 2)
                self.assertIn("needs a privacy config", err)
                self.assertEqual(out, "")
        self.assertEqual(list(self.root.iterdir()), [self.empty_config])

    def test_youtube_ack_review(self) -> None:
        code, _out, err = self.cli(["--library", "church", "--ack-review", ID_A])
        self.assertEqual(code, 2)
        self.assertIn("needs a privacy config", err)
        self.assertFalse((self.root / "church.sqlite").exists())

    def test_asr_chunks(self) -> None:
        transcript = self.root / "church-1.json"
        transcript.write_text(json.dumps({"meta": {"id": "church-1", "title": "Sunday"},
                                          "segments": [{"words": [[0.0, 0.4, "Gerald"], [0.5, 0.9, "Fenwick"]]}]}))
        out = self.root / "out.jsonl"
        with redirect_stderr(StringIO()) as err, self.assertRaises(SystemExit) as ctx:
            asr_chunks.main([str(transcript), "--library", "church", "--out", str(out)])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("needs a privacy config", err.getvalue())
        self.assertFalse(out.exists())

    def test_build_library_and_ingest_run(self) -> None:
        """Church audio never goes through these: refused with or without a config."""
        for env in ({}, {"PREACHED_PRIVACY": str(self.empty_config)}):
            for fn, argv in ((build_library.main, ["church"]), (ingest_run.main, ["--library", "church", "--all"])):
                with self.subTest(fn=fn.__module__, env=env), patch.dict(os.environ, env), \
                        patch.object(sys, "argv", ["x", *argv]), contextlib.redirect_stderr(io.StringIO()), \
                        self.assertRaises(SystemExit) as ctx:
                    fn()
                self.assertNotIn(ctx.exception.code, (0, None))

    def test_public_domain_slugs_never_take_church_audio(self) -> None:
        """Their files are served ungated, so the church paths refuse their slugs outright."""
        os.environ["PREACHED_PRIVACY"] = str(self.empty_config)
        for slug in PUBLIC_DOMAIN:
            with self.subTest(slug=slug):
                code, _out, err = self.cli([CHANNEL, "--library", slug], lister=self.never)
                self.assertEqual(code, 2)
                self.assertIn("public-domain", err)
                code, _out, err = self.cli(["--library", slug, "--ack-review", ID_A])
                self.assertEqual(code, 2)
                with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as ctx:
                    asr_chunks.main([str(self.root / "x.json"), "--library", slug, "--out", str(self.root / "o")])
                self.assertEqual(ctx.exception.code, 2)


class SermonLinkTests(Base):
    """/api/sermon/<id> follows the same link rules as a card."""

    def setUp(self) -> None:
        super().setUp()
        # Sermon A opens with names; sermon B has none.
        self.assertEqual(self.importer(b="Our choir sang a hymn and the morning was bright. ")[0], 0)
        for video_id in (ID_A, ID_B):
            self.assertEqual(self.cli(["--library", "wire", "--ack-review", video_id])[0], 0)
        # Links that point at the names, as an import under play would have stored them.
        writer = sqlite3.connect(self.index)
        for rowid, video_id, start_s in list(writer.execute("SELECT rowid, video_id, start_s FROM chunks")):
            writer.execute("UPDATE chunks SET audio_url = ? WHERE rowid = ?", (watch_url(video_id, start_s), rowid))
        writer.commit()
        writer.close()

    def rows(self, connection, video_id: str):
        return list(connection.execute("SELECT * FROM chunks WHERE video_id = ? ORDER BY rowid", (video_id,)))

    def test_youtube_sermon_link_skips_flagged_audio(self) -> None:
        app = self.app()
        rows = self.rows(app.connection, ID_A)
        flagged = [row for row in rows if row["flag_end_s"] is not None]
        self.assertTrue(flagged)
        self.assertIsNotNone(rows[0]["flag_end_s"])  # the stored first link plays the opening names
        sermon = app.sermon(ID_A)
        url = sermon["audio_url"]
        self.assertEqual(youtube_watch_url(url), url)  # canonical, rebuilt
        self.assertNotIn(url, {row["audio_url"] for row in flagged})
        self.assertNotEqual(url, rows[0]["audio_url"])
        # It is the link of the first chunk that neither holds nor touches a flagged chunk.
        clear = next(row for row in rows if row["flag_end_s"] is None and not touches_flagged(app.connection, row_hit(row)))
        self.assertEqual(url, policy_watch_url(ID_A, clear["start_s"], clear["end_s"], None, "none"))
        self.assertIsNone(sermon["source_url"])  # a watch link from 0:00 would play the names

    def test_unflagged_sermon_keeps_its_links(self) -> None:
        app = self.app()
        rows = self.rows(app.connection, ID_B)
        self.assertTrue(all(row["flag_end_s"] is None for row in rows))
        sermon = app.sermon(ID_B)
        self.assertEqual(sermon["audio_url"], rows[0]["audio_url"])
        self.assertEqual(sermon["source_url"], f"https://www.youtube.com/watch?v={ID_B}")

    def test_no_link_when_every_chunk_is_flagged_or_unsafe(self) -> None:
        writer = sqlite3.connect(self.index)
        writer.execute("UPDATE chunks SET flag_end_s = start_s + 0.1 WHERE video_id = ?", (ID_A,))
        # A junk stored link is rebuilt from the validated id in source_url (as for a card);
        # with no valid YouTube id anywhere, there is no link.
        writer.execute("UPDATE chunks SET audio_url = 'javascript:alert(1)', source_url = "
                       "'https://www.youtube.com/watch?v=bad' WHERE video_id = ?", (ID_B,))
        writer.commit()
        writer.close()
        app = self.app()
        self.assertIsNone(app.sermon(ID_A)["audio_url"])
        self.assertIsNone(app.sermon(ID_A)["source_url"])
        self.assertIsNone(app.sermon(ID_B)["audio_url"])


def row_hit(row):
    from types import SimpleNamespace

    return SimpleNamespace(**{key: row[key] for key in ("sermon_id", "flag_end_s", "word_start", "word_end", "start_s", "end_s")})


class ChurchAsrSermonTests(unittest.TestCase):
    """/api/sermon on the W1-C path: one archive file per sermon, through public_audio_url."""

    AUDIO = "https://archive.org/download/church-sample/church-1.mp3"

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        patcher = patch.dict(os.environ, clean_env(), clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        spoken = "Gerald Fenwick brought soup. " + FILLER * 60
        transcript = root / "church-1.json"
        transcript.write_text(json.dumps({
            "meta": {"id": "church-1", "title": "Sunday morning", "audio_url": self.AUDIO},
            "segments": [{"words": [[w.start, w.end, w.text] for w in words_for(spoken)]}],
        }))
        toml = root / "privacy.toml"
        toml.write_text("# none\n")
        self.index = root / "church.sqlite"
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            asr_chunks.main([str(transcript), "--out", str(root / "c.jsonl"), "--library", "church",
                             "--privacy", str(toml), "--index", str(self.index), *stub_audio(transcript)], embedder=embedder, coverage=lambda *_a, **_k: [])
            code = youtube_main(["--library", "church", "--ack-review", "church-1", "--privacy", str(toml)], index_dir=root)
        self.assertEqual(code, 0)

    def sermon(self):
        connection = open_readonly(self.index, check_same_thread=False)
        self.addCleanup(connection.close)
        return make_app(connection, "church").sermon("church-1")

    def test_stored_url_goes_through_public_audio_url(self) -> None:
        # The sermon opens with names (flagged), so the link is the first clear
        # chunk's own seek, never the bare file (which plays from 0:00).
        sermon = self.sermon()
        self.assertTrue(sermon["audio_url"].startswith(self.AUDIO + "#t="))
        self.assertGreater(float(sermon["audio_url"].split("#t=")[1]), 0)
        self.assertIsNone(sermon["source_url"])
        for bad in ("javascript:alert(1)", "http://archive.org/download/x.mp3", "data:audio/mp3;base64,AA",
                    "https://www.youtube.com/watch?v=short&t=javascript:"):
            with self.subTest(bad=bad):
                writer = sqlite3.connect(self.index)
                writer.execute("UPDATE chunks SET audio_url = ?", (bad,))
                writer.commit()
                writer.close()
                self.assertIsNone(self.sermon()["audio_url"])


if __name__ == "__main__":
    unittest.main()
