"""The suite fails when a run writes under PREACHED_CACHE or /cache.

Importing this module calls ``cache_guard.install``. Every other test
module does the same with one import line, so a ``discover -p`` pattern
that does not load this file, ``python -m unittest test_x`` from inside
``tests/``, and ``python tests/test_x.py`` are armed too. ``install`` is
idempotent per process: ``tests.cache_guard`` and top-level ``cache_guard``
are one module object.
"""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import ast
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

try:
    from . import cache_guard
except ImportError:  # discover -s tests loads this file as a top-level module
    import cache_guard

ROOT = Path(__file__).resolve().parents[1]


def _temp_root() -> Path:
    """A directory under the system temp dir, outside /cache and PREACHED_CACHE."""
    root = Path(tempfile.mkdtemp(prefix="preached-guard-")).resolve()
    temp = Path(tempfile.gettempdir()).resolve()
    if not root.is_relative_to(temp):
        raise AssertionError(f"refusing to use a fixture outside the temp dir: {root}")
    refused = []
    if Path("/cache").is_dir():
        refused.append(Path("/cache").resolve())
    raw = os.environ.get("PREACHED_CACHE")
    if raw:
        refused.append(Path(raw).resolve())
    for watched in refused:
        if root == watched or root.is_relative_to(watched):
            raise AssertionError(f"refusing to use a fixture inside {watched}: {root}")
    return root


def _assert_under_temp(path: Path) -> Path:
    """Resolve ``path`` and refuse to touch it unless it stays under the temp dir."""
    resolved = path.resolve()
    temp = Path(tempfile.gettempdir()).resolve()
    if not resolved.is_relative_to(temp):
        raise AssertionError(f"refusing to touch a path outside the temp dir: {resolved}")
    cache = Path("/cache")
    if cache.exists():
        cache_resolved = cache.resolve()
        if resolved == cache_resolved or resolved.is_relative_to(cache_resolved):
            raise AssertionError(f"refusing to touch the real cache: {resolved}")
    return resolved


def _remove_temp_tree(path: Path) -> None:
    resolved = _assert_under_temp(path)
    if not resolved.exists():
        return
    import shutil

    shutil.rmtree(resolved)


