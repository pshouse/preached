"""CTO hard conditions on church wiring (review of #33).

1. Every read-only open of an index goes through ``store.open_readonly``, so
   a -shm hardlinked to wesley.sqlite is refused before SQLite writes the
   shm index into Wesley. Before, check_dedupe, check_nl_questions,
   review_sheet, apply_grades, bundle_manifest.copy_index (the deploy backup
   of the live index) and measure_parity connected with a raw ``mode=ro``.
2. The realpath half of ``library._sidecar_problem``: a symlinked index name
   whose real file's -shm links to Wesley is refused.
3. ``App.gated`` is read-only.
4. Command-line callers print one error line on ``UnsafeSidecar``.
5. ``mark_your_church_exclusive`` reports a sibling whose sidecar turned
   unsafe after the scans, instead of passing over it.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import os
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.server import STATIC_DIR, App, Searcher  # noqa: E402
import preached.library as library  # noqa: E402
from preached.library import _sidecar_problem, is_your_church, mark_your_church_exclusive  # noqa: E402
from preached.store import UnsafeSidecar, open_readonly, open_readonly_or_exit  # noqa: E402
from test_side import build_library, church_rows, classic_rows, reopen  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HARDLINK = "has a -shm file with 2 hard links"


def _load(rel: str, name: str):
    """Import a script by path, leaving os.environ as it was (measure_parity sets CUDA vars)."""
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ):
        spec.loader.exec_module(module)
    return module


class _PlantedWesley(unittest.TestCase):
    """A synthetic wesley.sqlite and a WAL index whose -shm name is a hardlink to it."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.index_dir = self.root / "index"
        self.index_dir.mkdir()
        self.wesley = self.index_dir / "wesley.sqlite"
        build_library(self.wesley, *classic_rows())
        for target in (
            patch("preached.paths.INDEX_DIR", self.index_dir),
            patch("preached.paths.INDEX_PATH", self.wesley),
        ):
            target.start()
            self.addCleanup(target.stop)

    def wal_index(self, path: Path) -> Path:
        build_library(path, *classic_rows())
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as probe:
            self.assertEqual(probe.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        # The read-only probe leaves an -shm behind (and a WAL file with no
        # sidecars is what an ingest leaves once it closes).
        for suffix in ("-wal", "-shm"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)
        return path

    def plant(self, path: Path, suffix: str = "-shm") -> Path:
        sidecar = Path(f"{path}{suffix}")
        os.link(self.wesley, sidecar)
        self.addCleanup(sidecar.unlink, missing_ok=True)
        return sidecar

    def wesley_state(self) -> tuple[str, int, int]:
        st = self.wesley.stat()
        return hashlib.sha256(self.wesley.read_bytes()).hexdigest(), st.st_size, st.st_mtime_ns

    def assert_refused_and_wesley_unchanged(self, run) -> None:
        before = self.wesley_state()
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as caught:
                run()
        self.assertIn(HARDLINK, str(caught.exception.code))
        self.assertEqual(self.wesley_state(), before)


def _fake_models(module) -> None:
    module.load_model = lambda *_a, **_k: object()
    module.encode_query = lambda *_a, **_k: np.zeros(4, dtype=np.float32)
    module.unload = lambda *_a, **_k: None


class ScriptReadOnlyOpenTests(_PlantedWesley):
    """Hard condition 1: each script refuses the planted index and Wesley's bytes do not change.

    On the merge base every one of these wrote the shm index into Wesley
    (``reports/40-W3-CHURCH-GATE-WIRE.md``, "Hard conditions": probe table).
    """

    def setUp(self) -> None:
        super().setUp()
        self.index = self.wal_index(self.root / "target.sqlite")

    def test_review_sheet(self) -> None:
        module = _load("scripts/review_sheet.py", "hc_review_sheet")
        argv = ["review_sheet.py", "--index", str(self.index), "--out", str(self.root / "sheet.csv")]
        self.plant(self.index)
        with patch.object(sys, "argv", argv):
            self.assert_refused_and_wesley_unchanged(module.main)
        self.assertFalse((self.root / "sheet.csv").exists())

    def test_check_dedupe(self) -> None:
        module = _load("scripts/check_dedupe.py", "hc_check_dedupe")
        _fake_models(module)
        self.plant(self.index)
        argv = ["check_dedupe.py", "--index", str(self.index), "--models", "granite-english-r2"]
        with patch.object(sys, "argv", argv):
            self.assert_refused_and_wesley_unchanged(module.main)

    def test_check_nl_questions(self) -> None:
        module = _load("scripts/check_nl_questions.py", "hc_check_nl_questions")
        _fake_models(module)
        self.plant(self.index)
        argv = ["check_nl_questions.py", "--index", str(self.index), "--models", "granite-english-r2"]
        with patch.object(sys, "argv", argv):
            self.assert_refused_and_wesley_unchanged(module.main)

    def test_apply_grades(self) -> None:
        module = _load("eval/apply_grades.py", "hc_apply_grades")
        self.plant(self.index)
        self.assert_refused_and_wesley_unchanged(lambda: module.load_chunks(self.index))

    def test_bundle_manifest_copy_index(self) -> None:
        module = _load("scripts/bundle_manifest.py", "hc_bundle_manifest")
        dest = self.root / "bundle" / "index" / "wesley.sqlite"
        self.plant(self.index)
        self.assert_refused_and_wesley_unchanged(lambda: module.copy_index(self.index, dest))
        self.assertFalse(dest.exists())

    def test_measure_parity_every_open(self) -> None:
        module = _load("scripts/measure_parity.py", "hc_measure_parity")
        safe = self.root / "safe.sqlite"
        build_library(safe, *classic_rows())
        torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False),
                                      set_num_threads=lambda _n: None)
        self.plant(self.index)
        cases = {
            "load_rows": ({"TORCH_INDEX": self.index}, module.load_rows),
            "load_torch_docs": ({"TORCH_INDEX": self.index}, lambda: module.load_torch_docs([1])),
            "step_spotcheck shipped": (
                {"TORCH_INDEX": safe, "SHIPPED_INDEX": self.index, "load_torch_docs": lambda _rowids: None},
                lambda: module.step_spotcheck(1),
            ),
            "_copy_index": ({"SHIPPED_INDEX": self.root / "shipped.sqlite"},
                            lambda: module._copy_index(self.index, self.root / "copy.sqlite")),
        }
        for name, (attrs, run) in cases.items():
            with self.subTest(open=name), patch.multiple(module, **attrs), patch.dict(sys.modules, {"torch": torch}):
                self.assert_refused_and_wesley_unchanged(run)

    def test_the_same_scripts_read_an_index_with_safe_sidecars(self) -> None:
        before = self.wesley_state()
        chunks = _load("eval/apply_grades.py", "hc_apply_grades_ok").load_chunks(self.index)
        self.assertEqual(sorted(chunks), ["classic-a", "classic-b", "classic-shared"])
        dest = self.root / "bundle" / "index" / "wesley.sqlite"
        _load("scripts/bundle_manifest.py", "hc_bundle_manifest_ok").copy_index(self.index, dest)
        with closing(sqlite3.connect(f"{dest.as_uri()}?mode=ro", uri=True)) as copy:
            self.assertEqual(copy.execute("SELECT count(*) FROM chunks").fetchone()[0], 3)
        self.assertEqual(self.wesley_state(), before)


