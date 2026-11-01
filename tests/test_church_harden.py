"""PR #37 CTO round 3: church-deploy hard conditions 1 and 2, S1, S2, S4 and nits.

HC1: a church file busy at startup (a writer's lock, or WAL mode while
``--ack-review`` runs) is a pause, retried with backoff; no restart.
HC2: the real server, church side on, under #29's connection caps, health
buckets and refusal-log flush, through SIGTERM and the stuck path.

Every church file here is a synthetic fixture. No real church data is used.
"""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import json
import os
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app.server as server  # noqa: E402
import preached.library as library  # noqa: E402
import test_shutdown  # noqa: E402
from app.server import STATIC_DIR, build_app  # noqa: E402
from preached.library import ChurchRefused, open_church_readonly  # noqa: E402
from test_church_r2 import ABOVE, ATTACKER, build_attacker, texts  # noqa: E402
from test_church_wire import CHURCH_ON, PRIVACY, build_church  # noqa: E402
from test_side import build_library, classic_rows, reopen  # noqa: E402

LOCKED = "the church file is locked by a writer (database is locked)"
PAUSED_LOCK = f"church side paused: {LOCKED}"
OPENED = "church side: sample, read-only, through the publish gate"


HOLD_LOCK = (
    "import sqlite3, sys\n"
    "writer = sqlite3.connect(sys.argv[1], isolation_level=None)\n"
    "writer.execute('BEGIN EXCLUSIVE')\n"
    "print('locked', flush=True)\n"
    "sys.stdin.read()\n"
    "writer.execute('ROLLBACK')\n"
    "writer.close()\n"
)


