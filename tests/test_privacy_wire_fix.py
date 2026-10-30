"""W3-PRIV-WIRE fix-up (CTO review of PR #12).

Live publish gate, the W1-C path failing closed, titles and descriptions in
the review file, no exact times for withheld audio, symlink-safe
review files, and the privacy-config hash. Every name below is invented.
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.server import STATIC_DIR, App, hit_dict, make_server
from preached.audio_policy import public_times
from preached.corpus import load_chunk_config
from preached.privacy import Config, config_sha256, redact_metadata, write_review_file
from preached.search import Hit, Searcher
from preached.store import connect, open_readonly, replace_chunks
from preached.youtube.library import MODEL_KEY
from preached.youtube.listing import Video

from test_privacy_wire import CHANNEL, FILLER, ID_A, ID_B, OPENING_A, OPENING_B, Base, embedder, transcript, words_for
from test_privacy_wire import REPO_ROOT, videos

ID_C = "wirevideo03"
NAMES = ("Fenwick", "Gerald", "Okonkwo", "Thistlewood", "Brenda", "Townsend", "Kowalczyk", "Liam")


def encode(query: str) -> np.ndarray:
    vector = embedder([query], [query])[0]
    return vector / np.linalg.norm(vector)


class LiveServer:
    """The real HTTP handler on an ephemeral port, in a thread stopped by cleanup."""

    def __init__(self, test: unittest.TestCase, app: App) -> None:
        self.server = make_server(app, "127.0.0.1", 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        test.addCleanup(self.stop)

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def get(self, path: str) -> tuple[int, dict, str]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request("GET", path, headers={"Host": "127.0.0.1"})
            response = connection.getresponse()
            body = response.read().decode("utf-8")
        finally:
            connection.close()
        return response.status, json.loads(body), body


class LiveGateTests(Base):
    """Must-fix 1: the gate is checked per request, not at startup."""

    def live_importer(self, extra=None, *, listing=None, spoken=None):
        spoken = spoken or {ID_A: transcript(OPENING_A), ID_B: transcript(OPENING_B)}
        return self.cli(
            [CHANNEL, "--library", "wire", *(extra or [])],
            lister=lambda _url: listing or videos(),
            metadata=lambda video: {"title": video.title, "duration": 400, "upload_date": "20240602"},
            downloader=lambda video, dest: dest / f"{video.id}.m4a",
            transcriber=lambda path: spoken[Path(path).stem],
            coverage=lambda *_a, **_k: [],
            embedder=embedder,
        )

    def start(self) -> LiveServer:
        connection = open_readonly(self.index, check_same_thread=False)
        self.addCleanup(connection.close)
        app = App(
            connection=connection,
            searcher=Searcher(connection, model=MODEL_KEY),
            encode=encode,
            fallback_note=None,
            model_name=MODEL_KEY,
            hosts={"127.0.0.1"},
            static_dir=STATIC_DIR,
            library="wire",
        )
        return LiveServer(self, app)

    def served(self, live: LiveServer, query: str) -> dict[str, set[str]]:
        """Sermon ids each mode returns for ``query`` (k=25, the API maximum)."""
        found = {}
        for mode in ("bm25", "dense", "hybrid"):
            status, payload, body = live.get(f"/api/search?q={query}&k=25&mode={mode}&library=wire")
            self.assertEqual(status, 200, body)
            self.assertEqual(payload["mode"], mode)
            found[mode] = {hit["sermon_id"] for hit in payload["results"]}
        return found

    def assert_nothing_served(self, live: LiveServer, *queries: str) -> None:
        for query in queries:
            self.assertEqual(self.served(live, query), {"bm25": set(), "dense": set(), "hybrid": set()}, query)
        for video_id in (ID_A, ID_B, ID_C):
            self.assertEqual(live.get(f"/api/sermon/{video_id}")[0], 404, video_id)
        status, health, _ = live.get("/healthz")
        self.assertEqual(health["chunks"], 0)

    def test_import_redo_and_approval_while_the_server_runs(self) -> None:
        self.assertEqual(self.live_importer()[0], 0)
        self.assertEqual(self.cli(["--library", "wire", "--ack-review", ID_A])[0], 0)
        live = self.start()

        # Before: A is served by every mode and route; B is not.
        self.assertEqual(self.served(live, "faithful"), {"bm25": {ID_A}, "dense": {ID_A}, "hybrid": {ID_A}})
        status, sermon, _ = live.get(f"/api/sermon/{ID_A}")
        self.assertEqual(status, 200)
        # A has flagged chunks, so its YouTube source link (a watch link from
        # 0:00, which plays the opening names) is withheld under none.
        self.assertIsNone(sermon["source_url"])
        self.assertEqual(live.get(f"/api/sermon/{ID_B}")[0], 404)
        _, health, _ = live.get("/healthz")
        connection = open_readonly(self.index)
        count_a = connection.execute("SELECT count(*) FROM chunks WHERE video_id = ?", (ID_A,)).fetchone()[0]
        connection.close()
        self.assertEqual(health["chunks"], count_a)
        self.assertEqual(health["pending_review"], 1)

        # --redo while running, with new words in A: A drops back to unapproved
        # and neither its old nor its new text, title, URL or timing is served.
        spoken = {ID_A: transcript(OPENING_A + "The kumquatfeast was lovely. "), ID_B: transcript(OPENING_B)}
        self.assertEqual(self.live_importer(["--redo"], spoken=spoken)[0], 0)
        self.assert_nothing_served(live, "faithful", "kumquatfeast", "soup")
        _, health, body = live.get("/healthz")
        self.assertEqual(health["pending_review"], 2)
        for name in NAMES:
            self.assertNotIn(name, body)

        # A never-approved sermon imported while running is never served either.
        new = [Video(ID_C, "Harvest supper", 400, date(2024, 6, 16), f"https://www.youtube.com/watch?v={ID_C}")]
        code, _out, err = self.live_importer(listing=new, spoken={ID_C: transcript("We gathered for zucchinifest. ")})
        self.assertEqual(code, 0, err)
        self.assert_nothing_served(live, "faithful", "zucchinifest")
        self.assertEqual(live.get("/healthz")[1]["pending_review"], 3)

        # Approval while running applies on the next request, with the new text
        # findable by BM25 and by dense (vectors reload when the file changes).
        self.assertEqual(self.cli(["--library", "wire", "--ack-review", ID_A])[0], 0)
        self.assertEqual(self.served(live, "kumquatfeast")["bm25"], {ID_A})
        self.assertIn(ID_A, self.served(live, "kumquatfeast")["dense"])
        self.assertEqual(self.served(live, "zucchinifest")["dense"] - {ID_A}, set())
        self.assertEqual(live.get(f"/api/sermon/{ID_A}")[0], 200)
        self.assertEqual(live.get(f"/api/sermon/{ID_C}")[0], 404)
        _, health, _ = live.get("/healthz")
        self.assertEqual(health["pending_review"], 2)

    def test_rows_without_a_video_id_are_hidden(self) -> None:
        self.assertEqual(self.live_importer()[0], 0)
        self.assertEqual(self.cli(["--library", "wire", "--ack-review", ID_A])[0], 0)
        connection = sqlite3.connect(self.index)
        connection.execute(
            "INSERT INTO chunks (chunk_id, sermon_id, sermon_title, text, start_s, end_s) "
            "VALUES ('orphan-c0000', 'orphan', 'Orphan', 'orphanword faithful', 1.0, 2.0)"
        )
        connection.commit()
        connection.close()
        live = self.start()
        self.assertEqual(self.served(live, "orphanword")["bm25"], set())
        self.assertEqual(live.get("/api/sermon/orphan")[0], 404)

    def test_wesley_health_has_no_pending_key(self) -> None:
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("CREATE TABLE chunks (rowid INTEGER PRIMARY KEY, chunk_id TEXT, text TEXT)")
        connection.execute("INSERT INTO chunks (chunk_id, text) VALUES ('a', 'b')")
        app = App(connection, None, None, None, None, {"127.0.0.1"}, STATIC_DIR)
        self.assertEqual(app.health()["chunks"], 1)
        self.assertNotIn("pending_review", app.health())

    def test_a_church_library_missing_its_gate_serves_nothing(self) -> None:
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.executescript(
            "CREATE TABLE chunks (rowid INTEGER PRIMARY KEY, chunk_id TEXT, sermon_id TEXT, text TEXT);"
            "INSERT INTO chunks (chunk_id, sermon_id, text) VALUES ('a', 'x', 'b');"
        )
        app = App(connection, Searcher(connection), None, None, None, {"127.0.0.1"}, STATIC_DIR, library="church")
        self.assertEqual(app.health()["chunks"], 0)
        self.assertIsNone(app.sermon("x"))


class TimesTests(unittest.TestCase):
    """Must-fix 5: no exact start_s/end_s under none."""

    def hit(self, flag_end_s):
        return Hit(
            rowid=1, score=1.0, chunk_id="c", sermon_id=ID_A, sermon_title="t", text="x [name]",
            start_s=100.0, end_s=145.0, source_url=None, scripture=None,
            audio_url="https://archive.org/download/x/y.mp3", text_source="asr", flag_end_s=flag_end_s,
        )

    def test_public_times(self) -> None:
        self.assertEqual(public_times(100.0, 145.0, None, "none"), (100.0, 145.0, True))
        self.assertEqual(public_times(100.0, 145.0, 112.0, "play"), (100.0, 145.0, True))
        self.assertEqual(public_times(100.0, 145.0, 112.0, "none"), (None, None, False))
        with self.assertRaises(ValueError):
            public_times(100.0, 145.0, 112.0, "shifted")

    def test_no_field_brackets_the_name(self) -> None:
        payload = hit_dict(self.hit(112.0), "none")
        self.assertNotEqual(payload["start_s"], 100.0)
        self.assertIsNone(payload["end_s"])
        self.assertNotIn(100.0, payload.values())

    def test_query_cli_prints_no_exact_start(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "search"))
        try:
            import query
        finally:
            sys.path.pop(0)
        for policy, shown in (("none", "start_s=None"), ("play", "start_s=100.0")):
            out = StringIO()
            with redirect_stdout(out):
                query.print_hits("q", "bm25", None, [self.hit(112.0)], policy)
            self.assertIn(shown, out.getvalue(), policy)
            if policy != "play":
                self.assertNotIn("100.0", out.getvalue())
                self.assertNotIn("0:01:40", out.getvalue())

    @unittest.skipUnless(shutil.which("deno"), "deno not installed")
    def test_page_shows_text_only_for_withheld_audio(self) -> None:
        dom = """
        function node(tag) {
          return { tag: tag, children: [], className: "", textContent: "", attrs: {},
            appendChild(c) { this.children.push(c); return c; },
            setAttribute(k, v) { this.attrs[k] = v; }, addEventListener() {} };
        }
        globalThis.window = { location: { origin: "http://127.0.0.1:8000" } };
        globalThis.document = { addEventListener() {}, getElementById() { return null; },
          createElement: node };
        function texts(n) { return [n.textContent].concat(...n.children.map(texts)); }
        """
        checks = """
        var withheld = texts(renderCard({ sermon_title: "t", text: "x", start_s: null, end_s: null,
          audio_url: null, audio_withheld: true })).join("|");
        if (!withheld.includes("Text only")) throw new Error("withheld: " + withheld);
        if (withheld.includes("coming soon")) throw new Error("withheld shows coming soon");
        console.log("ok");
        """
        app_js = (REPO_ROOT / "app" / "static" / "app.js").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "check.js"
            script.write_text(dom + app_js + checks)
            result = subprocess.run(
                ["deno", "run", "--quiet", "--no-prompt", "--no-config", str(script)],
                capture_output=True, text=True, timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)


class TitleTests(Base):
    """Must-fix 3: titles in ALL CAPS and Title Case; title and description in the review file."""

    def test_cto_examples_are_fully_redacted(self) -> None:
        cases = {
            "PRAYER FOR GRACE TOWNSEND": "PRAYER FOR [name] [name]",
            "Liam and Olivia Kowalczyk": "[name] and [name] [name]",
            "Baby Dedication: Liam and Olivia Kowalczyk": "Baby Dedication: [name] and [name] [name]",
            "BABY DEDICATION: LIAM AND OLIVIA KOWALCZYK": "BABY DEDICATION: [name] AND [name] [name]",
            "Funeral For Margaret Ellison": "Funeral For [name] [name]",
        }
        for title, expected in cases.items():
            self.assertEqual(redact_metadata(title, config=Config())[0], expected, title)
        # Scripture and plain sermon titles are left alone in either casing.
        for title in ("THE GRACE OF GOD", "The Grace Of God", "Mark 4: The Sower", "JOHN 3:16 FOR GOD SO LOVED", "Faith Over Fear"):
            self.assertEqual(redact_metadata(title, config=Config())[0], title)

    def test_title_and_description_are_in_the_review_file(self) -> None:
        spoken = {ID_A: transcript(OPENING_A), ID_B: transcript(OPENING_B)}
        meta = {
            ID_A: {"title": "PRAYER FOR GRACE TOWNSEND", "description": "Liam and Olivia Kowalczyk joined us."},
            ID_B: {"title": "Sunday morning"},
        }
        code, out, err = self.cli(
            [CHANNEL, "--library", "wire"],
            lister=lambda _url: videos(),
            metadata=lambda video: {**meta[video.id], "duration": 400, "upload_date": "20240602"},
            downloader=lambda video, dest: dest / f"{video.id}.m4a",
            transcriber=lambda path: spoken[Path(path).stem],
            coverage=lambda *_a, **_k: [],
            embedder=embedder,
        )
        self.assertEqual(code, 0, err)
        raw = self.index.read_bytes()
        for name in (b"GRACE", b"TOWNSEND", b"Liam", b"Kowalczyk"):
            self.assertNotIn(name, raw)
        lines = [json.loads(line) for line in self.review_file(ID_A).read_text().splitlines()]
        title, description = lines[0], lines[1]
        self.assertEqual(title["field"], "title")
        connection = open_readonly(self.index)
        stored = connection.execute("SELECT title FROM videos WHERE video_id = ?", (ID_A,)).fetchone()[0]
        connection.close()
        self.assertEqual(title["stored"], stored)
        self.assertEqual(stored, "PRAYER FOR [name] [name]")
        self.assertEqual(description["field"], "description")
        self.assertIsNone(description["stored"])
        self.assertEqual(description["redacted"], "[name] and [name] [name] joined us.")
        self.assertTrue(description["review"])  # the review() output, original words included
        # Editing the title line is covered by the approved sha256.
        text = self.review_file(ID_A).read_text().replace("PRAYER FOR [name] [name]", "PRAYER FOR [name]")
        self.review_file(ID_A).write_text(text)
        code, _out, err = self.cli(["--library", "wire", "--ack-review", ID_A])
        self.assertEqual(code, 1)
        self.assertIn("changed since import", err)
        for name in NAMES:
            self.assertNotIn(name, out + err)


class ConfigHashTests(Base):
    """Should-fix: approval is refused when the privacy config changed since import."""

    def test_changed_config_blocks_approval(self) -> None:
        toml = self.root / "privacy.toml"
        toml.write_text('block = ["Timothy"]\n')
        self.assertEqual(self.importer(["--privacy", str(toml)])[0], 0)
        # Another config at approval (Base sets an empty one in the env): refused.
        code, _out, err = self.cli(["--library", "wire", "--ack-review", ID_A])
        self.assertEqual(code, 1)
        self.assertIn("privacy config changed", err)
        # No config at all: refused before the index is opened.
        with patch.dict(os.environ, {"PREACHED_PRIVACY": ""}):
            code, _out, err = self.cli(["--library", "wire", "--ack-review", ID_A])
        self.assertEqual(code, 2)
        self.assertIn("needs a privacy config", err)
        toml.write_text('block = ["Timothy", "Paul"]\n')
        code, _out, err = self.cli(["--library", "wire", "--ack-review", ID_A, "--privacy", str(toml)])
        self.assertEqual(code, 1)
        self.assertIn("privacy config changed", err)
        # The same settings (any order, same file or env) approve.
        toml.write_text('block = ["timothy"]\nflagged_audio = "none"\n')
        with patch.dict(os.environ, {"PREACHED_PRIVACY": str(toml)}):
            code, _out, err = self.cli(["--library", "wire", "--ack-review", ID_A])
        self.assertEqual(code, 0, err)

    def test_hash_ignores_order_but_not_content(self) -> None:
        a = Config.from_dict({"block": ["Ann", "Bo"], "allow": ["John Wesley"]})
        b = Config.from_dict({"block": ["bo", "ann"], "allow": ["john wesley"]})
        self.assertEqual(config_sha256(a), config_sha256(b))
        self.assertNotEqual(config_sha256(a), config_sha256(Config()))
        self.assertNotEqual(config_sha256(Config()), config_sha256(Config.from_dict({"drop": [{"start": 0, "end": 1}]})))


class ReviewFileTests(unittest.TestCase):
    """Should-fix: write_review_file never follows a symlink."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write(self, path: Path) -> int:
        with redirect_stdout(StringIO()):
            return write_review_file([{"text": "Invented Person"}], path)

    def test_symlink_at_the_file_path_is_replaced_not_followed(self) -> None:
        victim = self.root / "victim.txt"
        victim.write_text("keep me\n")
        os.chmod(victim, 0o644)
        folder = self.root / "review"
        folder.mkdir(mode=0o700)
        link = folder / "x.review.jsonl"
        link.symlink_to(victim)
        self.assertEqual(self.write(link), 1)
        self.assertEqual(victim.read_text(), "keep me\n")
        self.assertEqual(stat.S_IMODE(victim.stat().st_mode), 0o644)
        self.assertFalse(link.is_symlink())
        self.assertEqual(stat.S_IMODE(link.stat().st_mode), 0o600)
        self.assertIn("Invented Person", link.read_text())
        self.assertEqual([p.name for p in folder.iterdir()], ["x.review.jsonl"])  # no temp file left

    def test_existing_open_directory_is_tightened(self) -> None:
        folder = self.root / "review"
        folder.mkdir()
        os.chmod(folder, 0o777)
        self.write(folder / "x.review.jsonl")
        self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700)

    def test_symlinked_directory_is_refused(self) -> None:
        real = self.root / "elsewhere"
        real.mkdir()
        (self.root / "review").symlink_to(real)
        with self.assertRaises(RuntimeError):
            self.write(self.root / "review" / "x.review.jsonl")
        self.assertEqual(list(real.iterdir()), [])


