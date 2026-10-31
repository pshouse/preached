"""PR #37 CTO round 2: the church side's directory chain, fd-inode check,
non-blocking header read, writer-lock pause and alert lines.

Every church file here is a synthetic fixture. No real church data is used.
"""

from __future__ import annotations

import os
import sqlite3
import stat
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
from app.server import STATIC_DIR, App, Searcher  # noqa: E402
from preached.library import (  # noqa: E402
    ChurchRefused,
    _ancestor_problem,
    church_file_problem,
    church_path_problem,
    open_church_readonly,
    wal_mode,
)
from test_church_wire import CHURCH_ON, PRIVACY, build_church, church_app  # noqa: E402
from test_side import FIXTURE_FP, build_library, classic_rows, encode_fixture, reopen  # noqa: E402

ATTACKER = "attackercontent"
ABOVE = "above the church file is group- or world-writable"


def build_attacker(path: Path) -> None:
    """A church-shaped file whose only passage is the attacker's, marked approved."""
    build_church(path)
    with closing(sqlite3.connect(path)) as writer:
        writer.execute("UPDATE chunks SET text = ? WHERE chunk_id = 'c-approved'", (f"{ATTACKER} approvedtoken",))
        writer.commit()


def texts(connection: sqlite3.Connection) -> str:
    return " ".join(row[0] for row in connection.execute("SELECT text FROM chunks"))