def lock(path: Path) -> subprocess.Popen:
    """Another process holding ``BEGIN EXCLUSIVE`` on ``path``, as ``--ack-review`` does while it writes.

    Not this process: while a connection here holds a lock on the file,
    SQLite keeps a closed connection's descriptor and hands it to the next
    open, which the one-new-descriptor check then refuses (fail closed).
    """
    writer = subprocess.Popen(
        [sys.executable, "-I", "-c", HOLD_LOCK, str(path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    assert writer.stdout.readline().strip() == "locked"
    return writer


def release(writer: subprocess.Popen) -> None:
    if writer.poll() is None:
        writer.stdin.close()
        writer.wait(10)
    writer.stdout.close()


class _Root(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.wesley = self.root / "wesley.sqlite"
        build_library(self.wesley, *classic_rows())
        self.church = self.root / "sample.sqlite"
        build_church(self.church)
        env = patch.dict(os.environ, {"PREACHED_PRIVACY": str(PRIVACY), **CHURCH_ON})
        env.start()
        self.addCleanup(env.stop)


class StartupPauseTests(_Root):
    """HC1, in process: build_app with main's ``open_church``, a busy file at startup."""

    def opener(self):
        calls: list[int] = []

        def church_open():
            calls.append(1)
            return server.open_church(self.church, slug="sample", classic_library="wesley", classic_index=self.wesley)

        return church_open, calls

    def build(self, church_open):
        classic = reopen(self.wesley)
        self.addCleanup(classic.close)
        app = build_app(
            classic,
            model_key="granite-english-r2",
            bm25_only=True,
            hosts={"127.0.0.1"},
            static_dir=STATIC_DIR,
            floor=0.5,
            church_open=church_open,
        )
        self.addCleanup(lambda: app.church_connection is not None and app.church_connection.close())
        return app

    def present(self, app) -> bool:
        return app.side("approvedtoken", 5, "bm25")["church"]["present"]

    def test_a_writer_lock_at_startup_is_a_pause_and_the_church_side_resumes_without_a_restart(self) -> None:
        church_open, calls = self.opener()
        writer = lock(self.church)
        try:
            with self.assertLogs(level="INFO") as logs:
                app = self.build(church_open)
            self.assertEqual([line for line in logs.output if "church side" in line], [f"INFO:root:{PAUSED_LOCK}"])
            self.assertIsNone(app.church_connection)
            self.assertEqual(app.library_names(), ["wesley"])
            self.assertEqual(app._church_backoff, 2 * server.CHURCH_RETRY_FIRST_S)
            # Before the retry time no open is tried, and nothing more is logged.
            with self.assertNoLogs(level="INFO"):
                for _ in range(5):
                    self.assertFalse(self.present(app))
            self.assertEqual(len(calls), 1)
            # Due again but still locked: one more try, the wait doubles, still one pause line.
            app._church_retry_at = 0.0
            with self.assertNoLogs(level="INFO"):
                self.assertFalse(self.present(app))
            self.assertEqual((len(calls), app._church_backoff), (2, 4 * server.CHURCH_RETRY_FIRST_S))
        finally:
            release(writer)
        app._church_retry_at = 0.0
        with self.assertLogs(level="INFO") as logs:
            side = app.side("approvedtoken", 5, "bm25")
        self.assertTrue(side["church"]["present"])
        self.assertTrue(side["church"]["results"])
        self.assertEqual(logs.output, [f"INFO:root:{OPENED}", "INFO:root:church side resumed"])
        self.assertEqual(app.library_names(), ["wesley", "sample"])
        self.assertTrue(app.search("approvedtoken", 5, "bm25", library="sample")["results"])
        self.assertEqual(len(calls), 3)
        self.assertEqual(app.church_connection.execute("PRAGMA busy_timeout").fetchone()[0], 0)

    def test_main_holds_the_startup_pause_line_until_log_startup_pause(self) -> None:
        church_open, _calls = self.opener()
        classic = reopen(self.wesley)
        self.addCleanup(classic.close)
        writer = lock(self.church)
        try:
            with self.assertNoLogs(level="INFO"):
                app = build_app(classic, model_key="granite-english-r2", bm25_only=True, hosts={"127.0.0.1"},
                                static_dir=STATIC_DIR, floor=0.5, church_open=church_open, defer_church_pause_log=True)
            with self.assertLogs(level="INFO") as logs:
                app.log_startup_pause()
                app.log_startup_pause()
            self.assertEqual(logs.output, [f"INFO:root:{PAUSED_LOCK}"])
        finally:
            release(writer)

    def test_a_pause_after_startup_is_logged_even_in_the_deferred_mode(self) -> None:
        # SF1: log_startup_pause must switch deferral off, or a later pause is held forever.
        church_open, _calls = self.opener()
        classic = reopen(self.wesley)
        self.addCleanup(classic.close)
        app = build_app(classic, model_key="granite-english-r2", bm25_only=True, hosts={"127.0.0.1"},
                        static_dir=STATIC_DIR, floor=0.5, church_open=church_open, defer_church_pause_log=True)
        self.addCleanup(lambda: app.church_connection is not None and app.church_connection.close())
        app.log_startup_pause()  # nothing was paused at start: no line, deferral off
        writer = lock(self.church)
        try:
            with self.assertLogs(level="INFO") as logs:
                app.side("approvedtoken", 5, "bm25")
            self.assertIn(f"INFO:root:{PAUSED_LOCK}", logs.output)
        finally:
            release(writer)

    def test_the_backoff_doubles_to_the_cap(self) -> None:
        church_open, calls = self.opener()
        writer = lock(self.church)
        self.addCleanup(release, writer)
        with self.assertLogs(level="INFO"):
            app = self.build(church_open)
        waits = []
        for _ in range(8):
            app._church_retry_at = 0.0
            before = time.monotonic()
            self.assertFalse(self.present(app))
            waits.append(round(app._church_retry_at - before))
        self.assertEqual(waits, [2, 4, 8, 16, 30, 30, 30, 30])
        self.assertEqual(len(calls), 9)

    def test_a_search_for_the_church_slug_also_retries_the_open(self) -> None:
        church_open, _calls = self.opener()
        writer = lock(self.church)
        with self.assertLogs(level="INFO"):
            app = self.build(church_open)
        with self.assertRaises(server.BadRequest):
            app.search("approvedtoken", 5, "bm25", library="sample")  # paused: the generic 400
        release(writer)
        app._church_retry_at = 0.0
        with self.assertLogs(level="INFO") as logs:
            self.assertTrue(app.search("approvedtoken", 5, "bm25", library="sample")["results"])
        self.assertEqual(logs.output, [f"INFO:root:{OPENED}", "INFO:root:church side resumed"])

    def test_wal_mode_at_startup_is_a_pause_until_ack_review_leaves_delete_mode(self) -> None:
        # --ack-review writes in WAL mode and leaves DELETE mode when it is done.
        with closing(sqlite3.connect(self.church)) as writer:
            self.assertEqual(writer.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        church_open, _calls = self.opener()
        with self.assertLogs(level="INFO") as logs:
            app = self.build(church_open)
        self.assertEqual(
            [line for line in logs.output if "church side" in line],
            ["INFO:root:church side paused: sample.sqlite is in WAL journal mode"],
        )
        self.assertFalse(self.present(app))
        for suffix in ("-wal", "-shm"):
            self.assertFalse(Path(f"{self.church}{suffix}").exists(), suffix)
        with closing(sqlite3.connect(self.church)) as writer:
            self.assertEqual(writer.execute("PRAGMA journal_mode=DELETE").fetchone()[0], "delete")
        app._church_retry_at = 0.0
        with self.assertLogs(level="INFO") as logs:
            self.assertTrue(self.present(app))
        self.assertEqual(logs.output, [f"INFO:root:{OPENED}", "INFO:root:church side resumed"])

    def test_a_refusal_found_on_a_retry_ends_the_retries(self) -> None:
        church_open, calls = self.opener()
        writer = lock(self.church)
        with self.assertLogs(level="INFO"):
            app = self.build(church_open)
        release(writer)
        os.chmod(self.church, 0o666)
        app._church_retry_at = 0.0
        with self.assertLogs(level="INFO") as logs:
            self.assertFalse(self.present(app))
        # The pause ends explicitly, right after the refusal line.
        self.assertEqual(len(logs.output), 2, logs.output)
        self.assertTrue(logs.output[0].startswith("ERROR:root:church side refused: "), logs.output)
        self.assertEqual(logs.output[1], "INFO:root:church side pause ended: refused")
        os.chmod(self.church, 0o644)
        app._church_retry_at = 0.0
        with self.assertNoLogs(level="INFO"):
            self.assertFalse(self.present(app))
        self.assertEqual(len(calls), 2)

    def test_a_lock_during_the_searcher_build_is_a_pause_and_closes_that_connection(self) -> None:
        church_open, calls = self.opener()
        real = server.load_church_searcher
        opened = []

        def locked_build(connection, *args, **kwargs):
            opened.append(connection)
            if len(opened) == 1:
                writer = lock(self.church)
                try:
                    connection.execute("SELECT count(*) FROM chunks").fetchone()
                finally:
                    release(writer)
            return real(connection, *args, **kwargs)

        with patch.object(server, "load_church_searcher", side_effect=locked_build):
            with self.assertLogs(level="INFO") as logs:
                app = self.build(church_open)
            self.assertIn(f"INFO:root:{PAUSED_LOCK}", logs.output)
            with self.assertRaises(sqlite3.ProgrammingError):
                opened[0].execute("SELECT 1")  # S4: closed, not leaked
            app._church_retry_at = 0.0
            self.assertTrue(self.present(app))
        self.assertEqual(len(calls), 2)

    def test_a_writer_lock_at_startup_through_main(self) -> None:
        # main hands build_app the open itself, not an opened connection.
        captured = {}

        class Stop(Exception):
            pass

        def fake_build_app(connection, **kwargs):
            captured.update(kwargs)
            connection.close()
            raise Stop

        with patch.object(server, "build_app", side_effect=fake_build_app), self.assertRaises(Stop):
            server.main(["--bm25-only", "--index", str(self.wesley), "--church-index", str(self.church),
                         "--church-library", "sample"])
        self.assertNotIn("church_connection", captured)
        writer = lock(self.church)
        try:
            with self.assertRaises(library.ChurchPaused) as paused:
                captured["church_open"]()
        finally:
            release(writer)
        self.assertEqual(str(paused.exception), LOCKED)
        connection, slug, _check = captured["church_open"]()
        connection.close()
        self.assertEqual(slug, "sample")


class StartPausedFormsTests(_Root):
    """HC1: every place the start-up open can meet a writer's lock is a start pause, not a refusal."""

    def busy_error(self) -> sqlite3.OperationalError:
        writer = lock(self.church)
        try:
            with closing(sqlite3.connect(self.church, timeout=0)) as probe:
                with self.assertRaises(sqlite3.OperationalError) as caught:
                    probe.execute("SELECT count(*) FROM chunks").fetchone()
        finally:
            release(writer)
        self.assertTrue(library.is_busy(caught.exception))
        return caught.exception

    def assert_start_paused(self) -> None:
        with self.assertRaises(library.ChurchStartPaused) as caught:
            open_church_readonly(self.church, classic=self.wesley)
        self.assertEqual(caught.exception.reason, LOCKED)
        self.assertEqual(str(caught.exception), f"{LOCKED}; it is not opened")  # the CLI's refusal text

    def test_a_lock_at_the_connect(self) -> None:
        busy = self.busy_error()
        with patch.object(library, "open_readonly", side_effect=busy):
            self.assert_start_paused()

    def test_a_lock_at_the_publish_gate_read(self) -> None:
        busy = self.busy_error()
        with patch("preached.store.visible_sql", side_effect=busy):
            self.assert_start_paused()

    def test_a_lock_at_the_shape_read(self) -> None:
        writer = lock(self.church)
        try:
            self.assert_start_paused()
        finally:
            release(writer)


class SearcherBuildFailureTests(_Root):
    """S4 and the DEPLOY 'one line' nit: a searcher that fails to build closes the connection, one line."""

    def test_the_connection_is_closed_and_one_line_is_logged(self) -> None:
        classic = reopen(self.wesley)
        self.addCleanup(classic.close)
        church = reopen(self.church)
        with patch.object(server, "load_church_searcher", side_effect=RuntimeError("no searcher\nsecond line")):
            with self.assertLogs(level="ERROR") as logs:
                app = build_app(
                    classic, model_key="granite-english-r2", bm25_only=True, hosts={"127.0.0.1"},
                    static_dir=STATIC_DIR, church_connection=church, church_library="sample",
                )
        self.assertEqual(
            logs.output,
            ["ERROR:root:church side refused: its searcher could not be built (RuntimeError: no searcher second line)"],
        )
        self.assertIsNone(logs.records[0].exc_info)  # no traceback after the alert line
        with self.assertRaises(sqlite3.ProgrammingError):
            church.execute("SELECT 1")
        self.assertIsNone(app.church_connection)
        self.assertFalse(app.side("approvedtoken", 5, "bm25")["church"]["present"])

    def test_through_main_s_open_too(self) -> None:
        classic = reopen(self.wesley)
        self.addCleanup(classic.close)
        opened = []

        def church_open():
            side = server.open_church(self.church, slug="sample", classic_library="wesley", classic_index=self.wesley)
            opened.append(side[0])
            return side

        with patch.object(server, "load_church_searcher", side_effect=RuntimeError("boom")):
            with self.assertLogs(level="INFO") as logs:
                build_app(classic, model_key="granite-english-r2", bm25_only=True, hosts={"127.0.0.1"},
                          static_dir=STATIC_DIR, church_open=church_open)
        self.assertEqual(logs.output[-1], "ERROR:root:church side refused: its searcher could not be built (RuntimeError: boom)")
        self.assertNotIn("Traceback", "\n".join(logs.output))
        with self.assertRaises(sqlite3.ProgrammingError):
            opened[0].execute("SELECT 1")


class NameWalkTests(_Root):
    """S1: a symlink inside a 0777 dir pointing at a safe dir is refused by the name's own walk."""

    def test_a_symlinked_directory_in_a_world_writable_dir_is_refused(self) -> None:
        safe = self.root / "safe"
        safe.mkdir()
        church = safe / "church.sqlite"
        build_church(church)
        shared = self.root / "open"
        shared.mkdir()
        os.chmod(shared, 0o777)
        self.addCleanup(os.chmod, shared, 0o700)
        os.symlink(safe, shared / "link")
        given = shared / "link" / "church.sqlite"
        # The real path is all safe; only the name passes through the 0777 dir.
        self.assertIsNone(library.church_path_problem(church))
        self.assertEqual(Path(os.path.realpath(given)), Path(os.path.realpath(church)))
        self.assertIn(f"directory {shared} {ABOVE} (mode 777)", library.church_path_problem(given) or "")
        with self.assertRaises(ChurchRefused) as caught:
            open_church_readonly(given, classic=self.wesley)
        self.assertIn(f"directory {shared} {ABOVE} (mode 777)", str(caught.exception))
        # Once open, the per-request check walks the name too.
        connection, identity = open_church_readonly(church, classic=self.wesley)
        self.addCleanup(connection.close)
        self.assertIn(f"directory {shared} {ABOVE}", library.church_file_problem(connection, given, identity) or "")


class NewDescriptorCountTests(_Root):
    """S2: exactly one new descriptor at the connect, or the file is not opened.

    SQLite is pointed at an attacker's file around the connect (a swap the
    name checks cannot see), and the descriptor snapshot is made to show 0
    or 2 new files. Either count must refuse, so no attacker text is served.
    """

    def swapped_open(self, report):
        """open_readonly against the attacker's file; then ``_new_files`` returns ``report(real)``."""
        safe = self.root / "safe"
        (safe / "sub").mkdir(parents=True)
        (safe / "evil").mkdir()
        church = safe / "sub" / "church.sqlite"
        build_church(church)
        build_attacker(safe / "evil" / "church.sqlite")
        real_open = library.open_readonly
        real_new = library._new_files
        checked = os.stat(church)

        def swap_around_connect(path, **kwargs):
            os.rename(safe / "sub", safe / "sub-real")
            os.rename(safe / "evil", safe / "sub")
            try:
                return real_open(path, **kwargs)
            finally:
                os.rename(safe / "sub", safe / "evil")
                os.rename(safe / "sub-real", safe / "sub")

        def new_files(before):
            opened, now = real_new(before)
            return report(opened, checked), now

        with patch.object(library, "open_readonly", side_effect=swap_around_connect), patch.object(
            library, "_new_files", side_effect=new_files
        ):
            with self.assertRaises(ChurchRefused) as caught:
                connection, _identity = open_church_readonly(church, classic=self.wesley)
                self.addCleanup(connection.close)
                self.fail(f"opened, serving: {texts(connection)[:80]}")
        self.assertNotIn(ATTACKER, str(caught.exception))
        return str(caught.exception)

    def test_no_new_descriptor_is_refused(self) -> None:
        message = self.swapped_open(lambda opened, checked: [])
        self.assertEqual(message, "church.sqlite could not be checked once opened (no new descriptor); it is not opened")

    def test_two_new_descriptors_are_refused_even_when_one_is_the_checked_file(self) -> None:
        message = self.swapped_open(lambda opened, checked: [*opened, checked])
        self.assertEqual(message, "church.sqlite could not be checked once opened (2 new files, not 1); it is not opened")


class NotRegularFileTests(_Root):
    """Nit: a FIFO, directory or device at the church name is named as such, not 'not found'."""

    def test_each_kind_is_named(self) -> None:
        fifo = self.root / "fifo.sqlite"
        os.mkfifo(fifo, 0o600)
        directory = self.root / "dir.sqlite"
        directory.mkdir()
        cases = {
            fifo: "fifo.sqlite is not a regular file (a FIFO); it is not opened",
            directory: "dir.sqlite is not a regular file (a directory); it is not opened",
            self.root / "missing.sqlite": "missing.sqlite not found; the church side is empty",
        }
        if os.path.exists("/dev/null") and stat.S_ISCHR(os.stat("/dev/null").st_mode):
            cases[Path("/dev/null")] = "null is not a regular file (a character device); it is not opened"
        for path, want in cases.items():
            with self.subTest(path=path.name):
                with self.assertRaises(ChurchRefused) as caught:
                    open_church_readonly(path, classic=self.wesley)
                self.assertEqual(str(caught.exception), want)


# --- the real server (app/server.py as a script) ----------------------------

# Holds each church check (a request thread, not startup) for HOLD_S after
# touching $MARK. The check runs before any church read, under the App lock.
HOLD_CHURCH = (
    "import threading\n"
    "import preached.library as _lib\n"
    "_real_check = _lib.church_file_problem\n"
    "def _held_check(*a, **k):\n"
    "    if threading.current_thread() is not threading.main_thread():\n"
    "        open(os.environ['MARK'], 'w').close()\n"
    "        time.sleep(HOLD_S)\n"
    "    return _real_check(*a, **k)\n"
    "_lib.church_file_problem = _held_check\n"
)


def raw_get(port: int, path: str, timeout: float = 30, source: str = "127.0.0.1") -> tuple[int, bytes]:
    """One request with ``Connection: close``, read to EOF: the server has
    released the connection and its request slot before the close."""
    return raw_get_full(port, path, timeout, source)[::2]


def raw_get_full(port: int, path: str, timeout: float = 30, source: str = "127.0.0.1") -> tuple[int, dict, bytes]:
    """``raw_get`` with the response headers (lower-case names) as well, from the given source address."""
    with socket.create_connection(("127.0.0.1", port), timeout=timeout, source_address=(source, 0)) as sock:
        sock.sendall(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".encode())
        chunks = []
        while True:
            data = sock.recv(65536)
            if not data:
                break
            chunks.append(data)
    raw = b"".join(chunks)
    head, _, body = raw.partition(b"\r\n\r\n")
    status = int(head.split(b" ", 2)[1]) if head else 0
    headers = {}
    for line in head.decode("latin-1").split("\r\n")[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return status, headers, body


class _ChurchServer(unittest.TestCase):
    """The server script with the church side on (privacy config, deploy switch)."""

    ENV: dict = {}

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.index = test_shutdown._fixture_index(self.root / "wesley-fixture.sqlite", rows=20)
        self.church = self.root / "sample.sqlite"
        build_church(self.church)
        self.mark = self.root / "in-flight"

    def start(self, tmp: str, *, hold_s: float | None = None) -> test_shutdown._Server:
        extra = {"PREACHED_PRIVACY": str(PRIVACY), **CHURCH_ON, **self.ENV}
        base_env = test_shutdown._env
        setup = ""
        if hold_s is not None:
            setup = f"HOLD_S = {hold_s}\nos.environ['MARK'] = {str(self.mark)!r}\n" + HOLD_CHURCH
        args = ["--index", str(self.index), "--bm25-only", "--church-index", str(self.church), "--church-library", "sample"]
        with patch.object(test_shutdown, "_env", side_effect=lambda t: {**base_env(t), **extra}):
            running = test_shutdown._Server(tmp, args, setup=setup)
        self.assertIsNotNone(running.port, "server did not start")
        return running

    def held_side(self, port: int) -> tuple[threading.Thread, dict]:
        """``/api/side`` in a thread; returns once its church check is held."""
        result: dict = {}

        def request() -> None:
            try:
                result["status"], body = raw_get(port, "/api/side?q=approvedtoken&mode=bm25", timeout=60)
                result["body"] = json.loads(body)
            except (OSError, ValueError) as exc:
                result["error"] = repr(exc)

        client = threading.Thread(target=request, daemon=True)
        client.start()
        deadline = time.monotonic() + 20
        while not self.mark.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.mark.exists(), "the church search never started")
        return client, result

    def assert_church_clean(self, err: str) -> None:
        self.assertIn(OPENED, err)
        for bad in ("Traceback", "church side dropped", "church side refused", "church search failed"):
            self.assertNotIn(bad, err, err[-3000:])


class StartupLockServeTests(_ChurchServer):
    """HC1, the real server: started under a writer's lock, it resumes once the lock goes, no restart."""

    def test_started_while_locked_the_church_side_resumes(self) -> None:
        writer = lock(self.church)
        locked = True
        try:
            with tempfile.TemporaryDirectory() as tmp:
                running = self.start(tmp)
                try:
                    status, body = raw_get(running.port, "/api/side?q=approvedtoken&mode=bm25")
                    self.assertEqual(status, 200)
                    self.assertFalse(json.loads(body)["church"]["present"])
                    self.assertEqual(raw_get(running.port, "/api/search?q=approvedtoken&mode=bm25&library=sample")[0], 400)
                    release(writer)
                    locked = False
                    present = False
                    deadline = time.monotonic() + 15
                    while not present and time.monotonic() < deadline:
                        time.sleep(0.25)
                        status, body = raw_get(running.port, "/api/side?q=approvedtoken&mode=bm25")
                        present = status == 200 and json.loads(body)["church"]["present"]
                    self.assertTrue(present, "the church side did not resume")
                    self.assertTrue(json.loads(body)["church"]["results"])
                    status, body = raw_get(running.port, "/api/search?q=approvedtoken&mode=bm25&library=sample")
                    self.assertEqual(status, 200)
                    self.assertTrue(json.loads(body)["results"])
                finally:
                    rc, err = running.stop()
        finally:
            if locked:
                release(writer)
        self.assertEqual(rc, 0, err[-3000:])
        self.assertEqual(err.count(PAUSED_LOCK), 1, err[-3000:])
        self.assertEqual(err.count("church side resumed"), 1, err[-3000:])
        # HD1: the pause is logged after "listening on", which clears the alert.
        self.assertLess(err.index("INFO listening on "), err.index(PAUSED_LOCK))
        self.assertLess(err.index(PAUSED_LOCK), err.index(OPENED))
        self.assertLess(err.index(OPENED), err.index("church side resumed"))
        self.assert_church_clean(err)

    def test_started_in_wal_mode_logs_the_pause_after_listening(self) -> None:
        with closing(sqlite3.connect(self.church)) as writer:
            self.assertEqual(writer.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        with tempfile.TemporaryDirectory() as tmp:
            running = self.start(tmp)
            try:
                status, body = raw_get(running.port, "/api/side?q=approvedtoken&mode=bm25")
                self.assertEqual(status, 200)
                self.assertFalse(json.loads(body)["church"]["present"])
            finally:
                rc, err = running.stop()
        self.assertEqual(rc, 0, err[-3000:])
        paused = "INFO church side paused: sample.sqlite is in WAL journal mode"
        self.assertEqual(err.count(paused), 1, err[-3000:])
        self.assertLess(err.index("INFO listening on "), err.index(paused))


class CapsAndFlushServeTests(_ChurchServer):
    """HC2: #29's per-client request slot and connection cap, with a church search in flight, then SIGTERM."""

    ENV = {
        "PREACHED_MAX_CONNECTIONS": "8",
        "PREACHED_MAX_CLIENT_CONNECTIONS": "2",
        "PREACHED_MAX_CLIENT_REQUESTS": "1",
    }

    def test_caps_refusal_log_flush_and_sigterm_with_a_church_search_in_flight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            running = self.start(tmp, hold_s=3)
            client, result = self.held_side(running.port)
            # The one request slot is the held church search: three more get 503 (busy).
            busy_full = [raw_get_full(running.port, "/api/search?q=grace&mode=bm25") for _ in range(3)]
            busy = [status for status, _headers, _body in busy_full]
            # The held connection plus an idle one fill the per-client cap: the next is refused at accept.
            idle = socket.create_connection(("127.0.0.1", running.port))
            time.sleep(0.2)
            over, over_headers, _body = raw_get_full(running.port, "/api/search?q=grace&mode=bm25")
            idle.close()
            rc, err = running.stop()
            client.join(30)
        self.assertEqual(busy, [503, 503, 503], err[-3000:])
        self.assertEqual(over, 503, err[-3000:])
        # C7: every busy 503 tells the client when to come back.
        for _status, headers, _body in busy_full:
            self.assertEqual(headers.get("retry-after"), "1", headers)
        self.assertEqual(over_headers.get("retry-after"), "1", over_headers)
        self.assertEqual(result.get("status"), 200, (result, err[-3000:]))
        self.assertTrue(result["body"]["church"]["present"])
        self.assertTrue(result["body"]["church"]["results"])
        self.assertEqual(rc, 0, err[-3000:])
        lines = err.splitlines()
        self.assertEqual(sum(line.startswith("WARNING refused busy ") and "flush" not in line for line in lines), 1, err)
        self.assertIn("WARNING refused busy flush suppressed=2", lines)
        self.assertEqual(sum(line.startswith("WARNING refused over-cap ") for line in lines), 1, err)
        # The held search finished after the stop began, then both files closed.
        self.assertLess(lines.index("INFO stopping"), next(i for i, line in enumerate(lines) if "GET /api/side 200" in line))
        self.assert_church_clean(err)


class HealthBucketServeTests(_ChurchServer):
    """HC2: the church side counts against the search bucket, not /healthz's; both flush at SIGTERM."""

    ENV = {
        "PREACHED_RATE_LIMIT": "3",
        "PREACHED_RATE_WINDOW_S": "60",
        "PREACHED_HEALTH_RATE_LIMIT": "2",
    }

    def test_health_has_its_own_bucket_with_the_church_side_on(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            running = self.start(tmp)
            port = running.port
            church = raw_get(port, "/api/search?q=approvedtoken&mode=bm25&library=sample")
            side = raw_get(port, "/api/side?q=approvedtoken&mode=bm25")
            classic = raw_get(port, "/api/search?q=grace&mode=bm25")
            limited_full = [raw_get_full(port, "/api/search?q=approvedtoken&mode=bm25&library=sample") for _ in range(3)]
            limited = [status for status, _headers, _body in limited_full]
            health_full = [raw_get_full(port, "/healthz") for _ in range(3)]
            health = [(status, body) for status, _headers, body in health_full]
            rc, err = running.stop()
        self.assertEqual((church[0], side[0], classic[0]), (200, 200, 200), err[-3000:])
        self.assertTrue(json.loads(church[1])["results"])
        self.assertTrue(json.loads(side[1])["church"]["results"])
        self.assertEqual(limited, [429, 429, 429])
        # C7: the 429 carries Retry-After, the search bucket's and the health bucket's.
        for _status, headers, _body in limited_full + health_full[2:]:
            self.assertRegex(headers.get("retry-after", ""), r"^[1-9][0-9]*$", headers)
        # The search bucket is empty; /healthz still answers from its own, then hits its own limit.
        self.assertEqual([status for status, _ in health], [200, 200, 429])
        self.assertIsNone(json.loads(health[0][1])["church"])
        self.assertEqual(rc, 0, err[-3000:])
        lines = err.splitlines()
        self.assertEqual(sum(line.startswith("WARNING refused 429-client ") and "flush" not in line for line in lines), 1)
        self.assertIn("WARNING refused 429-client flush suppressed=2", lines)
        self.assertEqual(sum(line.startswith("WARNING refused 429-health ") for line in lines), 1)
        self.assert_church_clean(err)


class GlobalRateServeTests(_ChurchServer):
    """C8: the global rate caps, filled by several source addresses (127.0.0.2 and up), church side on."""

    ENV = {
        "PREACHED_RATE_LIMIT": "100",
        "PREACHED_GLOBAL_RATE_LIMIT": "3",
        "PREACHED_HEALTH_RATE_LIMIT": "100",
        "PREACHED_HEALTH_GLOBAL_RATE_LIMIT": "2",
        "PREACHED_RATE_WINDOW_S": "60",
    }

    def test_the_global_and_health_global_caps_hold_across_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            running = self.start(tmp)
            port = running.port
            paths = ["/api/search?q=approvedtoken&mode=bm25&library=sample", "/api/side?q=approvedtoken&mode=bm25", "/api/search?q=grace&mode=bm25"]
            allowed = [raw_get_full(port, path, source=f"127.0.0.{n}") for n, path in zip((2, 3, 4), paths)]
            over = raw_get_full(port, paths[0], source="127.0.0.5")
            health = [raw_get_full(port, "/healthz", source=f"127.0.0.{n}") for n in (6, 7, 8)]
            rc, err = running.stop()
        self.assertEqual([status for status, _h, _b in allowed], [200, 200, 200], err[-3000:])
        self.assertEqual(over[0], 429)
        self.assertRegex(over[1].get("retry-after", ""), r"^[1-9][0-9]*$", over[1])
        self.assertEqual([status for status, _h, _b in health], [200, 200, 429])
        self.assertRegex(health[2][1].get("retry-after", ""), r"^[1-9][0-9]*$", health[2][1])
        self.assertEqual(rc, 0, err[-3000:])
        self.assertEqual(sum(line.startswith("WARNING refused 429-global ") for line in err.splitlines()), 1, err)
        self.assertEqual(sum(line.startswith("WARNING refused 429-health-global ") for line in err.splitlines()), 1, err)
        self.assert_church_clean(err)


class ConnectionCapAndReserveServeTests(_ChurchServer):
    """C8: the global connection cap and the /healthz reserve, filled from several source addresses."""

    ENV = {
        "PREACHED_MAX_CONNECTIONS": "2",
        "PREACHED_MAX_CLIENT_CONNECTIONS": "4",
        "PREACHED_MAX_CLIENT_REQUESTS": "4",
        "PREACHED_HEALTH_RESERVED_CONNECTIONS": "1",
    }

    def test_the_cap_is_global_and_the_reserve_serves_only_healthz(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            running = self.start(tmp, hold_s=3)
            port = running.port
            holders = []
            for n in (2, 3):  # two church searches from two sources fill the two connections
                sock = socket.create_connection(("127.0.0.1", port), timeout=30, source_address=(f"127.0.0.{n}", 0))
                sock.sendall(b"GET /api/side?q=approvedtoken&mode=bm25 HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
                holders.append(sock)
            deadline = time.monotonic() + 20
            while not self.mark.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(self.mark.exists(), "the church search never started")
            time.sleep(0.5)  # the second connection is accepted, queued behind the first
            search = raw_get_full(port, "/api/search?q=grace&mode=bm25", source="127.0.0.4")
            health = raw_get_full(port, "/healthz", source="127.0.0.5")
            for sock in holders:
                sock.close()
            rc, err = running.stop()
        self.assertEqual(search[0], 503, err[-3000:])
        self.assertEqual(search[1].get("retry-after"), "1", search[1])
        self.assertEqual(health[0], 200, err[-3000:])
        self.assertEqual(rc, 0, err[-3000:])


class ReserveUpperBoundServeTests(_ChurchServer):
    """SF2: the /healthz reserve admits exactly ``PREACHED_HEALTH_RESERVED_CONNECTIONS``, no more."""

    ENV = ConnectionCapAndReserveServeTests.ENV

    def test_a_second_over_cap_connection_is_refused_while_the_reserve_is_held(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            running = self.start(tmp, hold_s=3)
            port = running.port
            socks = []
            for n in (2, 3):  # fill the two connections
                sock = socket.create_connection(("127.0.0.1", port), timeout=30, source_address=(f"127.0.0.{n}", 0))
                sock.sendall(b"GET /api/side?q=approvedtoken&mode=bm25 HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
                socks.append(sock)
            deadline = time.monotonic() + 20
            while not self.mark.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(self.mark.exists(), "the church search never started")
            time.sleep(0.5)
            # The one reserved connection, held open and idle.
            reserved = socket.create_connection(("127.0.0.1", port), timeout=30, source_address=("127.0.0.4", 0))
            socks.append(reserved)
            time.sleep(0.5)
            second = raw_get_full(port, "/healthz", source="127.0.0.5")
            for sock in socks:
                sock.close()
            rc, err = running.stop()
        self.assertEqual(second[0], 503, err[-3000:])
        self.assertEqual(rc, 0, err[-3000:])


class ChurchClosedAtShutdownTests(unittest.TestCase):
    """S3c: the stop path closes the church connection, then returns (exit 0).

    No signal is sent here: ``_STOP["requested"]`` stands in for a SIGTERM that
    arrived before serving. The real signalled child is in the serve tests."""

    def test_the_church_connection_is_closed_at_shutdown(self) -> None:
        class Conn:
            closed = 0

            def close(self) -> None:
                self.closed += 1

        class Server:
            drained = False

            def drain(self):
                return []

            def server_close(self) -> None:
                pass

        app = type("A", (), {})()
        app.church_connection = Conn()
        app.close_embedder = lambda: None
        classic = Conn()
        server._STOP["requested"] = True  # nothing is served; go straight to the stop
        self.addCleanup(server._STOP.update, {"requested": False, "stopping": False, "server": None})
        server.serve_until_stopped(Server(), app, classic)
        self.assertEqual((classic.closed, app.church_connection.closed), (1, 1))

    def test_not_closed_while_a_handler_is_still_running(self) -> None:
        class Conn:
            closed = 0

            def close(self) -> None:
                self.closed += 1

        class Server:
            refusals = None

            def drain(self):
                return [object()]

        app = type("A", (), {})()
        app.church_connection = Conn()
        server._STOP["requested"] = True
        self.addCleanup(server._STOP.update, {"requested": False, "stopping": False, "server": None})
        with self.assertRaises(SystemExit):
            server.serve_until_stopped(Server(), app, Conn())
        self.assertEqual(app.church_connection.closed, 0)


class StuckChurchServeTests(_ChurchServer):
    """HC2, the stuck path: a church search held past the drain bound exits 1, flushes, leaves both files open."""

    ENV = {"PREACHED_MAX_CLIENT_REQUESTS": "1"}

    def test_a_stuck_church_search_exits_one_and_flushes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            running = self.start(tmp, hold_s=server.DRAIN_TIMEOUT_S + 3)
            client, _result = self.held_side(running.port)
            busy = [raw_get(running.port, "/api/search?q=grace&mode=bm25")[0] for _ in range(2)]
            running.proc.send_signal(test_shutdown.signal.SIGTERM)
            try:
                rc = running.proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                running.proc.kill()
                running.proc.wait()
                rc = "hang"
            running._errt.join(10)
            running._out.join(10)
            running.proc.stdout.close()
            running.proc.stderr.close()
            err = "".join(running._err)
            client.join(15)
        self.assertEqual(busy, [503, 503])
        self.assertEqual(rc, 1, err[-3000:])
        self.assertIn("handler thread(s) still running", err)
        self.assertIn("index left open", err)
        lines = err.splitlines()
        self.assertIn("WARNING refused busy flush suppressed=1", lines)
        # Logged before the stuck handler finished, as #29 requires.
        self.assertLess(lines.index("WARNING refused busy flush suppressed=1"),
                        next(i for i, line in enumerate(lines) if "GET /api/side 200" in line))
        # The held church search woke to an open church file and completed.
        self.assertIn("GET /api/side 200", err)
        self.assert_church_clean(err)


class LoadedChurchSigtermTests(_ChurchServer):
    """SIGTERM under load with the church side on: 16 clients on /api/side and the church slug.

    Runs: PREACHED_SHUTDOWN_RUNS (default 3), as test_shutdown.
    """

    def test_sigterm_under_church_load_exits_zero(self) -> None:
        failures = []
        served = 0
        for run in range(test_shutdown.RUNS):
            with tempfile.TemporaryDirectory() as tmp:
                running = self.start(tmp)
                stop, ok = threading.Event(), []

                def hammer(n: int) -> None:
                    paths = ("/api/side?q=approvedtoken+grace&mode=bm25", "/api/search?q=approvedtoken&mode=bm25&library=sample")
                    while not stop.is_set():
                        try:
                            status, _body = raw_get(running.port, paths[n % 2], timeout=10)
                            if status == 200:
                                ok.append(1)
                        except OSError:
                            pass

                clients = [threading.Thread(target=hammer, args=(n,), daemon=True) for n in range(test_shutdown.CLIENTS)]
                for thread in clients:
                    thread.start()
                deadline = time.monotonic() + 30
                while len(ok) < test_shutdown.CLIENTS and time.monotonic() < deadline:
                    time.sleep(0.02)
                rc, err = running.stop()
                stop.set()
                for thread in clients:
                    thread.join(15)
                served += len(ok)
                bad = [word for word in ("Traceback", "church side dropped", "church side refused", "church search failed")
                       if word in err]
                leaked = list(Path(tmp).glob("preached-pycache-*"))
                if rc != 0 or bad or leaked or OPENED not in err or len(ok) < test_shutdown.CLIENTS:
                    failures.append((run, rc, len(ok), bad, err[-800:]))
        self.assertEqual(failures, [], f"{len(failures)}/{test_shutdown.RUNS} runs failed")
        self.assertGreater(served, 0)


if __name__ == "__main__":
    unittest.main()