# Raw sqlite3.connect calls left outside tests/, each with why it is not open_readonly.
RAW_CONNECTS = {
    "src/preached/store.py": 2,  # connect() (the writer) and open_readonly itself
    "src/preached/library.py": 1,  # _Checked: mode=rw, sidecars and the opened descriptor checked
    "src/preached/search.py": 1,  # ":memory:"
    "scripts/bundle_manifest.py": 1,  # dst: the new bundle copy it just unlinked and creates
    "scripts/measure_parity.py": 1,  # dst: a new copy under /cache/w3-cpu (refuses the shipped path)
    "scripts/gate_leak_sweep.py": 1,  # writer: the synthetic temp index the sweep just built
}


class RawConnectGuardTests(unittest.TestCase):
    """Hard condition 1, repo-wide: no new raw connect slips past open_readonly."""

    def test_only_the_listed_raw_connects_remain(self) -> None:
        found: dict[str, int] = {}
        for path in sorted(ROOT.rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith((".venv/", "tests/", ".worktrees/")) or "/." in f"/{rel}":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "connect"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "sqlite3"
                ):
                    found[rel] = found.get(rel, 0) + 1
        self.assertEqual(found, RAW_CONNECTS)


class RealpathSidecarTests(_PlantedWesley):
    """Hard condition 2: the realpath half of ``_sidecar_problem``.

    SQLite resolves a symlinked database name and opens the sidecars next
    to the real file (``open_readonly`` connects to ``resolve()``). Here the
    name ``link.sqlite`` has no sidecars of its own; only the real file's
    -shm is a hardlink to Wesley, so only the realpath half can see it.
    """

    def setUp(self) -> None:
        super().setUp()
        real_dir = self.root / "real"
        real_dir.mkdir()
        self.real = self.wal_index(real_dir / "church.sqlite")
        self.link = self.root / "link.sqlite"
        os.symlink(self.real, self.link)

    def test_a_symlinked_name_whose_real_shm_links_to_wesley_is_refused(self) -> None:
        self.plant(self.real)
        self.assertFalse(Path(f"{self.link}-shm").exists())
        before = self.wesley_state()
        self.assertIn(HARDLINK, _sidecar_problem(self.link) or "")
        with self.assertRaises(UnsafeSidecar) as caught:
            open_readonly(self.link)
        self.assertIn(HARDLINK, str(caught.exception))
        self.assertEqual(self.wesley_state(), before)
        self.assertEqual(os.stat(self.wesley).st_nlink, 2)

    def test_the_symlinked_name_opens_when_the_real_sidecars_are_safe(self) -> None:
        before = self.wesley_state()
        self.assertIsNone(_sidecar_problem(self.link))
        connection = open_readonly(self.link)
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM chunks").fetchone()[0], 3)
        finally:
            connection.close()
        self.assertEqual(self.wesley_state(), before)