class _Root(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.wesley = self.root / "wesley.sqlite"
        build_library(self.wesley, *classic_rows())
        for target in (patch.dict(os.environ, {"PREACHED_PRIVACY": str(PRIVACY), **CHURCH_ON}),):
            target.start()
            self.addCleanup(target.stop)

    def open_dir(self, name: str = "open") -> Path:
        """A directory every local user can write (the CTO's <0777 dir>)."""
        shared = self.root / name
        shared.mkdir()
        os.chmod(shared, 0o777)
        self.addCleanup(os.chmod, shared, 0o700)
        return shared


class ParentDirectorySwapTests(_Root):
    """MF2: every directory above the church file, on the name and the real path."""

    def probe(self) -> tuple[Path, Path]:
        """``<0777 dir>/sub/church.sqlite`` and an attacker's ``evil/church.sqlite`` beside ``sub``."""
        shared = self.open_dir()
        (shared / "sub").mkdir()
        church = shared / "sub" / "church.sqlite"
        build_church(church)
        (shared / "evil").mkdir()
        build_attacker(shared / "evil" / "church.sqlite")
        return shared, church

    def test_the_cto_probe_is_refused_before_any_connect(self) -> None:
        shared, church = self.probe()
        real_open = library.open_readonly
        swapped = []

        def swap_around_connect(path, **kwargs):
            # The probe: rename sub away, put the attacker's directory there,
            # connect, and put sub back so every later name check passes.
            os.rename(shared / "sub", shared / "sub-real")
            os.rename(shared / "evil", shared / "sub")
            try:
                swapped.append(True)
                return real_open(path, **kwargs)
            finally:
                os.rename(shared / "sub", shared / "evil")
                os.rename(shared / "sub-real", shared / "sub")

        with patch.object(library, "open_readonly", side_effect=swap_around_connect):
            with self.assertRaises(ChurchRefused) as caught:
                open_church_readonly(church, classic=self.wesley)
        self.assertEqual(swapped, [])
        self.assertIn(f"directory {shared} {ABOVE} (mode 777)", str(caught.exception))
        self.assertNotIn(ATTACKER, str(caught.exception))
        with self.assertLogs(level="ERROR") as logs:
            self.assertIsNone(server.open_church(church, slug=None, classic_library="wesley", classic_index=self.wesley))
        self.assertEqual(len(logs.output), 1)
        self.assertIn(f"ERROR:root:church side refused: directory {shared} {ABOVE}", logs.output[0])

    def test_group_writable_grandparent_is_refused_too(self) -> None:
        upper = self.root / "upper"
        (upper / "sub").mkdir(parents=True)
        church = upper / "sub" / "church.sqlite"
        build_church(church)
        os.chmod(upper, 0o775)
        self.addCleanup(os.chmod, upper, 0o700)
        self.assertIn(f"directory {upper} {ABOVE} (mode 775)", church_path_problem(church) or "")

    def test_a_safe_chain_opens(self) -> None:
        (self.root / "a" / "b").mkdir(parents=True)
        church = self.root / "a" / "b" / "church.sqlite"
        build_church(church)
        self.assertIsNone(church_path_problem(church))
        connection, _identity = open_church_readonly(church, classic=self.wesley)
        connection.close()

    def test_the_real_path_is_walked_as_well_as_the_name(self) -> None:
        # The name's own chain is safe; only its real chain passes through 0777.
        shared, church = self.probe()
        index = self.root / "index"
        index.mkdir()
        os.symlink(shared / "sub", index / "via")
        given = index / "via" / "church.sqlite"
        problem = church_path_problem(given) or ""
        self.assertIn(f"directory {shared} {ABOVE}", problem)

    def test_an_ancestor_owned_by_another_user_is_refused(self) -> None:
        (self.root / "a").mkdir()
        church = self.root / "a" / "church.sqlite"
        build_church(church)
        real_lstat = os.lstat

        def lstat(target, *args, **kwargs):
            st = real_lstat(target, *args, **kwargs)
            if Path(target) == self.root:
                values = list(st)
                values[4] = st.st_uid + 4242
                return os.stat_result(values)
            return st

        with patch("preached.library.os.lstat", side_effect=lstat):
            self.assertIn(f"directory {self.root} above the church file is owned by uid", church_path_problem(church) or "")

    def lstat_as(self, overrides: dict[Path, dict[int, int]]):
        """``os.lstat`` with some fields replaced (index 0 st_mode, 4 st_uid) for some paths."""
        real_lstat = os.lstat

        def lstat(target, *args, **kwargs):
            st = real_lstat(target, *args, **kwargs)
            fields = overrides.get(Path(target))
            if fields:
                values = list(st)
                for index, value in fields.items():
                    values[index] = value
                return os.stat_result(values)
            return st

        return patch("preached.library.os.lstat", side_effect=lstat)

    def test_a_root_owned_sticky_directory_is_allowed_only_when_the_next_component_is_ours(self) -> None:
        # /tmp's shape, simulated: this sandbox's /tmp is not root-owned or sticky.
        sticky = self.root / "sticky"
        (sticky / "mine").mkdir(parents=True)
        church = sticky / "mine" / "church.sqlite"
        build_church(church)
        os.chmod(sticky, 0o1777)
        self.addCleanup(os.chmod, sticky, 0o700)
        root_owned = {4: 0}
        with self.lstat_as({sticky: root_owned}):
            self.assertIsNone(_ancestor_problem(church))
        with self.lstat_as({sticky: root_owned, sticky / "mine": {4: os.geteuid() + 4242}}):
            # The next component is not ours: the sticky exception does not apply.
            self.assertIn(f"directory {sticky} {ABOVE} (mode 1777)", _ancestor_problem(church) or "")
        # Sticky but not root-owned (ours): refused.
        self.assertIn(f"directory {sticky} {ABOVE} (mode 1777)", _ancestor_problem(church) or "")
        # Root-owned but not sticky: refused.
        os.chmod(sticky, 0o777)
        with self.lstat_as({sticky: root_owned}):
            self.assertIn(f"directory {sticky} {ABOVE} (mode 777)", _ancestor_problem(church) or "")

    def test_sticky_next_component_owned_by_another_user_is_refused(self) -> None:
        # The owner rule is relaxed for the component after the sticky
        # directory, so only the sticky rule can refuse it.
        sticky = self.root / "sticky"
        (sticky / "theirs").mkdir(parents=True)
        church = sticky / "theirs" / "church.sqlite"
        build_church(church)
        other = os.geteuid() + 4242
        real_lstat = os.lstat

        def lstat(target, *args, **kwargs):
            st = real_lstat(target, *args, **kwargs)
            values = list(st)
            if Path(target) == sticky:
                values[0] = stat.S_IFDIR | 0o1777
                values[4] = 0
            elif Path(target) == sticky / "theirs":
                values[4] = other
            return os.stat_result(values)

        with patch("preached.library.os.lstat", side_effect=lstat):
            problem = _ancestor_problem(church) or ""
        self.assertIn(f"directory {sticky} {ABOVE} (mode 1777)", problem)

    def test_the_per_request_check_sees_a_directory_made_writable_after_start(self) -> None:
        (self.root / "a" / "b").mkdir(parents=True)
        church = self.root / "a" / "b" / "church.sqlite"
        build_church(church)
        connection, identity = open_church_readonly(church, classic=self.wesley)
        self.addCleanup(connection.close)
        self.assertIsNone(church_file_problem(connection, church, identity))
        os.chmod(self.root / "a", 0o777)
        self.addCleanup(os.chmod, self.root / "a", 0o700)
        problem = church_file_problem(connection, church, identity) or ""
        self.assertIn(f"directory {self.root / 'a'} {ABOVE}", problem)

    def test_sqlites_descriptor_must_be_the_checked_inode(self) -> None:
        # A swap the directory checks cannot see (here the test does it, in
        # its own directory): the name is swapped only around the connect,
        # so every check by name before and after passes.
        (self.root / "safe" / "sub").mkdir(parents=True)
        (self.root / "safe" / "evil").mkdir()
        church = self.root / "safe" / "sub" / "church.sqlite"
        build_church(church)
        build_attacker(self.root / "safe" / "evil" / "church.sqlite")
        real_open = library.open_readonly
        safe = self.root / "safe"

        def swap_around_connect(path, **kwargs):
            os.rename(safe / "sub", safe / "sub-real")
            os.rename(safe / "evil", safe / "sub")
            try:
                return real_open(path, **kwargs)
            finally:
                os.rename(safe / "sub", safe / "evil")
                os.rename(safe / "sub-real", safe / "sub")

        with patch.object(library, "open_readonly", side_effect=swap_around_connect):
            with self.assertRaises(ChurchRefused) as caught:
                open_church_readonly(church, classic=self.wesley)
        self.assertIn("church.sqlite is not the file SQLite opened (the name changed)", str(caught.exception))
        # Unswapped, the same file opens and holds no attacker text.
        connection, _identity = open_church_readonly(church, classic=self.wesley)
        self.addCleanup(connection.close)
        self.assertNotIn(ATTACKER, texts(connection))


class FifoTests(_Root):
    """B: the header read never blocks, follows no symlink, reads only the checked regular file."""

    def fifo(self) -> Path:
        fifo = self.root / "fifo.sqlite"
        os.mkfifo(fifo, 0o600)
        return fifo

    def bounded(self, call) -> list:
        """Run ``call`` in a thread; fail if it is still running after 5 s."""
        result: list = []
        worker = threading.Thread(target=lambda: result.append(call()), daemon=True)
        worker.start()
        worker.join(5)
        if worker.is_alive():
            # Unblock a reader stuck in open() so the thread can end.
            for path in self.root.glob("*fifo*"):
                fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
                os.close(fd)
            worker.join(5)
            self.fail("blocked on the FIFO for 5 s")
        return result

    def test_wal_mode_on_a_fifo_returns_none_without_blocking(self) -> None:
        fifo = self.fifo()
        self.assertEqual(self.bounded(lambda: wal_mode(fifo)), [None])

    def test_wal_mode_reads_only_the_expected_regular_file(self) -> None:
        church = self.root / "church.sqlite"
        build_church(church)
        st = os.stat(church)
        self.assertIs(wal_mode(church, (st.st_dev, st.st_ino)), False)
        self.assertIsNone(wal_mode(church, (st.st_dev, st.st_ino + 1)))
        link = self.root / "link.sqlite"
        os.symlink(church, link)
        self.assertIsNone(wal_mode(link))  # O_NOFOLLOW

    def test_a_fifo_swapped_in_after_the_name_check_is_refused_without_blocking(self) -> None:
        church = self.root / "church.sqlite"
        build_church(church)
        connection, identity = open_church_readonly(church, classic=self.wesley)
        self.addCleanup(connection.close)
        church.unlink()
        os.mkfifo(church, 0o600)
        self.addCleanup(church.unlink)
        # The swap lands right after the identity check: only the header read sees it.
        with patch("preached.library._church_identity", return_value=identity), patch(
            "preached.library._protection", return_value=None
        ):
            (problem,) = self.bounded(lambda: church_file_problem(connection, church, identity))
        self.assertEqual(problem, "church.sqlite cannot be read as the regular file that was opened; refused")

    def test_the_app_drops_the_church_side_without_stalling(self) -> None:
        church = self.root / "church.sqlite"
        build_church(church)
        app = church_app(self.wesley, church, check=None)
        connection, identity = open_church_readonly(church, classic=self.wesley)
        self.addCleanup(connection.close)
        app._church_check = lambda conn: church_file_problem(conn, church, identity)
        church.unlink()
        os.mkfifo(church, 0o600)
        self.addCleanup(church.unlink)
        with patch("preached.library._church_identity", return_value=identity), patch(
            "preached.library._protection", return_value=None
        ), self.assertLogs(level="ERROR") as logs:
            (side,) = self.bounded(lambda: app.side("approvedtoken", 5, "bm25"))
        self.assertFalse(side["church"]["present"])
        self.assertTrue(side["classic"]["results"] is not None)
        self.assertIn("ERROR:root:church side dropped: church.sqlite cannot be read as the regular file", logs.output[0])


class WriterLockTests(_Root):
    """D and F: a writer's lock pauses the church side at once, logged at its start and end."""

    def setUp(self) -> None:
        super().setUp()
        self.church = self.root / "sample.sqlite"
        build_church(self.church)
        connection, identity = open_church_readonly(self.church, classic=self.wesley)
        self.church_connection = connection
        self.identity = identity
        classic = reopen(self.wesley)
        self.addCleanup(classic.close)
        self.addCleanup(connection.close)
        self.classic = classic

    def app(self, check) -> App:
        return App(
            connection=self.classic,
            searcher=Searcher(self.classic, model="fixture", fingerprint=FIXTURE_FP),
            encode=encode_fixture,
            fallback_note=None,
            model_name="fixture",
            hosts={"127.0.0.1"},
            static_dir=STATIC_DIR,
            library="wesley",
            floor=0.5,
            church_connection=self.church_connection,
            church_searcher=Searcher(self.church_connection, model="fixture", fingerprint=FIXTURE_FP),
            church_library="sample",
            church_check=check,
        )

    def locked(self) -> sqlite3.Connection:
        writer = sqlite3.connect(self.church, isolation_level=None)
        writer.execute("BEGIN EXCLUSIVE")
        return writer

    def assert_paused_then_resumed(self, app: App) -> None:
        self.assertEqual(self.church_connection.execute("PRAGMA busy_timeout").fetchone()[0], 0)
        writer = self.locked()
        try:
            with self.assertLogs(level="INFO") as logs:
                for _ in range(20):
                    started = time.perf_counter()
                    side = app.side("approvedtoken", 5, "bm25")
                    self.assertLess(time.perf_counter() - started, 1.0)  # was 5.07 s at busy_timeout 5000
                    self.assertFalse(side["church"]["present"])
                    self.assertTrue(side["classic"] is not None)
        finally:
            writer.execute("ROLLBACK")
            writer.close()
        # F: one line for the whole pause, not one per request.
        self.assertEqual(len(logs.output), 1, logs.output)
        self.assertTrue(logs.output[0].startswith("INFO:root:church side paused: the church file is locked by a writer"))
        self.assertEqual(app.church_library, "sample")  # paused, not dropped
        with self.assertLogs(level="INFO") as logs:
            self.assertTrue(app.side("approvedtoken", 5, "bm25")["church"]["results"])
            self.assertTrue(app.side("approvedtoken", 5, "bm25")["church"]["results"])
        self.assertEqual(logs.output, ["INFO:root:church side resumed"])

    def test_a_lock_seen_by_the_check_is_a_pause(self) -> None:
        church, identity = self.church, self.identity
        self.assert_paused_then_resumed(self.app(lambda conn: church_file_problem(conn, church, identity)))

    def test_a_lock_taken_after_the_check_is_a_pause_too(self) -> None:
        # The check passes; the search's own read finds the lock.
        self.assert_paused_then_resumed(self.app(lambda conn: None))


class AlertStringTests(_Root):
    """E: startup says refused, a mid-run drop says dropped, in the server's log format."""

    def test_refused_at_startup_and_dropped_while_running(self) -> None:
        church = self.root / "sample.sqlite"
        build_church(church)
        os.chmod(church, 0o666)
        with self.assertLogs(level="ERROR") as logs:
            self.assertIsNone(server.open_church(church, slug=None, classic_library="wesley", classic_index=self.wesley))
        self.assertEqual(len(logs.output), 1)
        self.assertTrue(logs.output[0].startswith("ERROR:root:church side refused: "), logs.output)
        os.chmod(church, 0o644)
        with self.assertLogs(level="INFO"):
            connection, slug, check = server.open_church(
                church, slug=None, classic_library="wesley", classic_index=self.wesley
            )
        self.addCleanup(connection.close)
        app = church_app(self.wesley, church, check=None)
        app._church_check = check
        self.assertTrue(app.side("approvedtoken", 5, "bm25")["church"]["results"])
        os.chmod(church, 0o666)
        with self.assertLogs(level="ERROR") as logs:
            app.side("approvedtoken", 5, "bm25")
            app.side("approvedtoken", 5, "bm25")  # gone now: nothing more is logged
        self.assertEqual(len(logs.output), 1)
        self.assertTrue(logs.output[0].startswith("ERROR:root:church side dropped: "), logs.output)
        self.assertNotIn("refused:", logs.output[0])


if __name__ == "__main__":
    unittest.main()
