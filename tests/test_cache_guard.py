"""The suite fails when a run writes under PREACHED_CACHE or /cache.

Importing this module calls ``cache_guard.install``. Every other test
module does the same with one import line, so a ``discover -p`` pattern
that does not load this file, ``python -m unittest test_x`` from inside
``tests/``, and ``python tests/test_x.py`` are armed too. ``install`` is
idempotent.
"""

from __future__ import annotations

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

cache_guard.install()

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
                outside.unlink()
        # Both opens hit the same path, so the note set keeps one line.
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("index/wesley.sqlite", notes[0])
        self.assertTrue(notes[0].startswith(label + " "), notes)

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


class ArmingInvocationTests(unittest.TestCase):
    """The three invocations that used to run with the guard uninstalled."""

    def setUp(self) -> None:
        self.probe = ROOT / "tests" / "test_arming_probe.py"
        self.probe.write_text(_probe_source())
        self.scratch = _temp_root()
        self.env = os.environ.copy()
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.env.pop("PYTHONPATH", None)
        for key in (
            "PREACHED_CACHE",
            "PREACHED_ONNX_DIR",
            "HF_HOME",
            "HF_HUB_CACHE",
            "HUGGINGFACE_HUB_CACHE",
            "DENO_DIR",
            "XDG_CACHE_HOME",
            "UV_CACHE_DIR",
            "TORCH_HOME",
        ):
            path = self.scratch / key.lower()
            path.mkdir()
            self.env[key] = str(path)

    def tearDown(self) -> None:
        if self.probe.exists():
            self.probe.unlink()
        pycache = ROOT / "tests" / "__pycache__"
        if pycache.is_dir():
            for item in pycache.glob("test_arming_probe*"):
                item.unlink()
        resolved = self.scratch.resolve()
        if not resolved.is_relative_to(Path(tempfile.gettempdir()).resolve()):
            raise AssertionError(f"refusing to remove {resolved}")
        import shutil

        shutil.rmtree(resolved)

    def _assert_armed(self, argv: list[str], cwd: Path) -> None:
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

    def test_discover_pattern_that_skips_this_module_is_armed(self) -> None:
        self.assertNotIn("test_cache_guard", "test_arming_probe.py")
        self._assert_armed(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_arming_probe.py"],
            ROOT,
        )

    def test_unittest_from_inside_tests_is_armed(self) -> None:
        self._assert_armed([sys.executable, "-m", "unittest", "test_arming_probe"], ROOT / "tests")

    def test_running_the_file_as_a_script_is_armed(self) -> None:
        self._assert_armed([sys.executable, "tests/test_arming_probe.py"], ROOT)

    def test_every_test_module_imports_the_guard(self) -> None:
        missing = []
        for path in sorted((ROOT / "tests").glob("test_*.py")):
            if path.name == "test_arming_probe.py":
                continue
            text = path.read_text()
            if path.name == "test_cache_guard.py":
                if "cache_guard.install()" not in text:
                    missing.append(path.name)
                continue
            if _ARM not in text:
                missing.append(path.name)
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
