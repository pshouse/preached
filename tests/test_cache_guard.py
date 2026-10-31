"""The suite fails when a run writes under PREACHED_CACHE or /cache."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import tests.cache_guard as cache_guard


class CacheGuardTests(unittest.TestCase):
    def test_snapshot_skips_excluded_dirs_and_sqlite_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
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
            (root / "models" / "graph").chmod(0o644)
            listing = cache_guard.snapshot_tree(root)
        self.assertEqual(set(listing), {"models/graph", "index/wesley.sqlite"})
        self.assertEqual(listing["models/graph"][0], 1)

    def test_diff_names_added_removed_and_changed_files(self) -> None:
        before = {"keep": (1, 10), "gone": (2, 20)}
        after = {"keep": (3, 11), "new": (4, 30)}
        text = "\n".join(cache_guard.diff_lines("PREACHED_CACHE=/cache", before, after))
        self.assertIn("PREACHED_CACHE=/cache changed keep size=1->3 mtime_ns=10->11", text)
        self.assertIn("PREACHED_CACHE=/cache removed gone size=2 mtime_ns=20", text)
        self.assertIn("PREACHED_CACHE=/cache added new size=4 mtime_ns=30", text)

    def test_classify_write_ignores_temp_files_and_excluded_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            roots = [(f"PREACHED_CACHE={root}", root)]
            graph = root / "models" / "model.fp32.onnx"
            self.assertEqual(
                cache_guard.classify_write(graph, roots),
                f"PREACHED_CACHE={root} write models/model.fp32.onnx",
            )
            self.assertIsNone(cache_guard.classify_write(root / "uv" / "pkg", roots))
            self.assertIsNone(cache_guard.classify_write(root / "xdg" / "deno" / "cache", roots))
            self.assertIsNone(cache_guard.classify_write(root / "index" / "wesley.sqlite-shm", roots))
            self.assertIsNone(cache_guard.classify_write(root / "index" / "wesley.sqlite-wal", roots))
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
