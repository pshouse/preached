"""Fail a unittest run that writes under a real cache.

The suite reads PREACHED_CACHE. It must not create or change anything
there. Tool caches (XDG_CACHE_HOME, DENO_DIR) are pointed at a temp directory
so deno and ONNX Runtime do not use /cache/xdg.

A before/after listing catches files left behind, including a same-size
replace, a chmod, a new symlink, an empty directory, and a SQLite -wal
file written by a connection that is still open. Write-mode opens are
recorded as they happen, so a file created under the cache and removed
before the run ends still fails the run. A writable sqlite3.connect under
a watched root is refused; mode=ro URIs are left alone.

Arming: import the tests package (``python -m unittest tests.<module>``)
or discover the suite (``python -m unittest discover -s tests`` from any
directory). Discovery loads ``test_cache_guard``, which calls ``install``
without going through the package. ``python -m unittest test_x`` with the
working directory inside tests/ does not arm the guard.
"""

from __future__ import annotations

import atexit
import fnmatch
import os
import sqlite3
import stat
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

# Top-level directories that other tools rewrite. -shm changes when a
# read-only connection opens a WAL index, so those sidecars are ignored.
# -wal is the log itself: an insert or update with the connection still
# open changes only that file. The box snapshot daemon's
# *.box-store-snap-* names are noise. Everything else must stay put.
_EXCLUDED_DIRS = frozenset({"uv", "uv-python", "venvs", "xdg", "demo-kill"})
_SNAP_NOISE = "*.box-store-snap-*"
_REAL_CACHE = Path("/cache")

_installed = False
_tool_root: Path | None = None
_depth = 0
_run: "_Run | None" = None
_real_builtin_open = open
_real_os_open = os.open
_real_io_open = None
_real_sqlite_connect = sqlite3.connect
_hooks_on = False
_in_hook = False


class Entry(tuple):
    """lstat identity of one path. Directories compare inode and mode only.

    A directory's size, mtime and ctime move when the box daemon adds and
    removes a snap file beside a watched file. Those names are ignored, and
    the directory's timestamps are too, so that noise does not fail a run.
    Inode and mode still catch a replaced directory and a chmod of one.
    Files and symlinks compare inode, mode, size, mtime and ctime, so a
    same-size same-mtime replace, a chmod, or a metadata-only change is
    visible. Symlinks are lstat'd and not followed.
    """

    __slots__ = ()

    def __new__(cls, inode: int, mode: int, size: int, mtime_ns: int, ctime_ns: int) -> "Entry":
        return tuple.__new__(cls, (inode, mode, size, mtime_ns, ctime_ns))

    @property
    def inode(self) -> int:
        return self[0]

    @property
    def mode(self) -> int:
        return self[1]

    @property
    def size(self) -> int:
        return self[2]

    @property
    def mtime_ns(self) -> int:
        return self[3]

    @property
    def ctime_ns(self) -> int:
        return self[4]


class _Run:
    def __init__(self, roots: list[tuple[str, Path]]) -> None:
        self.endpoint_roots = list(roots)
        self.live_roots = list(roots)
        self.before = {label: snapshot_tree(root) for label, root in roots}
        self.notes: set[str] = set()


def _ignored_name(name: str) -> bool:
    if fnmatch.fnmatch(name, _SNAP_NOISE):
        return True
    # -shm only. -wal of a watched database is itself watched.
    return name.endswith("-shm")


def _ignored_rel(rel: str) -> bool:
    if not rel or rel == ".":
        return True
    parts = rel.split("/")
    if parts[0] in _EXCLUDED_DIRS:
        return True
    return any(_ignored_name(part) for part in parts)


