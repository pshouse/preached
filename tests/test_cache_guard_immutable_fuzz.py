"""Differential fuzz for SQLite ``immutable`` URIs the cache guard must refuse.

URIs are generated from a fixed seed. Real SQLite (the unhooked
``sqlite3.connect``) decides which ones open immutable, by reading through
an EXCLUSIVE lock held by another connection. Every one of those must be
refused by the armed guard under a watched root. The guard may refuse
more than SQLite opens immutable. The test fails when this SQLite build
has no URI support.
"""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import os
import random
import sqlite3
import tempfile
import unittest
from pathlib import Path

try:
    from . import cache_guard
except ImportError:  # discover -s tests loads this file as a top-level module
    import cache_guard

# The generator is deterministic. Changing the seed changes the corpus.
SEED = 20261031

# These three classes are what a decimal-only atoi and a no-NUL compare miss,
# plus the later case-sensitive key SQLite still honors.
_PINNED_IMMUTABLE = (
    "?mode=ro&immutable=0x1",
    "?mode=ro&immutable=0X1",
    "?mode=ro&immutable=0x10",
    "?mode=ro&immutable=0xA",
    "?mode=ro&immutable=yes%00",
    "?mode=ro&immutable=true%00x",
    "?mode=ro&immutable=on%00",
    "?mode=ro&immutable%00junk=1",
    "?mode=ro&immutable%00=1",
    "?mode=ro&IMMUTABLE=0&immutable=1",
)

_KEYS = (
    "immutable",
    "IMMUTABLE",
    "Immutable",
    "immutable%00junk",
    "immutable%00",
    "%69mmutable",
    "%69mmutable%00x",
)
_TRUE_VALUES = (
    "1",
    "01",
    "10",
    "yes",
    "on",
    "true",
    "TRUE",
    "YES",
    "0x1",
    "0X1",
    "0x10",
    "0xA",
    "0xa",
    "0x0001",
    "0xF",
    "yes%00",
    "true%00x",
    "on%00",
    "ON%00",
    "1%00",
    "yes%00no",
    "%31",
    "%30%78%31",
)
_FALSE_VALUES = (
    "",
    "0",
    "00",
    "000",
    "no",
    "off",
    "false",
    "NO",
    "FALSE",
    "0%00",
    "no%00",
    "false%00",
    "0x0",
    "0x00",
    "0X0",
)
_RANDOM_PAIRS = 500


def _temp_root() -> Path:
    """A directory under the system temp dir, outside /cache and PREACHED_CACHE."""
    root = Path(tempfile.mkdtemp(prefix="preached-immut-fuzz-")).resolve()
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


def _seed_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    setup = cache_guard._real_sqlite_connect(os.fspath(path))
    try:
        setup.execute("PRAGMA journal_mode=DELETE")
        setup.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        setup.execute("INSERT INTO t(v) VALUES ('base')")
        setup.commit()
    finally:
        setup.close()


def _uri_supported(path: Path) -> bool:
    """True when ``file:`` query parameters such as ``mode=ro`` are honored."""
    uri = path.resolve().as_uri() + "?mode=ro"
    try:
        conn = cache_guard._real_sqlite_connect(uri, uri=True, timeout=0)
    except sqlite3.OperationalError:
        return False
    try:
        try:
            conn.execute("CREATE TABLE uri_probe (x)")
        except sqlite3.OperationalError as exc:
            return "readonly" in str(exc).lower()
        return False
    finally:
        conn.close()


def _generated_queries() -> list[str]:
    """``mode=ro`` URIs. The mode key stays a single exact ``ro``."""
    queries = ["?mode=ro", "?mode=ro&immutable=1", "?mode=ro&cache=shared"]
    queries.extend(_PINNED_IMMUTABLE)
    values = _TRUE_VALUES + _FALSE_VALUES
    for key in _KEYS:
        for value in values:
            queries.append(f"?mode=ro&{key}={value}")
    rng = random.Random(SEED)
    for _ in range(_RANDOM_PAIRS):
        left = f"{rng.choice(_KEYS)}={rng.choice(values)}"
        right = f"{rng.choice(_KEYS)}={rng.choice(values)}"
        if rng.randrange(2):
            left, right = right, left
        queries.append(f"?mode=ro&{left}&{right}")
    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        if query in seen:
            continue
        seen.add(query)
        unique.append(query)
    return unique


def _sqlite_immutable_queries(path: Path, queries: list[str]) -> list[str]:
    """Queries that read through an EXCLUSIVE lock held on ``path``.

    A non-immutable open fails with ``database is locked``. An immutable
    open does not take the lock, so the read returns the seeded row.
    """
    holder = cache_guard._real_sqlite_connect(os.fspath(path), timeout=0)
    base = path.resolve().as_uri()
    found: list[str] = []
    try:
        holder.execute("BEGIN EXCLUSIVE")
        for query in queries:
            reader = None
            try:
                try:
                    reader = cache_guard._real_sqlite_connect(base + query, uri=True, timeout=0)
                except sqlite3.OperationalError:
                    continue
                try:
                    row = reader.execute("SELECT v FROM t").fetchone()
                except sqlite3.OperationalError as exc:
                    if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                        continue
                    raise
                if row != ("base",):
                    raise AssertionError(f"{query} returned {row!r}")
                found.append(query)
            finally:
                if reader is not None:
                    reader.close()
    finally:
        holder.rollback()
        holder.close()
    return found


class SqliteImmutableDifferentialTests(unittest.TestCase):
    def test_guard_refuses_every_uri_sqlite_opens_immutable(self) -> None:
        self.assertIsNotNone(cache_guard.current_run(), "the suite hook is not armed")
        root = _temp_root()
        label = f"fuzz-{root.name}"
        pushed = False
        try:
            oracle_db = root / "oracle.sqlite"
            _seed_db(oracle_db)
            if not _uri_supported(oracle_db):
                self.fail("SQLite build lacks URI support")
            watched = root / "watched"
            guard_db = watched / "sample.sqlite"
            _seed_db(guard_db)
            queries = _generated_queries()
            immutable = _sqlite_immutable_queries(oracle_db, queries)
            self.assertNotIn("?mode=ro", immutable)
            self.assertNotIn("?mode=ro&cache=shared", immutable)
            self.assertIn("?mode=ro&immutable=1", immutable)
            for query in _PINNED_IMMUTABLE:
                self.assertIn(query, immutable, query)
            cache_guard.push_root(label, watched)
            pushed = True
            base = guard_db.resolve().as_uri()
            missed: list[tuple[str, str]] = []
            for query in immutable:
                conn = None
                try:
                    conn = sqlite3.connect(base + query, uri=True, timeout=0)
                except sqlite3.OperationalError as exc:
                    message = str(exc)
                    if "cache guard" not in message or "immutable" not in message:
                        missed.append((query, message))
                else:
                    missed.append((query, "opened"))
                finally:
                    if conn is not None:
                        conn.close()
            if missed:
                sample = ", ".join(repr(query) for query, _reason in missed[:8])
                self.fail(
                    f"{len(missed)} of {len(immutable)} SQLite-immutable URIs "
                    f"were not refused (seed {SEED}), e.g. {sample}"
                )
        finally:
            if pushed:
                cache_guard.pop_root(label)
            _remove_temp_tree(root)