class AppGatedReadOnlyTests(unittest.TestCase):
    """Hard condition 3: ``App.gated`` drives visible_sql, visible_count and every reload Searcher."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def app(self, path: Path, library_slug: str) -> App:
        connection = reopen(path)
        self.addCleanup(connection.close)
        return App(connection=connection, searcher=Searcher(connection), encode=None, fallback_note=None,
                   model_name="fixture", hosts={"127.0.0.1"}, static_dir=STATIC_DIR, library=library_slug)

    def test_a_church_app_cannot_turn_its_gate_off(self) -> None:
        church = self.root / "sample.sqlite"
        build_library(church, *church_rows(), church=True, sample=True)
        app = self.app(church, "sample")
        self.assertIs(app.gated, True)
        with self.assertRaises(AttributeError):
            app.gated = False
        with self.assertRaises(AttributeError):
            setattr(app, "gated", False)
        with self.assertRaises(AttributeError):
            del app.gated
        self.assertIs(app.gated, True)
        self.assertIs(app._searcher().gated, True)

    def test_the_wesley_app_is_ungated_and_also_read_only(self) -> None:
        wesley = self.root / "wesley.sqlite"
        build_library(wesley, *classic_rows())
        app = self.app(wesley, "wesley")
        self.assertIs(app.gated, False)
        with self.assertRaises(AttributeError):
            app.gated = True


class ErrorLineTests(_PlantedWesley):
    """Hard condition 4 (CTO item 4): an unsafe sidecar is one error line, not a traceback."""

    def test_open_readonly_or_exit(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            open_readonly_or_exit(self.root / "missing.sqlite")
        self.assertEqual(str(caught.exception.code), f"error: missing index {self.root / 'missing.sqlite'}")
        index = self.wal_index(self.root / "target.sqlite")
        self.plant(index)
        with self.assertRaises(SystemExit) as caught:
            open_readonly_or_exit(index)
        self.assertEqual(str(caught.exception.code), f"error: {index} {HARDLINK}; it is not opened")

    def test_scripts_print_one_error_line(self) -> None:
        index = self.wal_index(self.root / "target.sqlite")
        self.plant(index)
        runs = {
            "review_sheet": [str(ROOT / "scripts" / "review_sheet.py"), "--index", str(index),
                             "--out", str(self.root / "sheet.csv")],
            "smoke_server": [str(ROOT / "scripts" / "smoke_server.py"), "--index", str(index)],
            "eval/pool": [str(ROOT / "eval" / "pool.py"), "--index", str(index), "--out", str(self.root / "p.jsonl"),
                          "--texts", str(self.root / "texts")],
        }
        for name, argv in runs.items():
            with self.subTest(script=name):
                before = self.wesley_state()
                result = subprocess.run([sys.executable, *argv], capture_output=True, text=True, timeout=120,
                                        check=False, env={**os.environ, "PREACHED_CACHE": str(self.root)})
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(result.stderr.strip(), f"error: {index} {HARDLINK}; it is not opened")
                self.assertEqual(self.wesley_state(), before)

    def test_build_library_check_target(self) -> None:
        module = _load("search/build_library.py", "hc_build_library")
        index = self.wal_index(self.root / "target.sqlite")
        self.plant(index)
        self.assert_refused_and_wesley_unchanged(lambda: module.check_target(index, "spurgeon"))


class SiblingSidecarSkippedTests(_PlantedWesley):
    """CTO item 5: a sibling whose sidecar turns unsafe after the scans is reported as skipped."""

    def test_a_sibling_made_unsafe_after_the_scans_is_reported(self) -> None:
        rows, vectors = church_rows()
        target = self.index_dir / "sample.sqlite"
        sibling = self.index_dir / "other.sqlite"
        build_library(target, rows[:1], vectors[:1], church=True, sample=True)
        build_library(sibling, rows[:1], vectors[:1], church=True)
        scanned = library.church_index_matches(self.index_dir, exclude=target.resolve())
        self.assertEqual(scanned, [sibling])

        def after_the_scans(*_args, **_kwargs):
            # The read-only scans leave an -shm; swap it for a link to Wesley.
            Path(f"{sibling}-shm").unlink(missing_ok=True)
            self.plant(sibling)
            return scanned

        before = self.wesley_state()
        with patch.object(library, "church_index_matches", after_the_scans):
            skipped = mark_your_church_exclusive(target, self.index_dir, sample=True)
        self.assertEqual(skipped, [(sibling, f"{HARDLINK} (not opened)")])
        self.assertEqual(self.wesley_state(), before)
        Path(f"{sibling}-shm").unlink()
        with closing(open_readonly(sibling)) as connection:
            self.assertTrue(is_your_church(connection))


if __name__ == "__main__":
    unittest.main()
