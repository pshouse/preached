"""Fail a unittest run that writes under a real cache.

The six cache variables are PREACHED_CACHE, PREACHED_ONNX_DIR, HF_HOME,
DENO_DIR, XDG_CACHE_HOME, and UV_CACHE_DIR. The suite reads PREACHED_CACHE.
It must not create or change anything there. ``install`` points the tool
caches XDG_CACHE_HOME and DENO_DIR at a temp directory so deno and ONNX
Runtime do not use /cache/xdg. PREACHED_ONNX_DIR, HF_HOME, and UV_CACHE_DIR
stay as the process set them; a suite run points those at temp directories
too.

A before/after listing catches files left behind, including a same-size
replace, a chmod, a new symlink, an empty directory, and a SQLite -wal
file written by a connection that is still open. A file created under a
watched root and deleted before the run ends leaves no trace in that
listing (b2): the path is absent from both snapshots. Write-mode opens,
including the built-in ``open()``, are recorded as they happen, so that
create-then-delete still fails the run. Directory inode and mode are
compared, so a chmod or ``os.replace`` of a protected directory is caught
too. A writable sqlite3.connect under a watched root is refused. A URI is
left alone only when it has exactly one ``mode`` parameter and that value
is ``ro``; ``mode=ro&mode=rw``, ``mode=ro&mode=ro``, and any other mode
are refused. The ``mode`` key and value are exact: ``Mode`` and ``RO`` do
not match. An ``immutable`` parameter that SQLite would turn on is refused
as well, including a case-folded key or boolean word and a percent-encoded
key or value (``IMMUTABLE=1``, ``immutable=TRUE``, ``immutable=%31``,
``%69mmutable=1``). SQLite itself matches that key with strcmp and keeps
the first value; the guard refuses any enabling value.

Snap noise is only a regular file named ``<sibling>.box-store-snap-<digits>``
whose sibling entry is in the same directory. A directory of that name, a
symlink of that name, or a file of that name with no sibling is a real
entry and is not ignored.

Arming: ``install`` is idempotent per process, not per module object.
``tests.cache_guard`` and top-level ``cache_guard`` are one module: the
second import aliases itself to the first. A sentinel on
``unittest.result.TestResult`` stops a second ``install`` from wrapping
the result hooks again. The real ``builtins.open`` and ``io.open`` are
captured when that first instance is imported, and restore puts those
originals back. Every test module calls ``install`` with one import line,
so these invocations are armed: ``python -m unittest discover -s tests``
(including ``-p`` patterns that do not load ``test_cache_guard``),
``python -m unittest test_x`` with the working directory inside ``tests/``,
and ``python tests/test_x.py``. ``python -m unittest tests.<module>`` also
arms through this package's ``__init__``.
"""

from __future__ import annotations

import atexit
import builtins
import io
import os
import re
import sqlite3
import stat
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

# Second import name (tests.cache_guard vs top-level cache_guard) must not
# build its own hooks. The import system returns sys.modules[__name__] after
# this body finishes, so replacing that entry hands the caller the first copy.
_GUARD_MODULE = "_preached_cache_guard_module"
_GUARD_INSTALLED = "_preached_cache_guard_installed"


def _adopt_loaded_guard() -> None:
    """Alias this import name to the guard already loaded in the process."""
    me = sys.modules.get(__name__)
    for name in ("cache_guard", "tests.cache_guard"):
        other = sys.modules.get(name)
        if other is None or other is me:
            continue
        if getattr(other, _GUARD_MODULE, False):
            sys.modules[__name__] = other
            return
    if me is not None:
        setattr(me, _GUARD_MODULE, True)


_adopt_loaded_guard()

# Captured at import of the first instance, before any hook is installed.
# A second copy of this file may still execute, but its globals are discarded
# when the alias above wins, and install() refuses to hook twice. Restore
# always writes these originals back, including after a second run.
_real_builtin_open = builtins.open
_real_io_open = io.open
_real_os_open = os.open
_real_sqlite_connect = sqlite3.connect

# Top-level directories that other tools rewrite. -shm changes when a
# read-only connection opens a WAL index, so those sidecars are ignored.
# -wal is the log itself: an insert or update with the connection still
# open changes only that file. Snap noise is decided by _snap_noise_file,
# not by a name glob: a real directory or file must stay visible.
_EXCLUDED_DIRS = frozenset({"uv", "uv-python", "venvs", "xdg", "demo-kill"})
# <sibling>.box-store-snap-<digits>. The sibling group is non-empty.
_SNAP_FILE_RE = re.compile(r"^(.+)\.box-store-snap-(\d+)$")
_REAL_CACHE = Path("/cache")

_installed = False
_tool_root: Path | None = None
_depth = 0
_run: "_Run | None" = None
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
    # -shm only. -wal of a watched database is itself watched.
    # Snap names are not decided here. A directory, a symlink, or a real
    # file that merely looks like snap noise must stay visible, and that
    # depends on the parent directory and on the file type.
    return name.endswith("-shm")