class AsrGateTests(unittest.TestCase):
    """Must-fix 2: align/asr_chunks.py fails closed for every library but wesley."""

    def setUp(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "align"))
        self.addCleanup(sys.path.remove, str(REPO_ROOT / "align"))
        import asr_chunks

        self.module = asr_chunks
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        env = {k: v for k, v in os.environ.items() if k not in ("PREACHED_PRIVACY", "PREACHED_FLAGGED_AUDIO")}
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        words = words_for(OPENING_A + FILLER * 40)
        self.transcript_path = self.root / "church-1.json"
        self.transcript_path.write_text(json.dumps({
            "meta": {"id": "church-1", "title": "Soup With Gerald Fenwick"},
            "segments": [{"words": [[w.start, w.end, w.text] for w in words]}],
        }))
        self.toml = self.root / "privacy.toml"
        self.toml.write_text('block = ["Timothy"]\n')
        self.out = self.root / "chunks.jsonl"

    def run_main(self, argv: list[str], **kwargs) -> tuple[int, str, str]:
        out, err = StringIO(), StringIO()
        code = 0
        with redirect_stdout(out), redirect_stderr(err):
            try:
                self.module.main([str(self.transcript_path), "--out", str(self.out), *argv], **{"coverage": lambda *_a, **_k: [], **kwargs})
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 2
        return code, out.getvalue(), err.getvalue()

    def test_library_is_required(self) -> None:
        self.assertEqual(self.run_main([])[0], 2)
        self.assertFalse(self.out.exists())

    def test_church_without_a_config_is_refused(self) -> None:
        code, _out, err = self.run_main(["--library", "church"])
        self.assertEqual(code, 2)
        self.assertIn("needs a privacy config", err)
        self.assertFalse(self.out.exists())

    def test_church_is_always_redacted_and_keyed_to_the_gate(self) -> None:
        index = self.root / "church.sqlite"
        for argv, env in ((["--privacy", str(self.toml)], {}), ([], {"PREACHED_PRIVACY": str(self.toml)})):
            with patch.dict(os.environ, env):
                code, out, err = self.run_main(["--library", "church", "--index", str(index), *argv], embedder=embedder)
            self.assertEqual(code, 0, err)
            text = self.out.read_text()
            for name in ("Fenwick", "Gerald", "Timothy"):
                self.assertNotIn(name, text)
                self.assertNotIn(name, out + err)
                self.assertNotIn(name.encode(), index.read_bytes())
            rows = [json.loads(line) for line in text.splitlines()]
            self.assertEqual({row["video_id"] for row in rows}, {"church-1"})
            self.assertEqual(rows[0]["sermon_title"], "Soup With [name] [name]")
            self.assertIsNotNone(rows[0]["flag_end_s"])
            review = self.root / "church" / "review" / "church-1.review.jsonl"
            self.assertEqual(stat.S_IMODE(review.stat().st_mode), 0o600)
            self.assertEqual(json.loads(review.read_text().splitlines()[0])["field"], "title")

        # Loaded unpublished: nothing is served until a human approves.
        connection = open_readonly(index)
        self.addCleanup(connection.close)
        self.assertEqual(Searcher(connection, gated=True).bm25("faithful", 5), [])
        from preached.youtube.cli import main as youtube_main

        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            code = youtube_main(["--library", "church", "--ack-review", "church-1", "--privacy", str(self.toml)], index_dir=self.root)
        self.assertEqual(code, 0)
        self.assertTrue(Searcher(connection, gated=True).bm25("faithful", 5))

    def test_gate_keyed_chunks_never_enter_an_ungated_index(self) -> None:
        rows = self.module.asr_chunks(json.loads(self.transcript_path.read_text()), load_chunk_config(), privacy=Config())
        connection = connect(self.root / "wesley-like.sqlite")
        self.addCleanup(connection.close)
        with self.assertRaises(ValueError):
            replace_chunks(connection, rows)
        self.assertEqual(connection.execute("SELECT count(*) FROM chunks").fetchone()[0], 0)

    def test_without_index_review_goes_to_the_index_dir(self) -> None:
        with patch("preached.paths.INDEX_DIR", self.root / "idx"):
            code, out, err = self.run_main(["--library", "church", "--privacy", str(self.toml)])
        self.assertEqual(code, 0, err)
        self.assertIn("UNPUBLISHED", out)
        self.assertTrue((self.root / "idx" / "church" / "review" / "church-1.review.jsonl").is_file())

    def test_wesley_output_is_unchanged(self) -> None:
        # The wesley path takes only wesley-* sermons (should-fix): a church id is refused ...
        code, _out, err = self.run_main(["--library", "wesley"])
        self.assertEqual(code, 2)
        self.assertIn("wesley-*", err)
        self.assertFalse(self.out.exists())
        # ... and a wesley id is chunked exactly as before, unredacted.
        sample = json.loads(self.transcript_path.read_text())
        sample["meta"]["id"] = "wesley-001"
        self.transcript_path.write_text(json.dumps(sample))
        plain = self.module.asr_chunks(sample, load_chunk_config())
        code, _out, err = self.run_main(["--library", "wesley"])
        self.assertEqual(code, 0, err)
        self.assertEqual([json.loads(line) for line in self.out.read_text().splitlines()], plain)
        self.assertNotIn("video_id", plain[0])
        self.assertIn("Fenwick", plain[0]["text"])
        self.assertNotEqual(self.run_main(["--library", "wesley", "--privacy", str(self.toml)])[0], 0)


if __name__ == "__main__":
    unittest.main()