class CacheGuardTests(unittest.TestCase):
    def test_snapshot_skips_excluded_dirs_shm_and_snap_noise(self) -> None:
        root = _temp_root()
        try:
            for name in ("uv", "uv-python", "venvs", "xdg", "demo-kill", "models", "index"):
                (root / name).mkdir()
            (root / "uv" / "pkg").write_bytes(b"u")
            (root / "uv-python" / "py").write_bytes(b"p")
            (root / "venvs" / "lib").write_bytes(b"v")
            (root / "xdg" / "deno").write_bytes(b"d")
            (root / "demo-kill" / "KILL").write_bytes(b"k")
            (root / "models" / "graph").write_bytes(b"g")
            (root / "index" / "wesley.sqlite").write_bytes(b"s")
            (root / "index" / "wesley.sqlite-shm").write_bytes(b"h")
            (root / "index" / "wesley.sqlite-wal").write_bytes(b"w")
            (root / "index" / "wesley.sqlite.box-store-snap-1").write_bytes(b"n")
            (root / "models" / "graph").chmod(0o644)
            listing = cache_guard.snapshot_tree(root)
        finally:
            resolved = root.resolve()
            if not resolved.is_relative_to(Path(tempfile.gettempdir()).resolve()):
                raise AssertionError(f"refusing to remove {resolved}")
            import shutil

            shutil.rmtree(resolved)
        self.assertEqual(
            set(listing),
            {".", "models", "models/graph", "index", "index/wesley.sqlite", "index/wesley.sqlite-wal"},
        )
        self.assertEqual(listing["models/graph"].size, 1)
        self.assertTrue(stat.S_ISDIR(listing["."].mode))
        self.assertNotIn("index/wesley.sqlite-shm", listing)

    def test_diff_names_added_removed_and_changed_files(self) -> None:
        before = {
            "keep": cache_guard.Entry(1, 0o100644, 1, 10, 10),
            "gone": cache_guard.Entry(2, 0o100644, 2, 20, 20),
        }
        after = {
            "keep": cache_guard.Entry(1, 0o100644, 3, 11, 12),
            "new": cache_guard.Entry(4, 0o100644, 4, 30, 30),
        }
        text = "\n".join(cache_guard.diff_lines("PREACHED_CACHE=/cache", before, after))
        self.assertIn("PREACHED_CACHE=/cache changed keep", text)
        self.assertIn("size=1->3", text)
        self.assertIn("mtime_ns=10->11", text)
        self.assertIn("ctime_ns=10->12", text)
        self.assertIn("PREACHED_CACHE=/cache removed gone", text)
        self.assertIn("size=2", text)
        self.assertIn("PREACHED_CACHE=/cache added new", text)
        self.assertIn("size=4", text)

    def test_directory_timestamps_are_ignored_and_file_ctime_is_not(self) -> None:
        directory = cache_guard.Entry(5, 0o40755, 60, 10, 10)
        touched = cache_guard.Entry(5, 0o40755, 100, 99, 99)
        self.assertEqual(cache_guard.diff_lines("fake", {"index": directory}, {"index": touched}), [])
        file_old = cache_guard.Entry(7, 0o100644, 4, 10, 10)
        file_new = cache_guard.Entry(7, 0o100644, 4, 10, 11)
        lines = cache_guard.diff_lines(
            "fake",
            {"index/wesley.sqlite": file_old},
            {"index/wesley.sqlite": file_new},
        )
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("ctime_ns=10->11", lines[0])

    def test_classify_write_ignores_temp_files_shm_and_snap_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.assertTrue(root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
            roots = [(f"PREACHED_CACHE={root}", root)]
            graph = root / "models" / "model.fp32.onnx"
            self.assertEqual(
                cache_guard.classify_write(graph, roots),
                f"PREACHED_CACHE={root} write models/model.fp32.onnx",
            )
            wal = root / "index" / "wesley.sqlite-wal"
            self.assertEqual(
                cache_guard.classify_write(wal, roots),
                f"PREACHED_CACHE={root} write index/wesley.sqlite-wal",
            )
            self.assertIsNone(cache_guard.classify_write(root / "uv" / "pkg", roots))
            self.assertIsNone(cache_guard.classify_write(root / "xdg" / "deno" / "cache", roots))
            self.assertIsNone(cache_guard.classify_write(root / "index" / "wesley.sqlite-shm", roots))
            index = root / "index"
            index.mkdir()
            (index / "wesley.sqlite").write_bytes(b"s")
            snap = index / "wesley.sqlite.box-store-snap-3"
            self.assertIsNone(cache_guard.classify_write(snap, roots))
            outside = Path(tempfile.gettempdir()) / "not-a-cache-file"
            self.assertIsNone(cache_guard.classify_write(outside, roots))

    def test_a_write_under_a_watched_cache_is_remembered_after_it_is_removed(self) -> None:
        self.assertIsNotNone(cache_guard.current_run(), "the suite hook is not armed")
        temp_root = Path(tempfile.gettempdir()).resolve()
        with tempfile.TemporaryDirectory(dir=temp_root) as tmp:
            root = Path(tmp).resolve()
            self.assertTrue(root.is_relative_to(temp_root))
            label = cache_guard.push_root(f"fixture-{root.name}", root)
            try:
                with tempfile.TemporaryDirectory(dir=root) as scratch:
                    scratch_path = Path(scratch).resolve()
                    self.assertTrue(scratch_path.is_relative_to(temp_root))
                    victim = scratch_path / "model.fp32.onnx"
                    victim.write_bytes(b"not-the-real-graph")
                self.assertFalse(any(root.rglob("model.fp32.onnx")))
            finally:
                notes = cache_guard.pop_root(label)
        self.assertTrue(any("model.fp32.onnx" in note for note in notes), notes)
        self.assertTrue(all(note.startswith(label + " ") for note in notes))

    def test_builtin_open_under_a_watched_cache_is_remembered_after_it_is_removed(self) -> None:
        """``open()`` is hooked. pathlib writes go through ``io.open`` and would miss this."""
        self.assertIsNotNone(cache_guard.current_run(), "the suite hook is not armed")
        temp_root = Path(tempfile.gettempdir()).resolve()
        with tempfile.TemporaryDirectory(dir=temp_root) as tmp:
            root = Path(tmp).resolve()
            self.assertTrue(root.is_relative_to(temp_root))
            label = cache_guard.push_root(f"fixture-{root.name}", root)
            try:
                with tempfile.TemporaryDirectory(dir=root) as scratch:
                    scratch_path = Path(scratch).resolve()
                    self.assertTrue(scratch_path.is_relative_to(temp_root))
                    victim = scratch_path / "opened.bin"
                    with open(victim, "wb") as handle:
                        handle.write(b"x")
                self.assertFalse(victim.exists())
            finally:
                notes = cache_guard.pop_root(label)
        self.assertTrue(any("opened.bin" in note for note in notes), notes)

    def test_tool_caches_stay_outside_the_real_cache(self) -> None:
        cache_guard.install()
        temp_root = Path(tempfile.gettempdir()).resolve()
        real = Path("/cache").resolve()
        for key in ("XDG_CACHE_HOME", "DENO_DIR"):
            path = Path(os.environ[key]).resolve()
            self.assertTrue(path.is_dir(), path)
            self.assertTrue(path.is_relative_to(temp_root), path)
            self.assertFalse(path == real or path.is_relative_to(real), path)

    def _open_wal_change(self, kind: str) -> None:
        """Insert or update through a connection that stays open. Only the -wal moves."""
        root = _temp_root()
        db = root / "index" / "wesley.sqlite"
        db.parent.mkdir()
        conn = sqlite3.connect(db)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
            conn.execute("INSERT INTO t(v) VALUES ('base')")
            conn.commit()
            before = cache_guard.snapshot_tree(root)
            self.assertIn("index/wesley.sqlite-wal", before)
            if kind == "insert":
                conn.execute("INSERT INTO t(v) VALUES ('d')")
            else:
                conn.execute("UPDATE t SET v = 'd3' WHERE v = 'base'")
            conn.commit()
            after = cache_guard.snapshot_tree(root)
            self.assertEqual(before["index/wesley.sqlite"], after["index/wesley.sqlite"])
            lines = cache_guard.diff_lines("fake", before, after)
        finally:
            conn.close()
            resolved = root.resolve()
            if not resolved.is_relative_to(Path(tempfile.gettempdir()).resolve()):
                raise AssertionError(f"refusing to remove {resolved}")
            import shutil

            shutil.rmtree(resolved)
        self.assertEqual([line.split()[2] for line in lines], ["index/wesley.sqlite-wal"], lines)
        self.assertNotIn("sqlite-shm", "\n".join(lines))

    def test_open_wal_insert_is_caught_while_the_connection_is_open(self) -> None:
        self._open_wal_change("insert")

    def test_open_wal_update_is_caught_while_the_connection_is_open(self) -> None:
        self._open_wal_change("update")

    def test_writable_sqlite_open_under_a_watched_root_is_refused(self) -> None:
        self.assertIsNotNone(cache_guard.current_run(), "the suite hook is not armed")
        root = _temp_root()
        label = f"fixture-{root.name}"
        try:
            db = root / "index" / "wesley.sqlite"
            db.parent.mkdir()
            setup = sqlite3.connect(db)
            setup.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
            setup.execute("INSERT INTO t(v) VALUES ('base')")
            setup.commit()
            setup.close()
            outside = root.parent / f"{root.name}-outside.sqlite"
            self.assertTrue(outside.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()))
            cache_guard.push_root(label, root)
            try:
                with self.assertRaises(sqlite3.OperationalError) as caught:
                    sqlite3.connect(db)
                self.assertIn("cache guard", str(caught.exception))
                with self.assertRaises(sqlite3.OperationalError) as caught_uri:
                    sqlite3.connect(db.resolve().as_uri() + "?mode=rw", uri=True)
                self.assertIn("cache guard", str(caught_uri.exception))
                reader = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
                try:
                    self.assertEqual(reader.execute("SELECT v FROM t").fetchall(), [("base",)])
                finally:
                    reader.close()
                other = sqlite3.connect(outside)
                other.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
                other.close()
            finally:
                notes = cache_guard.pop_root(label)
        finally:
            resolved = root.resolve()
            if not resolved.is_relative_to(Path(tempfile.gettempdir()).resolve()):
                raise AssertionError(f"refusing to remove {resolved}")
            import shutil

            shutil.rmtree(resolved)
            outside = root.parent / f"{root.name}-outside.sqlite"
            if outside.exists():
                _assert_under_temp(outside).unlink()
        # Both opens hit the same path, so the note set keeps one line.
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("index/wesley.sqlite", notes[0])
        self.assertTrue(notes[0].startswith(label + " "), notes)

    def test_sqlite_uri_with_duplicate_or_non_ro_mode_is_refused(self) -> None:
        """One mode parameter whose value is exactly ``ro``. Duplicates are refused."""
        self.assertIsNotNone(cache_guard.current_run(), "the suite hook is not armed")
        root = _temp_root()
        label = f"fixture-{root.name}"
        try:
            db = root / "index" / "wesley.sqlite"
            db.parent.mkdir()
            setup = sqlite3.connect(db)
            setup.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
            setup.execute("INSERT INTO t(v) VALUES ('base')")
            setup.commit()
            setup.close()
            base = db.resolve().as_uri()
            cache_guard.push_root(label, root)
            try:
                refused = (
                    "?mode=ro&mode=rw",
                    "?mode=rw&mode=ro",
                    "?mode=ro&mode=ro",
                    "?mode=RO",
                    "?mode=rwc",
                )
                for query in refused:
                    with self.subTest(query=query):
                        with self.assertRaises(sqlite3.OperationalError) as caught:
                            sqlite3.connect(base + query, uri=True)
                        self.assertIn("cache guard", str(caught.exception))
                reader = sqlite3.connect(base + "?mode=ro", uri=True)
                try:
                    self.assertEqual(reader.execute("SELECT v FROM t").fetchall(), [("base",)])
                finally:
                    reader.close()
                shared = sqlite3.connect(base + "?mode=ro&cache=shared", uri=True)
                try:
                    self.assertEqual(shared.execute("SELECT v FROM t").fetchall(), [("base",)])
                finally:
                    shared.close()
            finally:
                cache_guard.pop_root(label)
        finally:
            _remove_temp_tree(root)

    def test_sqlite_uri_with_immutable_is_refused(self) -> None:
        """``immutable=1`` is refused, including case and percent-encoding variants.

        ``mode=ro`` still reads. ``immutable=0`` and ``immutable=false`` are not
        the flag SQLite turns on. A path outside the watched root is left alone.
        """
        self.assertIsNotNone(cache_guard.current_run(), "the suite hook is not armed")
        root = _temp_root()
        label = f"fixture-{root.name}"
        outside = root.parent / f"{root.name}-outside.sqlite"

        def seed(path: Path) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            setup = sqlite3.connect(path)
            setup.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
            setup.execute("INSERT INTO t(v) VALUES ('base')")
            setup.commit()
            setup.close()

        try:
            db = root / "index" / "wesley.sqlite"
            seed(db)
            _assert_under_temp(outside)
            seed(outside)
            base = db.resolve().as_uri()
            cache_guard.push_root(label, root)
            try:
                refused = (
                    "?mode=ro&immutable=1",
                    "?mode=ro&IMMUTABLE=1",
                    "?mode=ro&Immutable=1",
                    "?mode=ro&immutable=TRUE",
                    "?mode=ro&immutable=%31",
                    "?mode=ro&%69mmutable=1",
                    "?mode=ro&%69%6D%6d%75%74%61%62%6C%65=%31",
                    "?mode=ro&immutable=%74%72%75%65",
                    "?immutable=1&mode=ro",
                    "?mode=ro&immutable=1&immutable=0",
                    "?mode=ro&immutable=01",
                )
                for query in refused:
                    with self.subTest(query=query):
                        conn = None
                        try:
                            with self.assertRaises(sqlite3.OperationalError) as caught:
                                conn = sqlite3.connect(base + query, uri=True)
                            message = str(caught.exception)
                            self.assertIn("cache guard", message)
                            self.assertIn("immutable", message)
                        finally:
                            if conn is not None:
                                conn.close()
                allowed = (
                    "?mode=ro",
                    "?mode=ro&cache=shared",
                    "?mode=ro&immutable=0",
                    "?mode=ro&immutable=false",
                    "?mode=ro&immutable=FALSE",
                    "?mode=ro&immutable=",
                    "?mode=ro&IMMUTABLE=0",
                )
                for query in allowed:
                    with self.subTest(query=query):
                        reader = sqlite3.connect(base + query, uri=True)
                        try:
                            self.assertEqual(reader.execute("SELECT v FROM t").fetchall(), [("base",)])
                        finally:
                            reader.close()
                other = sqlite3.connect(outside.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
                try:
                    self.assertEqual(other.execute("SELECT v FROM t").fetchall(), [("base",)])
                finally:
                    other.close()
            finally:
                cache_guard.pop_root(label)
        finally:
            _remove_temp_tree(root)
            if outside.exists():
                _assert_under_temp(outside).unlink()

    def test_remove_temp_tree_refuses_a_path_outside_the_temp_dir(self) -> None:
        """The temp-dir assert in ``_remove_temp_tree`` runs before rmtree.

        Every other caller passes a temp directory, so deleting the assert
        would leave the suite green and would delete a real path.
        """
        root = _temp_root()
        (root / "marker").write_bytes(b"ok")
        _remove_temp_tree(root)
        self.assertFalse(root.exists())

        outside = Path("/preached-guard-not-under-temp")
        resolved = outside.resolve()
        temp = Path(tempfile.gettempdir()).resolve()
        self.assertFalse(resolved.is_relative_to(temp), resolved)
        self.assertFalse(resolved.exists(), resolved)
        cache = Path("/cache")
        if cache.exists():
            cache_resolved = cache.resolve()
            self.assertFalse(
                resolved == cache_resolved or resolved.is_relative_to(cache_resolved),
                resolved,
            )

        import shutil

        calls: list[str] = []
        real_rmtree = shutil.rmtree

        def record(path, *args, **kwargs):
            calls.append(os.fspath(path))
            raise AssertionError(f"rmtree must not run: {path}")

        shutil.rmtree = record
        try:
            with self.assertRaises(AssertionError) as caught:
                _remove_temp_tree(outside)
            message = str(caught.exception)
            self.assertIn("outside the temp dir", message)
            self.assertNotIn("rmtree must not run", message)
            self.assertEqual(calls, [])
        finally:
            shutil.rmtree = real_rmtree

    def test_same_size_same_mtime_replace_is_caught(self) -> None:
        root = _temp_root()
        try:
            victim = root / "index" / "wesley.sqlite"
            victim.parent.mkdir()
            payload = b"same-size!!"
            victim.write_bytes(payload)
            st = victim.lstat()
            os.utime(victim, ns=(st.st_atime_ns, st.st_mtime_ns))
            before = cache_guard.snapshot_tree(root)
            replacement = root / "replacement"
            replacement.write_bytes(payload)
            os.utime(replacement, ns=(st.st_atime_ns, before["index/wesley.sqlite"].mtime_ns))
            os.replace(replacement, victim)
            after = cache_guard.snapshot_tree(root)
            old, new = before["index/wesley.sqlite"], after["index/wesley.sqlite"]
            self.assertEqual(old.size, new.size)
            self.assertEqual(old.mtime_ns, new.mtime_ns)
            self.assertNotEqual(old.inode, new.inode)
            lines = cache_guard.diff_lines("fake", before, after)
            self.assertTrue(any("changed index/wesley.sqlite " in line for line in lines), lines)
        finally:
            resolved = root.resolve()
            if not resolved.is_relative_to(Path(tempfile.gettempdir()).resolve()):
                raise AssertionError(f"refusing to remove {resolved}")
            import shutil

            shutil.rmtree(resolved)

    def test_new_symlink_is_caught_and_not_followed(self) -> None:
        root = _temp_root()
        try:
            target = root / "models" / "graph"
            target.parent.mkdir()
            target.write_bytes(b"g")
            outside = root.parent / f"{root.name}-secret"
            outside.mkdir()
            (outside / "hidden").write_bytes(b"no")
            before = cache_guard.snapshot_tree(root)
            (root / "models" / "alias").symlink_to("graph")
            (root / "linkdir").symlink_to(outside)
            after = cache_guard.snapshot_tree(root)
            self.assertNotIn("models/alias", before)
            self.assertTrue(stat.S_ISLNK(after["models/alias"].mode))
            self.assertEqual(after["models/alias"].size, len("graph"))
            self.assertTrue(stat.S_ISLNK(after["linkdir"].mode))
            self.assertFalse(any(name.startswith("linkdir/") for name in after))
            lines = cache_guard.diff_lines("fake", before, after)
            self.assertTrue(any("added models/alias " in line for line in lines), lines)
            self.assertTrue(any("added linkdir " in line for line in lines), lines)
        finally:
            resolved = root.resolve()
            temp = Path(tempfile.gettempdir()).resolve()
            if not resolved.is_relative_to(temp):
                raise AssertionError(f"refusing to remove {resolved}")
            import shutil

            shutil.rmtree(resolved)
            secret = root.parent / f"{root.name}-secret"
            if secret.exists():
                self.assertTrue(secret.resolve().is_relative_to(temp))
                shutil.rmtree(secret)

    def test_empty_directory_is_caught(self) -> None:
        root = _temp_root()
        try:
            (root / "models").mkdir()
            before = cache_guard.snapshot_tree(root)
            (root / "models" / "empty").mkdir()
            after = cache_guard.snapshot_tree(root)
            self.assertNotIn("models/empty", before)
            self.assertTrue(stat.S_ISDIR(after["models/empty"].mode))
            lines = cache_guard.diff_lines("fake", before, after)
            self.assertTrue(any("added models/empty " in line for line in lines), lines)
        finally:
            resolved = root.resolve()
            if not resolved.is_relative_to(Path(tempfile.gettempdir()).resolve()):
                raise AssertionError(f"refusing to remove {resolved}")
            import shutil

            shutil.rmtree(resolved)

    def test_chmod_only_change_is_caught(self) -> None:
        root = _temp_root()
        try:
            victim = root / "models" / "graph"
            victim.parent.mkdir()
            victim.write_bytes(b"same")
            before = cache_guard.snapshot_tree(root)
            victim.chmod(before["models/graph"].mode ^ 0o111)
            after = cache_guard.snapshot_tree(root)
            old, new = before["models/graph"], after["models/graph"]
            self.assertEqual(old.size, new.size)
            self.assertEqual(old.mtime_ns, new.mtime_ns)
            self.assertEqual(old.inode, new.inode)
            self.assertNotEqual(old.mode, new.mode)
            lines = cache_guard.diff_lines("fake", before, after)
            self.assertTrue(any("changed models/graph " in line for line in lines), lines)
        finally:
            resolved = root.resolve()
            if not resolved.is_relative_to(Path(tempfile.gettempdir()).resolve()):
                raise AssertionError(f"refusing to remove {resolved}")
            import shutil

            shutil.rmtree(resolved)

    def test_chmod_or_replace_of_a_protected_directory_is_caught(self) -> None:
        """Directory comparison is inode and mode. Timestamps alone are not a change."""
        root = _temp_root()
        try:
            models = root / "models"
            models.mkdir()
            before = cache_guard.snapshot_tree(root)
            os.chmod(models, stat.S_IMODE(before["models"].mode) ^ 0o111)
            after_chmod = cache_guard.snapshot_tree(root)
            self.assertEqual(before["models"].inode, after_chmod["models"].inode)
            self.assertNotEqual(before["models"].mode, after_chmod["models"].mode)
            chmod_lines = cache_guard.diff_lines("fake", before, after_chmod)
            self.assertTrue(any("changed models " in line for line in chmod_lines), chmod_lines)

            protected = root / "index"
            protected.mkdir()
            replacement = root / "index-new"
            replacement.mkdir()
            before_replace = cache_guard.snapshot_tree(root)
            os.chmod(replacement, stat.S_IMODE(before_replace["index"].mode))
            os.replace(replacement, protected)
            after_replace = cache_guard.snapshot_tree(root)
            self.assertNotEqual(before_replace["index"].inode, after_replace["index"].inode)
            self.assertEqual(
                stat.S_IMODE(before_replace["index"].mode),
                stat.S_IMODE(after_replace["index"].mode),
            )
            replace_lines = cache_guard.diff_lines("fake", before_replace, after_replace)
            self.assertTrue(any("changed index " in line for line in replace_lines), replace_lines)
        finally:
            _remove_temp_tree(root)

    def test_box_store_snap_names_are_ignored(self) -> None:
        """Only ``<sibling>.box-store-snap-<digits>`` regular files are noise.

        A directory, a symlink, a file with no sibling, and a name the old
        ``*.box-store-snap-*`` glob would hide are real and stay visible.
        """
        root = _temp_root()
        try:
            index = root / "index"
            index.mkdir()
            (index / "wesley.sqlite").write_bytes(b"s")
            before = cache_guard.snapshot_tree(root)
            noise = index / "wesley.sqlite.box-store-snap-4"
            noise.write_bytes(b"noise")
            orphan = index / "orphan.box-store-snap-4"
            orphan.write_bytes(b"real-file")
            dotted = index / ".box-store-snap-9"
            dotted.write_bytes(b"x")
            note = index / "wesley.sqlite.box-store-snap-note"
            note.write_bytes(b"t")
            as_dir = index / "wesley.sqlite.box-store-snap-8"
            as_dir.mkdir()
            (as_dir / "inside").write_bytes(b"i")
            link = index / "wesley.sqlite.box-store-snap-5"
            link.symlink_to("wesley.sqlite")
            after = cache_guard.snapshot_tree(root)
            blob = "\n".join(cache_guard.diff_lines("fake", before, after))
            self.assertNotIn("index/wesley.sqlite.box-store-snap-4 ", blob)
            self.assertIn("index/orphan.box-store-snap-4 ", blob)
            self.assertIn("index/.box-store-snap-9 ", blob)
            self.assertIn("index/wesley.sqlite.box-store-snap-note ", blob)
            self.assertIn("index/wesley.sqlite.box-store-snap-8 ", blob)
            self.assertIn("index/wesley.sqlite.box-store-snap-8/inside ", blob)
            self.assertIn("index/wesley.sqlite.box-store-snap-5 ", blob)
            roots = [(f"PREACHED_CACHE={root}", root)]
            self.assertIsNone(cache_guard.classify_write(noise, roots))
            self.assertIsNotNone(cache_guard.classify_write(orphan, roots))
            self.assertIsNotNone(cache_guard.classify_write(as_dir, roots))
            self.assertIsNotNone(cache_guard.classify_write(dotted, roots))
            self.assertIsNotNone(cache_guard.classify_write(link, roots))
        finally:
            resolved = root.resolve()
            if not resolved.is_relative_to(Path(tempfile.gettempdir()).resolve()):
                raise AssertionError(f"refusing to remove {resolved}")
            import shutil

            shutil.rmtree(resolved)

    def test_package_import_arms_the_guard(self) -> None:
        script = textwrap.dedent(
            """\
            import tests.cache_guard as cache_guard
            assert cache_guard._installed, "package import did not arm the guard"
            print("package-armed")
            """
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(tempfile.gettempdir()),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("package-armed", result.stdout)

    def test_discovery_without_the_tests_package_arms_the_guard(self) -> None:
        """``discover -s tests`` puts the tests directory on sys.path and does not import the package."""
        cache = _temp_root()
        try:
            script = textwrap.dedent(
                """\
                import os, sys
                from pathlib import Path
                sys.path.insert(0, sys.argv[1])
                assert "tests" not in sys.modules
                import test_cache_guard
                import cache_guard
                assert "tests" not in sys.modules
                assert cache_guard._installed, "discovery import did not arm the guard"
                import unittest
                root = Path(os.environ["PREACHED_CACHE"])

                class T(unittest.TestCase):
                    def test_write(self):
                        (root / "leaked.bin").write_bytes(b"x")

                result = unittest.TextTestRunner(stream=open(os.devnull, "w"), verbosity=0).run(
                    unittest.defaultTestLoader.loadTestsFromTestCase(T)
                )
                blob = "\\n".join(str(item[1]) for item in result.failures)
                if "leaked.bin" not in blob:
                    sys.stderr.write(blob or "no failures\\n")
                    sys.exit(1)
                print("red")
                """
            )
            env = os.environ.copy()
            env.pop("PYTHONPATH", None)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            scratch = cache / "scratch"
            scratch.mkdir()
            for key, name in (
                ("PREACHED_CACHE", "cache"),
                ("HF_HOME", "hf"),
                ("DENO_DIR", "deno"),
                ("XDG_CACHE_HOME", "xdg"),
                ("PREACHED_ONNX_DIR", "onnx"),
            ):
                path = scratch / name
                path.mkdir()
                env[key] = str(path)
            result = subprocess.run(
                [sys.executable, "-c", script, str(ROOT / "tests")],
                cwd=str(cache),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("red", result.stdout)
            self.assertNotIn("tests", result.stdout)
        finally:
            resolved = cache.resolve()
            if not resolved.is_relative_to(Path(tempfile.gettempdir()).resolve()):
                raise AssertionError(f"refusing to remove {resolved}")
            import shutil

            shutil.rmtree(resolved)


# The one-line import every test module uses. install() is idempotent.
_ARM = '__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()'


def _is_arming_statement(stmt: ast.stmt) -> bool:
    """True when ``stmt`` is the arming call, compared as syntax not as text."""
    expected = ast.parse(_ARM).body[0]
    return ast.dump(stmt) == ast.dump(expected)


def _arming_is_first_import(tree: ast.AST) -> bool:
    """True when the arming call is the first import.

    A module docstring and ``from __future__`` imports may precede it.
    Any other statement, including a plain ``import`` or a string that
    merely contains the line, means the module is not armed first.
    """
    if not isinstance(tree, ast.Module):
        return False
    body = list(tree.body)
    index = 0
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        index = 1
    while index < len(body) and isinstance(body[index], ast.ImportFrom) and body[index].module == "__future__":
        index += 1
    return index < len(body) and _is_arming_statement(body[index])


def _probe_source() -> str:
    return (
        '"""Deliberate write under PREACHED_CACHE; the guard must fail the run."""\n'
        f"{_ARM}\n"
        "import os\n"
        "import unittest\n"
        "from pathlib import Path\n"
        "\n"
        "class ArmProbe(unittest.TestCase):\n"
        "    def test_deliberate_write(self) -> None:\n"
        '        Path(os.environ["PREACHED_CACHE"]).joinpath("leaked.bin").write_bytes(b"x")\n'
        "\n"
        'if __name__ == "__main__":\n'
        "    unittest.main()\n"
    )


def _repo_arming_probes() -> list[Path]:
    leftover = list((ROOT / "tests").glob("test_arming_probe*"))
    pycache = ROOT / "tests" / "__pycache__"
    if pycache.is_dir():
        leftover.extend(pycache.glob("test_arming_probe*"))
    return leftover


_CACHE_ENV_KEYS = (
    "PREACHED_CACHE",
    "PREACHED_ONNX_DIR",
    "HF_HOME",
    "HF_HUB_CACHE",
    "HUGGINGFACE_HUB_CACHE",
    "DENO_DIR",
    "XDG_CACHE_HOME",
    "UV_CACHE_DIR",
    "TORCH_HOME",
)


def _child_cache_env(scratch: Path, *, pythonpath: str | None) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if pythonpath is None:
        env.pop("PYTHONPATH", None)
    else:
        env["PYTHONPATH"] = pythonpath
    for key in _CACHE_ENV_KEYS:
        path = scratch / key.lower()
        path.mkdir()
        env[key] = str(path)
    return env


class ArmingInvocationTests(unittest.TestCase):
    """The three invocations that used to run with the guard uninstalled.

    The probe and a copy of ``cache_guard.py`` live under ``tempfile.mkdtemp``.
    Nothing is written into the repo's ``tests/`` directory.
    """

    def setUp(self) -> None:
        self.assertEqual(_repo_arming_probes(), [])
        self.work = _temp_root()
        self.addCleanup(self._remove, self.work)
        tests_dir = self.work / "tests"
        tests_dir.mkdir()
        source = ROOT / "tests" / "cache_guard.py"
        dest = tests_dir / "cache_guard.py"
        _assert_under_temp(dest)
        dest.write_bytes(source.read_bytes())
        self.probe = tests_dir / "test_arming_probe.py"
        _assert_under_temp(self.probe)
        self.probe.write_text(_probe_source())
        self.scratch = _temp_root()
        self.addCleanup(self._remove, self.scratch)
        self.env = _child_cache_env(self.scratch, pythonpath=None)
        self.addCleanup(self._assert_repo_clean)

    def _remove(self, path: Path) -> None:
        _remove_temp_tree(path)

    def _assert_repo_clean(self) -> None:
        self.assertEqual(_repo_arming_probes(), [])

    def _assert_armed(self, argv: list[str], cwd: Path) -> None:
        _assert_under_temp(cwd)
        result = subprocess.run(
            argv,
            cwd=cwd,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        blob = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, blob)
        self.assertIn("cache guard", blob)
        self.assertIn("leaked.bin", blob)
        self.assertEqual(_repo_arming_probes(), [])

    def test_discover_pattern_that_skips_this_module_is_armed(self) -> None:
        self.assertNotIn("test_cache_guard", "test_arming_probe.py")
        self._assert_armed(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_arming_probe.py"],
            self.work,
        )

    def test_unittest_from_inside_tests_is_armed(self) -> None:
        self._assert_armed([sys.executable, "-m", "unittest", "test_arming_probe"], self.work / "tests")

    def test_running_the_file_as_a_script_is_armed(self) -> None:
        self._assert_armed([sys.executable, "tests/test_arming_probe.py"], self.work)

    def test_every_test_module_imports_the_guard(self) -> None:
        self.assertEqual(_repo_arming_probes(), [])
        missing = []
        for path in sorted((ROOT / "tests").glob("test_*.py")):
            if path.name == "test_arming_probe.py":
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            if not _arming_is_first_import(tree):
                missing.append(path.name)
        self.assertEqual(missing, [])

    def test_arming_order_rejects_an_import_before_the_line(self) -> None:
        """A substring match is not enough. The arming call has to be the first import."""
        self.assertTrue(_arming_is_first_import(ast.parse(_ARM + "\nimport os\n")))
        self.assertTrue(
            _arming_is_first_import(
                ast.parse('"""doc"""\nfrom __future__ import annotations\n' + _ARM + "\nimport os\n")
            )
        )
        self.assertFalse(_arming_is_first_import(ast.parse("import os\n" + _ARM + "\n")))
        self.assertFalse(
            _arming_is_first_import(
                ast.parse("from __future__ import annotations\nimport os\n" + _ARM + "\n")
            )
        )
        self.assertFalse(_arming_is_first_import(ast.parse("def arm():\n    " + _ARM + "\n")))
        self.assertFalse(_arming_is_first_import(ast.parse("import os\n_ARM = " + repr(_ARM) + "\n")))


# Importing these modules is what ``python -m unittest <module>`` does before
# it runs their tests. Each one also imports a top-level test module, which
# loads ``cache_guard`` a second time. The child then runs one deliberate
# write so a double-wrapped guard would report two failures.
_ONCE_SCRIPT = textwrap.dedent(
    """\
    import builtins
    import importlib
    import io
    import os
    import sys
    import unittest

    real_io = io.open
    real_builtin = builtins.open
    importlib.import_module(sys.argv[1])
    names = [name for name in ("cache_guard", "tests.cache_guard") if name in sys.modules]
    distinct = {id(sys.modules[name]) for name in names}
    sys.stdout.write(f"loaded_names={len(names)} distinct={len(distinct)}\\n")
    if len(names) != 2 or len(distinct) != 1:
        sys.exit(2)
    cache = os.environ["PREACHED_CACHE"]

    class Probe(unittest.TestCase):
        def test_write(self):
            path = os.path.join(cache, "leaked.bin")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("x")

    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=1).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(Probe)
    )
    guard = [item for item in result.failures if "cache guard" in str(item[1])]
    sys.stdout.write(stream.getvalue())
    sys.stdout.write(
        f"guard_failures={len(guard)} failures={len(result.failures)} errors={len(result.errors)}\\n"
    )
    if len(guard) != 1 or len(result.failures) != 1 or result.errors:
        sys.exit(3)
    if io.open is not real_io or builtins.open is not real_builtin:
        sys.stdout.write(
            f"io_open_restored={io.open is real_io} builtin_restored={builtins.open is real_builtin}\\n"
        )
        sys.exit(4)
    sys.stdout.write("mf3-once-ok\\n")
    """
)

_TWICE_SCRIPT = textwrap.dedent(
    """\
    import builtins
    import io
    import os
    import sys
    import tempfile
    import unittest
    from pathlib import Path

    sys.path.insert(0, sys.argv[1])
    import tests.cache_guard
    import cache_guard

    if sys.modules.get("cache_guard") is not sys.modules.get("tests.cache_guard"):
        sys.stderr.write("guard loaded twice\\n")
        sys.exit(2)
    real_io = io.open
    real_builtin = builtins.open
    scratch = Path(sys.argv[2]).resolve()
    cache = Path(os.environ["PREACHED_CACHE"]).resolve()
    temp = Path(tempfile.gettempdir()).resolve()
    if not scratch.is_relative_to(temp) or scratch == cache or scratch.is_relative_to(cache):
        sys.stderr.write(f"scratch is not a temp dir outside the cache: {scratch}\\n")
        sys.exit(2)

    class Probe(unittest.TestCase):
        def test_legitimate_temp_write(self):
            target = scratch / "ok.txt"
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("hello")
            self.assertEqual(target.read_text(encoding="utf-8"), "hello")
            other = scratch / "via-path.bin"
            other.write_bytes(b"path")
            self.assertEqual(other.read_bytes(), b"path")

    loader = unittest.defaultTestLoader
    for index in (1, 2):
        stream = io.StringIO()
        try:
            result = unittest.TextTestRunner(stream=stream, verbosity=1).run(
                loader.loadTestsFromTestCase(Probe)
            )
        except RecursionError:
            sys.stderr.write(stream.getvalue())
            sys.stderr.write(f"RecursionError on run {index}\\n")
            sys.exit(3)
        if result.errors or result.failures or not result.wasSuccessful():
            sys.stderr.write(stream.getvalue())
            blob = "\\n".join(str(item[1]) for item in result.errors + result.failures)
            sys.stderr.write(blob)
            sys.stderr.write(f"\\nrun {index} failed\\n")
            sys.exit(4)
    if io.open is not real_io or builtins.open is not real_builtin:
        sys.exit(5)
    after = scratch / "after.txt"
    with open(after, "w", encoding="utf-8") as handle:
        handle.write("after")
    if after.read_text(encoding="utf-8") != "after":
        sys.exit(6)
    sys.stdout.write("mf3-twice-ok\\n")
    """
)


_SENTINEL_SCRIPT = textwrap.dedent(
    """\
    import sys

    sys.path.insert(0, sys.argv[1])
    import cache_guard
    from unittest.result import TestResult

    cache_guard.install()
    flag = cache_guard._GUARD_INSTALLED
    if getattr(TestResult, flag, None) is not True:
        sys.stderr.write(
            "sentinel missing after install: %r\\n" % (getattr(TestResult, flag, None),)
        )
        sys.exit(2)
    start = TestResult.startTestRun
    stop = TestResult.stopTestRun
    cache_guard.install()
    if TestResult.startTestRun is not start or TestResult.stopTestRun is not stop:
        sys.stderr.write("second install rewrapped while the sentinel was set\\n")
        sys.exit(3)
    if cache_guard._installed is not True:
        sys.stderr.write("module flag was not set\\n")
        sys.exit(4)
    delattr(TestResult, flag)
    cache_guard.install()
    if TestResult.startTestRun is start or TestResult.stopTestRun is stop:
        sys.stderr.write("clearing only the sentinel did not rewrap\\n")
        sys.exit(5)
    sys.stdout.write("sentinel-ok\\n")
    """
)

_IO_OPEN_SCRIPT = textwrap.dedent(
    """\
    import sys

    sys.path.insert(0, sys.argv[1])
    import io

    original = io.open
    import cache_guard

    if cache_guard._real_io_open is not original:
        sys.stderr.write("io.open was not captured at import\\n")
        sys.exit(2)

    def wrapped(file, mode="r", *args, **kwargs):
        return original(file, mode, *args, **kwargs)

    io.open = wrapped
    if cache_guard._real_io_open is not original:
        sys.stderr.write("import-time capture changed when io.open was replaced\\n")
        sys.exit(3)
    cache_guard._install_write_hooks()
    try:
        if cache_guard._real_io_open is not original:
            sys.stderr.write("hook install recaptured io.open\\n")
            sys.exit(4)
        if io.open is not cache_guard._hooked_io_open:
            sys.stderr.write("io.open was not hooked\\n")
            sys.exit(5)
    finally:
        cache_guard._remove_write_hooks()
    if io.open is not original or cache_guard._real_io_open is not original:
        sys.stderr.write("restore did not put back the import-time io.open\\n")
        sys.exit(6)
    sys.stdout.write("io-open-import-time-ok\\n")
    """
)


class ProcessGuardTests(unittest.TestCase):
    """``python -m unittest tests.test_coverage`` and ``tests.test_church_harden``.

    Those commands import a package test module and, through it, a top-level
    test module. Both names of the guard load. One deliberate write must be
    reported once, and both open functions must be the originals afterwards.
    Two runs in one process must not recurse, and a temp write must work.
    """

    def _env(self) -> tuple[Path, dict[str, str]]:
        scratch = _temp_root()
        self.addCleanup(_remove_temp_tree, scratch)
        return scratch, _child_cache_env(scratch, pythonpath=str(ROOT))

    def _run(self, script: str, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", script, *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )

    def _assert_loaded_once(self, module: str) -> None:
        _scratch, env = self._env()
        result = self._run(_ONCE_SCRIPT, [module], env)
        blob = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, blob)
        self.assertIn("loaded_names=2 distinct=1", result.stdout)
        self.assertIn("guard_failures=1", result.stdout)
        self.assertIn("mf3-once-ok", result.stdout)
        self.assertNotIn("RecursionError", blob)

    def test_unittest_tests_test_coverage_loads_the_guard_once(self) -> None:
        self._assert_loaded_once("tests.test_coverage")

    def test_unittest_tests_test_church_harden_loads_the_guard_once(self) -> None:
        self._assert_loaded_once("tests.test_church_harden")

    def test_two_runs_in_one_process_do_not_recurse_and_a_temp_write_works(self) -> None:
        scratch, env = self._env()
        write_dir = _temp_root()
        self.addCleanup(_remove_temp_tree, write_dir)
        result = self._run(_TWICE_SCRIPT, [str(ROOT / "tests"), str(write_dir)], env)
        blob = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, blob)
        self.assertIn("mf3-twice-ok", result.stdout)
        self.assertNotIn("RecursionError", blob)
        self.assertEqual((write_dir / "ok.txt").read_text(encoding="utf-8"), "hello")
        self.assertEqual((write_dir / "after.txt").read_text(encoding="utf-8"), "after")

    def test_testresult_sentinel_blocks_a_second_wrap_on_its_own(self) -> None:
        """The TestResult attribute is what stops a second wrap.

        ``_installed`` is already true on the second call. Clearing only the
        sentinel must wrap ``startTestRun`` again. A module-flag check would
        not, and the depth counter hides a missing sentinel from the other tests.
        """
        _scratch, env = self._env()
        result = self._run(_SENTINEL_SCRIPT, [str(ROOT / "tests")], env)
        blob = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, blob)
        self.assertIn("sentinel-ok", result.stdout)

    def test_io_open_is_captured_at_import_time(self) -> None:
        """``io.open`` is bound when the module is imported, not when the hook is installed."""
        source = (ROOT / "tests" / "cache_guard.py").read_text()
        tree = ast.parse(source)
        found = [
            stmt
            for stmt in tree.body
            if isinstance(stmt, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "_real_io_open" for target in stmt.targets)
        ]
        self.assertEqual(len(found), 1)
        value = found[0].value
        self.assertIsInstance(value, ast.Attribute)
        self.assertEqual(value.attr, "open")
        self.assertIsInstance(value.value, ast.Name)
        self.assertEqual(value.value.id, "io")
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "_real_io_open" for target in sub.targets
                ):
                    self.fail(f"{node.name} assigns _real_io_open")
        _scratch, env = self._env()
        result = self._run(_IO_OPEN_SCRIPT, [str(ROOT / "tests")], env)
        blob = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, blob)
        self.assertIn("io-open-import-time-ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
