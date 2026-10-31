"""Fail a unittest run that writes under a real cache.

The suite reads PREACHED_CACHE. It must not create or change regular files
there. Tool caches (XDG_CACHE_HOME, DENO_DIR) are pointed at a temp directory
so deno and ONNX Runtime do not use /cache/xdg.

A before/after listing catches files left behind. Write-mode opens are
recorded as they happen, so a file created under the cache and removed
before the run ends still fails the run.
"""

from __future__ import annotations

import atexit
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

# Top-level directories that other tools rewrite. SQLite sidecars change when
# a read-only connection opens the index. Everything else must stay put.
_EXCLUDED_DIRS = frozenset({"uv", "uv-python", "venvs", "xdg", "demo-kill"})
_REAL_CACHE = Path("/cache")

_installed = False
_tool_root: Path | None = None
_depth = 0
_run: "_Run | None" = None
_real_builtin_open = open
_real_os_open = os.open
_real_io_open = None
_hooks_on = False
_in_hook = False


class _Run:
    def __init__(self, roots: list[tuple[str, Path]]) -> None:
        self.endpoint_roots = list(roots)
        self.live_roots = list(roots)
        self.before = {label: snapshot_tree(root) for label, root in roots}
        self.notes: set[str] = set()


def _ignored_rel(rel: str) -> bool:
    if not rel or rel == ".":
        return True
    head = rel.split("/", 1)[0]
    if head in _EXCLUDED_DIRS:
        return True
    name = rel.rsplit("/", 1)[-1]
    return name.endswith("-shm") or name.endswith("-wal")


def snapshot_tree(root: Path) -> dict[str, tuple[int, int]]:
    """Relative path -> (size, mtime_ns) for regular files under ``root``.

    Symlinks are not followed and are not listed. Excluded directories are
    not walked. The snapshot only stats; it does not write.
    """
    listing: dict[str, tuple[int, int]] = {}
    base = os.fspath(root)
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        rel_dir = os.path.relpath(dirpath, base)
        if rel_dir == ".":
            dirnames[:] = [name for name in dirnames if name not in _EXCLUDED_DIRS]
            prefix = ""
        else:
            prefix = rel_dir.replace(os.sep, "/") + "/"
            dirnames[:] = [name for name in dirnames if not _ignored_rel(prefix + name)]
        for name in filenames:
            rel = name if not prefix else prefix + name
            if _ignored_rel(rel):
                continue
            path = os.path.join(dirpath, name)
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            listing[rel] = (st.st_size, st.st_mtime_ns)
    return listing


def diff_lines(label: str, before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> list[str]:
    lines = []
    for rel in sorted(set(before) | set(after)):
        if rel not in before:
            size, mtime = after[rel]
            lines.append(f"{label} added {rel} size={size} mtime_ns={mtime}")
        elif rel not in after:
            size, mtime = before[rel]
            lines.append(f"{label} removed {rel} size={size} mtime_ns={mtime}")
        elif before[rel] != after[rel]:
            bsize, bmtime = before[rel]
            asize, amtime = after[rel]
            lines.append(f"{label} changed {rel} size={bsize}->{asize} mtime_ns={bmtime}->{amtime}")
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