def _snap_noise_file(directory: str, name: str) -> bool:
    """True when ``name`` is daemon noise beside its sibling.

    The entry must be a regular file named ``<sibling>.box-store-snap-<digits>``,
    and ``<sibling>`` must already be an entry in ``directory``. A directory
    or a symlink with that name is real. A file with that name and no sibling
    is real. A creating open of a not-yet-existing path is noise only when
    the sibling is already there, which is how the snapshot daemon writes.
    """
    match = _SNAP_FILE_RE.fullmatch(name)
    if match is None:
        return False
    path = os.path.join(directory, name)
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        pass
    else:
        # On disk and not a regular file: a directory or a symlink is real.
        if not stat.S_ISREG(mode):
            return False
    sibling = match.group(1)
    return os.path.lexists(os.path.join(directory, sibling))


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
            if _snap_noise_file(dirpath, name):
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
        if _snap_noise_file(os.fspath(resolved.parent), resolved.name):
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


def _sqlite_query_pairs(database: object) -> list[tuple[str, str]] | None:
    """Decoded query pairs, or None when ``database`` has no query string.

    Percent-encoding is decoded. ``+`` is a space, matching ``parse_qsl``.
    The fragment after ``#`` is not part of the query.
    """
    try:
        text = os.fspath(database)  # type: ignore[arg-type]
    except TypeError:
        return None
    if isinstance(text, bytes):
        text = os.fsdecode(text)
    if not isinstance(text, str) or "?" not in text:
        return None
    query = text.split("?", 1)[1].split("#", 1)[0]
    return urllib.parse.parse_qsl(query, keep_blank_values=True, separator="&")


def _sqlite_mode_values(database: object) -> list[str] | None:
    """Every ``mode`` query value, or None when ``database`` has no query string.

    The key and the value are exact. ``Mode`` is not ``mode``, and ``RO`` is
    not ``ro``. Repeated keys stay repeated: ``mode=ro&mode=ro`` is two values.
    """
    pairs = _sqlite_query_pairs(database)
    if pairs is None:
        return None
    return [value for key, value in pairs if key == "mode"]


def _sqlite_atoi(value: str) -> int:
    """SQLite's atoi: leading whitespace, an optional sign, then digits."""
    index = 0
    while index < len(value) and value[index] in " \t\n\r\v\f":
        index += 1
    if index >= len(value):
        return 0
    sign = 1
    if value[index] == "-":
        sign = -1
        index += 1
    elif value[index] == "+":
        index += 1
    number = 0
    saw_digit = False
    while index < len(value) and value[index].isdigit():
        saw_digit = True
        number = number * 10 + int(value[index])
        index += 1
        if number > 2**63:
            break
    if not saw_digit:
        return 0
    return sign * number


def _sqlite_uri_boolean(value: str) -> bool:
    """True when sqlite3_uri_boolean would enable a flag whose default is false.

    ``yes``, ``on``, and ``true`` (any case) are true. ``no``, ``off``, and
    ``false`` (any case) are false. Anything else follows atoi: non-zero is true.
    """
    folded = value.casefold()
    if folded in {"yes", "on", "true"}:
        return True
    if folded in {"no", "off", "false"}:
        return False
    return _sqlite_atoi(value) != 0


def _sqlite_immutable_enabled(database: object) -> bool:
    """True when any query parameter would turn SQLite's immutable flag on.

    The key is case-folded and the query is percent-decoded, so
    ``IMMUTABLE=1``, ``immutable=%31``, and ``%69mmutable=1`` all count.
    Every enabling value counts, not only the first. ``immutable=0`` and
    ``immutable=false`` do not.
    """
    pairs = _sqlite_query_pairs(database)
    if not pairs:
        return False
    return any(key.casefold() == "immutable" and _sqlite_uri_boolean(value) for key, value in pairs)


def _sqlite_is_readonly(database: object, uri: bool) -> bool:
    """True only for a URI with exactly one mode parameter whose value is ``ro``."""
    if not uri:
        return False
    modes = _sqlite_mode_values(database)
    return modes is not None and len(modes) == 1 and modes[0] == "ro"


def _hooked_sqlite_connect(database, *args, **kwargs):
    """Refuse a writable or immutable open under a watched root.

    A URI with exactly one ``mode=ro`` passes through. ``immutable=1`` does
    not, including case and percent-encoding variants. An immutable URI
    outside a watched root is left alone.
    """
    uri = _connect_uri(args, kwargs)
    immutable = bool(uri) and _sqlite_immutable_enabled(database)
    if immutable or not _sqlite_is_readonly(database, uri):
        path = _sqlite_fs_path(database, uri)
        if path is not None and _run is not None and not _in_hook:
            note = classify_write(path, _run.live_roots)
            if note is not None:
                _record(path)
                if immutable:
                    raise sqlite3.OperationalError(
                        f"cache guard: refusing an immutable SQLite open ({note})"
                    )
                raise sqlite3.OperationalError(
                    f"cache guard: refusing a writable SQLite open ({note})"
                )
    return _real_sqlite_connect(database, *args, **kwargs)


def _install_write_hooks() -> None:
    global _hooks_on
    if _hooks_on:
        return
    # Rebind both names. io.open and builtins.open start as one object, so
    # replacing only io.open would leave open() unhooked.
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
    """Point tool caches at a temp dir and arm the suite hook.

    Idempotent per process. A second module object shares this one's hooks
    via the import alias, and the TestResult sentinel stops a second wrap
    if that alias was not the module the caller invoked.
    """
    from unittest.result import TestResult

    global _installed
    if getattr(TestResult, _GUARD_INSTALLED, False):
        _installed = True
        return
    setattr(TestResult, _GUARD_INSTALLED, True)
    _installed = True
    _redirect_tool_caches()
    _patch_result()