def _entry(path: str) -> Entry | None:
    try:
        st = os.lstat(path)
    except OSError:
        return None
    return Entry(st.st_ino, st.st_mode, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _visible(entry: Entry) -> tuple:
    """The fields a change is judged on. Directory timestamps are not among them."""
    if stat.S_ISDIR(entry.mode):
        return (entry.inode, entry.mode)
    return (entry.inode, entry.mode, entry.size, entry.mtime_ns, entry.ctime_ns)


def _format_entry(entry: Entry) -> str:
    return (
        f"inode={entry.inode} mode={oct(entry.mode)} size={entry.size} "
        f"mtime_ns={entry.mtime_ns} ctime_ns={entry.ctime_ns}"
    )


def snapshot_tree(root: Path) -> dict[str, Entry]:
    """Relative path -> lstat identity for files, directories and symlinks.

    Symlinks are not followed. Excluded directories and ignored names are
    not walked and not listed. The snapshot only stats; it does not write.
    ``.`` is the root itself, so a chmod of the cache directory is visible.
    """
    listing: dict[str, Entry] = {}
    base = os.fspath(root)
    root_entry = _entry(base)
    if root_entry is not None:
        listing["."] = root_entry
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        rel_dir = os.path.relpath(dirpath, base)
        prefix = "" if rel_dir == "." else rel_dir.replace(os.sep, "/") + "/"
        kept: list[str] = []
        for name in dirnames:
            rel = name if not prefix else prefix + name
            if _ignored_rel(rel):
                continue
            path = os.path.join(dirpath, name)
            entry = _entry(path)
            if entry is not None:
                listing[rel] = entry
            # A symlink to a directory is listed and not descended into.
            if os.path.islink(path):
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            rel = name if not prefix else prefix + name
            if _ignored_rel(rel):
                continue
            entry = _entry(os.path.join(dirpath, name))
            if entry is not None:
                listing[rel] = entry
    return listing


def diff_lines(label: str, before: dict[str, Entry], after: dict[str, Entry]) -> list[str]:
    lines = []
    for rel in sorted(set(before) | set(after)):
        if rel not in before:
            lines.append(f"{label} added {rel} {_format_entry(after[rel])}")
        elif rel not in after:
            lines.append(f"{label} removed {rel} {_format_entry(before[rel])}")
        elif _visible(before[rel]) != _visible(after[rel]):
            old, new = before[rel], after[rel]
            lines.append(
                f"{label} changed {rel} "
                f"inode={old.inode}->{new.inode} mode={oct(old.mode)}->{oct(new.mode)} "
                f"size={old.size}->{new.size} mtime_ns={old.mtime_ns}->{new.mtime_ns} "
                f"ctime_ns={old.ctime_ns}->{new.ctime_ns}"
            )
    return lines


def watched_roots() -> list[tuple[str, Path]]:
    """Existing cache directories this process must not change.

    PREACHED_CACHE is watched when it names a directory. /cache is watched
    whenever it exists, including when PREACHED_CACHE points somewhere else.
    """
    found: list[tuple[str, Path]] = []
    seen: set[Path] = set()

    def add(label: str, path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            return
        if not resolved.is_dir() or resolved in seen:
            return
        seen.add(resolved)
        found.append((label, resolved))

    raw = os.environ.get("PREACHED_CACHE")
    if raw:
        add(f"PREACHED_CACHE={raw}", Path(raw))
    if _REAL_CACHE.is_dir():
        add("/cache", _REAL_CACHE)
    return found


def classify_write(path: object, roots: list[tuple[str, Path]]) -> str | None:
    """``label write relative/path`` when ``path`` is a regular-file write under a watched root."""
    try:
        text = os.fspath(path)  # type: ignore[arg-type]
    except TypeError:
        return None
    if isinstance(text, bytes):
        text = os.fsdecode(text)
    if not isinstance(text, str) or not text:
        return None
    try:
        resolved = Path(text).resolve()
    except OSError:
        return None
    for label, root in roots:
        try:
            rel = resolved.relative_to(root).as_posix()
        except ValueError:
            continue
        if _ignored_rel(rel):
            continue
        return f"{label} write {rel}"
    return None


def _assert_under_temp(path: Path) -> Path:
    resolved = path.resolve()
    temp = Path(tempfile.gettempdir()).resolve()
    if not resolved.is_relative_to(temp):
        raise RuntimeError(f"refusing to touch a path outside the temp dir: {resolved}")
    try:
        cache = _REAL_CACHE.resolve()
    except OSError:
        cache = _REAL_CACHE
    if resolved == cache or _is_inside(resolved, cache):
        raise RuntimeError(f"refusing to touch the real cache: {resolved}")
    return resolved


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _redirect_tool_caches() -> None:
    global _tool_root
    if _tool_root is not None:
        return
    root = Path(tempfile.mkdtemp(prefix="preached-tool-"))
    root = _assert_under_temp(root)
    xdg = root / "xdg"
    deno = root / "deno"
    xdg.mkdir()
    deno.mkdir()
    os.environ["XDG_CACHE_HOME"] = str(xdg)
    os.environ["DENO_DIR"] = str(deno)
    _tool_root = root
    atexit.register(_cleanup_tool_root, root)


def _cleanup_tool_root(root: Path) -> None:
    resolved = _assert_under_temp(root)
    # Local import: shutil is unused unless a run actually exits.
    import shutil

    shutil.rmtree(resolved)


def _mode_writes(mode: object) -> bool:
    return isinstance(mode, str) and any(flag in mode for flag in ("w", "a", "x", "+"))


def _record(path: object) -> None:
    global _in_hook
    if _in_hook or _run is None:
        return
    _in_hook = True
    try:
        note = classify_write(path, _run.live_roots)
        if note is not None:
            _run.notes.add(note)
    finally:
        _in_hook = False


def _hooked_builtin_open(file, mode="r", *args, **kwargs):
    if _mode_writes(mode):
        _record(file)
    return _real_builtin_open(file, mode, *args, **kwargs)


def _hooked_os_open(path, flags, *args, **kwargs):
    write_bits = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
    if isinstance(flags, int) and flags & write_bits:
        _record(path)
    return _real_os_open(path, flags, *args, **kwargs)


def _hooked_io_open(file, mode="r", *args, **kwargs):
    # pathlib writes through io.open, which keeps its own reference.
    if _mode_writes(mode):
        _record(file)
    return _real_io_open(file, mode, *args, **kwargs)


def _connect_uri(args: tuple, kwargs: dict) -> bool:
    if "uri" in kwargs:
        return bool(kwargs["uri"])
    # timeout, detect_types, isolation_level, check_same_thread, factory,
    # cached_statements, uri. uri becomes keyword-only in 3.15.
    return bool(args[6]) if len(args) >= 7 else False


def _sqlite_fs_path(database: object, uri: bool) -> str | None:
    try:
        text = os.fspath(database)  # type: ignore[arg-type]
    except TypeError:
        return None
    if isinstance(text, bytes):
        text = os.fsdecode(text)
    if not isinstance(text, str) or text in {":memory:", ""}:
        return None
    if uri and text.startswith("file:"):
        path = urllib.parse.unquote(urllib.parse.urlparse(text).path)
        if path in {":memory:", ""}:
            return None
        return path
    return text


def _sqlite_is_readonly(database: object, uri: bool) -> bool:
    """True only for a URI whose mode parameter is ro."""
    if not uri:
        return False
    try:
        text = os.fspath(database)  # type: ignore[arg-type]
    except TypeError:
        return False
    if isinstance(text, bytes):
        text = os.fsdecode(text)
    if not isinstance(text, str) or "?" not in text:
        return False
    query = text.split("?", 1)[1].split("#", 1)[0]
    modes = [item.strip().lower() for item in urllib.parse.parse_qs(query).get("mode", [])]
    return bool(modes) and all(mode == "ro" for mode in modes)


def _hooked_sqlite_connect(database, *args, **kwargs):
    """Refuse a writable open under a watched root. mode=ro URIs pass through."""
    uri = _connect_uri(args, kwargs)
    if not _sqlite_is_readonly(database, uri):
        path = _sqlite_fs_path(database, uri)
        if path is not None and _run is not None and not _in_hook:
            note = classify_write(path, _run.live_roots)
            if note is not None:
                _record(path)
                raise sqlite3.OperationalError(f"cache guard: refusing a writable SQLite open ({note})")
    return _real_sqlite_connect(database, *args, **kwargs)


def _install_write_hooks() -> None:
    global _hooks_on, _real_io_open
    if _hooks_on:
        return
    import builtins
    import io

    _real_io_open = io.open
    builtins.open = _hooked_builtin_open
    io.open = _hooked_io_open
    os.open = _hooked_os_open
    sqlite3.connect = _hooked_sqlite_connect
    _hooks_on = True


def _remove_write_hooks() -> None:
    global _hooks_on
    if not _hooks_on:
        return
    import builtins
    import io

    builtins.open = _real_builtin_open
    io.open = _real_io_open
    os.open = _real_os_open
    sqlite3.connect = _real_sqlite_connect
    _hooks_on = False


def push_root(label: str, path: Path) -> str:
    """Watch ``path`` for the rest of this run. ``pop_root`` drops its notes."""
    if _run is None:
        raise RuntimeError("cache guard is not running")
    _run.live_roots.append((label, path.resolve()))
    return label


def pop_root(label: str) -> list[str]:
    if _run is None:
        raise RuntimeError("cache guard is not running")
    _run.live_roots[:] = [(item, root) for item, root in _run.live_roots if item != label]
    prefix = label + " "
    mine = sorted(note for note in _run.notes if note.startswith(prefix))
    _run.notes.difference_update(mine)
    return mine


def current_run() -> _Run | None:
    return _run


def _begin() -> None:
    global _run
    _run = _Run(watched_roots())
    _install_write_hooks()


def _fail(result: unittest.TestResult, message: str) -> None:
    class CacheGuardCheck(unittest.TestCase):
        def test_run_leaves_the_cache_unchanged(self) -> None:
            pass

    case = CacheGuardCheck("test_run_leaves_the_cache_unchanged")
    try:
        raise AssertionError(message)
    except AssertionError:
        result.addFailure(case, sys.exc_info())


def _end(result: unittest.TestResult) -> None:
    global _run
    run = _run
    if run is None:
        _remove_write_hooks()
        return
    notes = sorted(run.notes)
    _remove_write_hooks()
    lines = list(notes)
    for label, root in run.endpoint_roots:
        lines.extend(diff_lines(label, run.before[label], snapshot_tree(root)))
    _run = None
    if not lines:
        return
    shown = lines[:200]
    extra = len(lines) - len(shown)
    message = "cache guard: the test run changed a real cache\n" + "\n".join(shown)
    if extra:
        message += f"\n... and {extra} more"
    _fail(result, message)


def _patch_result() -> None:
    from unittest.result import TestResult

    original_start = TestResult.startTestRun
    original_stop = TestResult.stopTestRun

    def startTestRun(self) -> None:
        global _depth
        if _depth == 0:
            _begin()
        _depth += 1
        original_start(self)

    def stopTestRun(self) -> None:
        global _depth
        try:
            _depth -= 1
            if _depth == 0:
                _end(self)
        finally:
            original_stop(self)

    TestResult.startTestRun = startTestRun  # type: ignore[method-assign]
    TestResult.stopTestRun = stopTestRun  # type: ignore[method-assign]


def install() -> None:
    """Point tool caches at a temp dir and arm the suite hook. Idempotent."""
    global _installed
    if _installed:
        return
    _installed = True
    _redirect_tool_caches()
    _patch_result()
