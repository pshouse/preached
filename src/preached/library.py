"""Which SQLite file is a library, and which one is the user's church.

Each library is still its own file (``/cache/index/<slug>.sqlite``). A search
reads one connection, so rows from another file cannot appear in its hits.
The church mark is a row in the ``meta`` table that file already has. There
is no combined index and no new database.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from pathlib import Path

from preached.libraries import PUBLIC_DOMAIN, SIDECAR_SUFFIXES, canonical_index, classic_index_problem
from preached.store import migrate, open_readonly

# meta.key. One file holds role=church. Import --your-church clears the others.
ROLE_KEY = "role"
ROLE_CHURCH = "church"
LABEL_KEY = "label"
SAMPLE_KEY = "sample"

CHURCH_EMPTY = "Nothing from your church yet."
CHURCH_LABEL = "Your church"
CLASSIC_LABEL = "John Wesley"
SAMPLE_SLUG = "sample"


def classic_names() -> tuple[str, ...]:
    """Wesley, then #14's public-domain allow-list. Not a second copy of the names."""
    return ("wesley", *PUBLIC_DOMAIN)


def _classic_church_error(name: str) -> str:
    listed = ", ".join(classic_names())
    return f"error: {name} is a classic library ({listed}) and cannot be your church"


def _hardlink_church_error(name: str, links: int) -> str:
    return (
        f"error: {name} has {links} hard links, so another name may point at the same file; "
        "a church library must have exactly one. It is not marked"
    )


def set_meta(connection: sqlite3.Connection, key: str, value: str) -> None:
    """Insert or replace one meta row. Does not commit."""
    connection.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_meta(connection: sqlite3.Connection, key: str) -> str | None:
    """Meta value, or None when the table or the key is missing."""
    try:
        row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    except sqlite3.Error:
        return None
    if row is None or row[0] is None:
        return None
    text = str(row[0]).strip()
    return text or None


def mark_your_church(
    connection: sqlite3.Connection,
    *,
    label: str | None = None,
    sample: bool = False,
) -> None:
    """Flag this open library as the user's church. Does not commit."""
    set_meta(connection, ROLE_KEY, ROLE_CHURCH)
    if label:
        set_meta(connection, LABEL_KEY, label)
    if sample:
        set_meta(connection, SAMPLE_KEY, "1")


def clear_church_role(connection: sqlite3.Connection) -> None:
    """Drop the church mark. Does not commit. A classic library is unchanged."""
    connection.execute(
        "DELETE FROM meta WHERE key = ? AND value = ?",
        (ROLE_KEY, ROLE_CHURCH),
    )


def is_your_church(connection: sqlite3.Connection) -> bool:
    return get_meta(connection, ROLE_KEY) == ROLE_CHURCH


def read_label(connection: sqlite3.Connection | None) -> str | None:
    if connection is None:
        return None
    return get_meta(connection, LABEL_KEY)


def is_sample_library(slug: str | None, connection: sqlite3.Connection | None = None) -> bool:
    """True for the fixture slug ``sample`` or a file that recorded sample=1.

    Sample data is labelled on the page and in the CLI. A real church library
    leaves both unset.
    """
    if slug == SAMPLE_SLUG:
        return True
    if connection is None:
        return False
    return get_meta(connection, SAMPLE_KEY) == "1"


def classic_heading(connection: sqlite3.Connection | None, slug: str) -> str:
    label = read_label(connection) or (CLASSIC_LABEL if slug == "wesley" else slug)
    return f"Classic library: {label}"


def is_classic_slug(slug: str | None) -> bool:
    """True for wesley and #14's public-domain allow-list (spurgeon, edwards)."""
    if not isinstance(slug, str):
        return False
    folded = slug.casefold()
    return any(folded == name for name in classic_names())


def classic_church_refusal(slug: str | None, path: Path | None = None) -> str | None:
    """Error text when this target cannot be the church, else None.

    An explicit ``--church-library wesley`` (or spurgeon, edwards) and a
    church index whose name, canonical path, or inode is one of those
    libraries are refused as a classic. Spurgeon and edwards go through
    ``libraries.PUBLIC_DOMAIN`` and ``classic_index_problem``. A church index
    with more than one link gets its own hardlink message. The file is not
    opened. The server and ``search/query.py`` raise ``SystemExit`` with
    this text; neither scans the index directory for a mark.
    """
    if is_classic_slug(slug):
        return _classic_church_error(slug)
    if path is None:
        return None
    reason = _protection(path)
    if reason == "classic":
        return _classic_church_error(slug or Path(path).name)
    if reason is not None:
        return _hardlink_church_error(slug or Path(path).name, _links(path))
    return None


def church_heading(connection: sqlite3.Connection | None, slug: str | None) -> str:
    """Column title. Sample libraries keep the words "sample data"."""
    if connection is None:
        return CHURCH_LABEL
    label = read_label(connection) or CHURCH_LABEL
    if is_sample_library(slug, connection) and "sample data" not in label.casefold():
        return f"{label} (sample data)"
    return label


def _is_church_file(path: Path) -> bool:
    """Read-only. False, without opening it, when a sidecar is unsafe (``_sidecar_problem``)."""
    if _sidecar_problem(path) is not None:
        return False
    try:
        connection = open_readonly(path)
    except (OSError, sqlite3.Error):
        return False
    try:
        return is_your_church(connection)
    except sqlite3.Error:
        return False
    finally:
        connection.close()


def church_index_matches(index_dir: Path, *, exclude: Path | None = None) -> list[Path]:
    """Library files under ``index_dir`` whose meta role is church.

    ``exclude`` is the classic index. It is never the church side, even if
    something marked it. Unreadable files are skipped. The list is sorted.
    """
    root = Path(index_dir)
    if not root.is_dir():
        return []
    excluded = _resolve(exclude) if exclude is not None else None
    found: list[Path] = []
    for candidate in sorted(root.glob("*.sqlite")):
        if not candidate.is_file():
            continue
        # Never open a classic index just to see if it was marked. Opening
        # it for writing migrates the schema; skipping here means the scan
        # does not touch the file at all.
        if is_protected_classic(candidate):
            continue
        resolved = _resolve(candidate)
        if resolved is None:
            continue
        if excluded is not None and resolved == excluded:
            continue
        if _is_church_file(candidate):
            found.append(candidate)
    return found


def find_church_index(index_dir: Path, *, exclude: Path | None = None) -> Path | None:
    """The one marked church file, or None when there are zero or several.

    Several marks is not a guess: the caller leaves the church side empty
    until ``--church-library`` names one.
    """
    found = church_index_matches(index_dir, exclude=exclude)
    if len(found) == 1:
        return found[0]
    return None


def resolve_church_path(
    index_dir: Path,
    *,
    classic: Path | None = None,
    church_index: Path | None = None,
    church_library: str | None = None,
) -> Path | None:
    """The church file to open, or None when that side should be the empty state.

    An explicit path wins, then a slug, then the single marked file. A missing
    file is None, not an error. The classic index is never returned.
    """
    classic_resolved = _resolve(classic) if classic is not None else None
    if church_index is not None:
        path: Path | None = Path(church_index)
    elif church_library:
        path = Path(index_dir) / f"{church_library}.sqlite"
    else:
        path = find_church_index(index_dir, exclude=classic)
    if path is None or not path.is_file():
        return None
    resolved = _resolve(path)
    if resolved is None:
        return None
    if classic_resolved is not None and resolved == classic_resolved:
        return None
    return path


def mark_your_church_exclusive(
    path: Path,
    index_dir: Path,
    *,
    sample: bool = False,
    label: str | None = None,
) -> list[tuple[Path, str]]:
    """Mark ``path`` as the church and clear that mark on any sibling file.

    Returns the sibling files still marked ``role=church`` that were not
    cleared, each with the reason, so the importer can say so.

    Classic libraries (wesley, spurgeon, edwards: by name, path, or the same
    inode through a hardlink) are not opened for writing. Nor is a file with
    more than one link, or one that does not look like a church import
    (``church_shaped``): a Wesley-shaped file, or one whose ``meta.library``
    names a classic. Those checks name a path, and the name can be swapped
    for a link to wesley.sqlite before the file is opened. So every write
    goes through ``_Checked``: no -wal, -shm or -journal file may be a
    symlink, a hardlink, or a classic file (``_sidecar_problem``, else
    ``UnsafeOpen``); the descriptor SQLite actually opened must have one
    link and must not be a classic file; and the church shape is read again
    through that connection, before the first write.

    The target is opened and checked first and held open; then the siblings
    are cleared; then the target is migrated and marked.

    Siblings are cleared with a plain ``sqlite3`` connection, which does not
    migrate and does not change the journal mode. The target is the church
    file this import just wrote, so it is migrated (``store.migrate``).
    """
    target = Path(path).resolve()
    reason = _protection(target)
    if reason == "classic":
        raise ValueError(_classic_church_error(target.name))
    if reason is not None:
        raise ValueError(_hardlink_church_error(target.name, _links(target)))
    sidecar = _sidecar_problem(target)
    if sidecar is not None:
        raise UnsafeOpen(target, sidecar)
    if not church_shaped(target):
        raise ValueError(f"error: {target.name} is not a church import (no videos table); it is not marked")
    # The target is opened and checked first, and held, so a target that
    # fails changes no sibling.
    checked = _Checked(target)
    try:
        problem = _church_shape_problem(checked.connection)
        if problem is not None:
            raise ValueError(f"error: {target.name} {problem}; it is not marked")
        skipped = _marked_siblings_not_cleared(index_dir, target)
        for candidate in church_index_matches(index_dir, exclude=target):
            if is_protected_classic(candidate):
                continue
            # The scans above checked its sidecars by name; one made unsafe
            # since then is reported, not passed over by church_shaped.
            sidecar = _sidecar_problem(candidate)
            if sidecar is not None:
                if all(path != candidate for path, _ in skipped):
                    skipped.append((candidate, f"{sidecar} (not opened)"))
                continue
            if not church_shaped(candidate):
                continue
            problem = _clear_church_mark(candidate)
            if problem is not None:
                skipped.append((candidate, problem))
        # The switch to WAL opens -wal and -shm; check them before the schema
        # and the mark are written.
        checked.recheck()
        checked.connection.execute("PRAGMA journal_mode=WAL")
        checked.connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
        checked.recheck()
        migrate(checked.connection)
        mark_your_church(checked.connection, label=label, sample=sample)
        checked.recheck()
        checked.connection.commit()
    finally:
        checked.close()
    return sorted(skipped)


def _marked_siblings_not_cleared(index_dir: Path, target: Path) -> list[tuple[Path, str]]:
    """Marked files ``church_index_matches`` leaves out, other than classics.

    A classic library is never opened. A file with an unsafe sidecar
    (``_sidecar_problem``) is never opened either; it is listed whether or
    not it is marked. A hardlinked or non-church-shaped file is opened
    read-only to see whether it carries ``role=church``.
    """
    root = Path(index_dir)
    if not root.is_dir():
        return []
    found: list[tuple[Path, str]] = []
    for candidate in sorted(root.glob("*.sqlite")):
        if not candidate.is_file() or _resolve(candidate) == target:
            continue
        reason = _protection(candidate)
        if reason == "classic":
            continue
        sidecar = _sidecar_problem(candidate)
        if sidecar is not None:
            # Not opened, even read-only, so its mark is not known.
            found.append((candidate, f"{sidecar} (not opened)"))
            continue
        if reason is not None:
            why = f"has {_links(candidate)} hard links"
        elif not church_shaped(candidate):
            why = "is not a church import"
        else:
            continue
        if _is_church_file(candidate):
            found.append((candidate, why))
    return found


def _classic_files() -> list[Path]:
    """Where the classic indexes live: Wesley (``paths.INDEX_PATH`` and
    ``INDEX_DIR/wesley.sqlite``, read at call time) and #14's canonical
    public-domain files."""
    from preached import paths

    return [paths.INDEX_PATH, paths.INDEX_DIR / "wesley.sqlite", *(canonical_index(slug) for slug in PUBLIC_DOMAIN)]


def _classic_ids() -> set[tuple[int, int]]:
    """(st_dev, st_ino) of every classic file that exists now."""
    ids = set()
    for candidate in _classic_files():
        ident = _file_id(candidate)
        if ident is not None:
            ids.add(ident[:2])
    return ids


def _links(path: Path) -> int:
    ident = _file_id(path)
    return ident[2] if ident is not None else 0


def _file_id(path: Path) -> tuple[int, int, int] | None:
    """(st_dev, st_ino, st_nlink) of the file ``path`` names, following symlinks."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_dev, st.st_ino, st.st_nlink


def is_protected_classic(path: Path) -> bool:
    """True for a classic slug, a classic index file, or any hardlinked file.

    The stem check covers a copy (``/tmp/wesley.sqlite``). A path is
    compared with the classic files (``_classic_files``) by realpath and by
    ``(st_dev, st_ino)``, so a hardlink to wesley.sqlite or spurgeon.sqlite
    under another name is that classic. A file with more than one link is
    protected too: its other name may be a classic this process does not
    know about. The file is not opened.
    """
    return _protection(path) is not None


def _protection(path: Path) -> str | None:
    """``"classic"``, ``"hardlink"`` (more than one link, no known classic), or None."""
    if is_classic_slug(Path(path).stem):
        return "classic"
    resolved = _resolve(path)
    if resolved is None:
        return None
    ident = _file_id(path)
    for candidate in _classic_files():
        canonical = _resolve(candidate)
        if canonical is not None and resolved == canonical:
            return "classic"
        other = _file_id(candidate)
        if ident is not None and other is not None and ident[:2] == other[:2]:
            return "classic"
    for slug in PUBLIC_DOMAIN:
        # None means #14 would serve this path as that classic library.
        if classic_index_problem(slug, path) is None:
            return "classic"
    if ident is not None and ident[2] > 1:
        return "hardlink"
    return None


def church_shaped(path: Path) -> bool:
    """True when ``path`` holds a church import (``_church_shape_problem``).

    Read-only (``store.open_readonly``). Anything unreadable is not
    church-shaped, so it is not written. A file with an unsafe sidecar
    (``_sidecar_problem``) is not opened and is not church-shaped.
    """
    if _sidecar_problem(Path(path)) is not None:
        return False
    try:
        connection = open_readonly(Path(path))
    except (OSError, sqlite3.Error):
        return False
    try:
        return _church_shape_problem(connection) is None
    finally:
        connection.close()


def _church_shape_problem(connection: sqlite3.Connection, *, busy_pauses: bool = False) -> str | None:
    """None when the open file has a ``videos`` table and a ``chunks.video_id``
    column, with no ``meta.library`` naming a classic.

    Wesley's index has neither table nor column; build_library.py records
    its slug in ``meta.library``. With ``busy_pauses``, a writer's lock
    (``is_busy``) raises ``ChurchPaused`` instead of giving a problem.
    """
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "videos" not in tables or "chunks" not in tables:
            return "is not a church import (no videos table)"
        columns = {row[1] for row in connection.execute("PRAGMA table_info(chunks)")}
        if "video_id" not in columns:
            return "is not a church import (no chunks.video_id)"
        if is_classic_slug(get_meta(connection, "library")):
            return "is a classic library build (meta.library)"
    except sqlite3.Error as exc:
        if busy_pauses and is_busy(exc):
            raise ChurchPaused(f"the church file is locked by a writer ({exc})") from exc
        return f"cannot be read ({exc})"
    return None


def _descriptors() -> dict[int, os.stat_result]:
    """``{fd: fstat}`` for every descriptor open in this process. The one
    ``listdir`` used is closed by the time it returns, so ``fstat`` drops it."""
    found = {}
    for name in os.listdir("/dev/fd"):
        try:
            fd = int(name)
            found[fd] = os.fstat(fd)
        except (OSError, ValueError):
            continue
    return found


def _new_files(before: dict[int, os.stat_result]) -> tuple[list[os.stat_result], dict[int, os.stat_result]]:
    """Regular files open now that were not open in ``before``, and the new snapshot.

    A descriptor number that was open before but now names another
    ``(st_dev, st_ino)`` was closed and reused, so it counts as new.
    """
    now = _descriptors()
    opened = []
    for fd, st in sorted(now.items()):
        old = before.get(fd)
        if old is not None and (old.st_dev, old.st_ino) == (st.st_dev, st.st_ino):
            continue
        if stat.S_ISREG(st.st_mode):
            opened.append(st)
    return opened, now


def _one_new_file(before: dict[int, os.stat_result]) -> tuple[os.stat_result, dict[int, os.stat_result]]:
    """The one regular file opened since ``before`` (``_new_files``), and the new snapshot.

    SQLite opens the main database file when it connects, before any read,
    so a connect opens exactly one. Raises ``ValueError`` (the reason, no
    file name) for none or more than one.
    """
    opened, now = _new_files(before)
    if not opened:
        raise ValueError("could not be checked once opened (no new descriptor)")
    if len(opened) != 1:
        raise ValueError(f"could not be checked once opened ({len(opened)} new files, not 1)")
    return opened[0], now


def _sidecar_problem(path: Path) -> str | None:
    """Why a -wal, -shm or -journal file next to ``path`` makes it unsafe to open, or None.

    SQLite opens those by name (``libraries.SIDECAR_SUFFIXES``), after any
    check on the main file, and writes them, even from a read-only
    connection (the -shm index). One that is a hardlink to wesley.sqlite
    makes SQLite write into Wesley, then delete the name, so nothing shows
    afterwards. Each one that exists must be a regular file, not a symlink,
    with one link, and not a classic file (``_classic_ids``). Both the name
    given and its realpath are checked, since SQLite resolves symlinks in
    the database path. Nothing is opened.
    """
    bases = dict.fromkeys([os.path.abspath(path), os.path.realpath(path)])
    classic = None
    for base in bases:
        for suffix in SIDECAR_SUFFIXES:
            try:
                st = os.lstat(f"{base}{suffix}")
            except FileNotFoundError:
                continue
            except OSError as exc:
                return f"has a {suffix} file that cannot be checked ({exc.strerror})"
            if stat.S_ISLNK(st.st_mode):
                return f"has a {suffix} file that is a symlink"
            if not stat.S_ISREG(st.st_mode):
                return f"has a {suffix} file that is not a regular file"
            if st.st_nlink != 1:
                return f"has a {suffix} file with {st.st_nlink} hard links"
            if classic is None:
                classic = _classic_ids()
            if (st.st_dev, st.st_ino) in classic:
                return f"has a {suffix} file that is a classic library file"
    return None


class UnsafeOpen(ValueError):
    """The file SQLite opened is not one this module may write. ``why`` has no file name."""

    def __init__(self, path: Path, why: str) -> None:
        super().__init__(f"error: {Path(path).name} {why}; it is not written")
        self.why = why


def _rw_uri(path: Path) -> str:
    """``file:`` URI for ``path`` with ``mode=rw``: SQLite opens it read-write
    but never creates it, so a dangling symlink swapped in creates nothing."""
    return Path(os.path.abspath(path)).as_uri() + "?mode=rw"


class _Checked:
    """A plain read-write connection to ``path``, refused unless every file SQLite opened is safe.

    Before the open, the sidecars are checked by name (``_sidecar_problem``).
    SQLite opens the main database file when it connects, before any read.
    The descriptors open across ``sqlite3.connect`` are compared with a
    ``{fd: (st_dev, st_ino)}`` snapshot (a reused number counts as new).
    Exactly one new regular file must appear, it must be the file
    ``os.stat(path)`` names after the connect, and it must have one link and
    not be a classic file (``_classic_ids``). That is the file every later
    write goes to, whatever the name points at by then. Then one read runs
    (in WAL mode that opens -wal and -shm) and ``recheck`` runs. Callers
    call ``recheck`` again before a step that opens a new sidecar (the switch
    to WAL). Raises ``UnsafeOpen``.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        problem = _sidecar_problem(self.path)
        if problem is not None:
            raise UnsafeOpen(self.path, problem)
        before = _descriptors()
        try:
            self.connection = sqlite3.connect(_rw_uri(self.path), uri=True)
        except sqlite3.Error as exc:
            raise UnsafeOpen(self.path, f"could not be opened for writing ({exc})") from exc
        try:
            try:
                opened, self._seen = _one_new_file(before)
            except ValueError as exc:
                raise UnsafeOpen(self.path, str(exc)) from None
            try:
                named = os.stat(self.path)
            except OSError as exc:
                raise UnsafeOpen(self.path, f"could not be checked once opened ({exc.strerror})") from exc
            self._refuse_file(opened, sidecar=False)
            if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
                raise UnsafeOpen(self.path, "is not the file SQLite opened (the name changed)")
            self.connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
            self.recheck()
        except BaseException:
            self.connection.close()
            raise

    def _refuse_file(self, st: os.stat_result, *, sidecar: bool) -> None:
        if st.st_nlink != 1:
            what = "a sidecar with " if sidecar else ""
            raise UnsafeOpen(self.path, f"has {what}{st.st_nlink} hard links once opened")
        if (st.st_dev, st.st_ino) in _classic_ids():
            what = "has a sidecar that is" if sidecar else "is"
            raise UnsafeOpen(self.path, f"{what} a classic library file once opened")

    def recheck(self) -> None:
        """Files SQLite opened since the last check (the -wal, -shm, a hot
        journal) get the same checks, and the sidecar names are checked again."""
        problem = _sidecar_problem(self.path)
        if problem is not None:
            raise UnsafeOpen(self.path, problem)
        opened, self._seen = _new_files(self._seen)
        for st in opened:
            self._refuse_file(st, sidecar=True)

    def close(self) -> None:
        self.connection.close()


def _clear_church_mark(path: Path) -> str | None:
    """Drop ``role=church`` without migrating the file or enabling WAL.

    ``store.connect`` runs the schema script and ``PRAGMA journal_mode=WAL``.
    A plain connection does neither. The journal mode already on the file
    stays as it is. Callers check ``is_protected_classic`` and
    ``church_shaped`` first; the open file is checked again here
    (``_Checked``, ``_church_shape_problem``) before the delete.
    Returns why the mark was left in place, or None when it was cleared.
    """
    try:
        checked = _Checked(path)
    except UnsafeOpen as exc:
        return exc.why
    try:
        problem = _church_shape_problem(checked.connection)
        if problem is not None:
            return problem
        try:
            checked.recheck()
        except UnsafeOpen as exc:
            return exc.why
        clear_church_role(checked.connection)
        checked.connection.commit()
    finally:
        checked.close()
    return None


def _resolve(path: Path | None) -> Path | None:
    if path is None:
        return None
    try:
        return Path(path).resolve()
    except OSError:
        return None


class ChurchRefused(ValueError):
    """The church file is not searched. The message is the logged refusal."""


class ChurchPaused(Exception):
    """The church file is in WAL mode or locked by a writer (``--ack-review``): skip this search."""


class ChurchStartPaused(ChurchRefused):
    """``open_church_readonly`` could not open the file because it is in WAL
    mode or locked by a writer (``--ack-review`` running). The message is the
    refusal a one-shot caller (``search/query.py --side``) prints; ``reason``
    is the pause reason the server logs before it retries the open later
    (CTO #37 r3 hard condition 1)."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


def is_busy(exc: BaseException) -> bool:
    """True for SQLITE_BUSY or SQLITE_LOCKED (any extended code): another
    connection holds a lock. The church connection waits for none
    (``busy_timeout = 0``)."""
    code = getattr(exc, "sqlite_errorcode", None)
    return isinstance(exc, sqlite3.OperationalError) and code is not None and code & 0xFF in (5, 6)


def _owners() -> set[int] | None:
    return {0, os.geteuid()} if hasattr(os, "geteuid") else None


def _ancestor_problem(path: Path) -> str | None:
    """Why a directory above the church file would let another user swap it, or None.

    A user who can write any directory on the way to the file can rename a
    directory below it and put another file under the same name (PR #37
    r2 must-fix 2). Every directory from ``/`` down, on the name given
    (each component ``lstat``-ed, not followed) and on the real path, must
    be owned by the serving euid or root and must not be group- or
    world-writable. One exception: a root-owned sticky directory (``/tmp``)
    whose next component is owned by the serving euid or root, since
    sticky stops others renaming what they do not own. A symlink component
    is checked for owner only; its target is on the real path, walked too.
    """
    owners = _owners()
    for chain in dict.fromkeys([os.path.abspath(path), os.path.realpath(path)]):
        parts = Path(chain).parts
        components = [Path(*parts[: i + 1]) for i in range(len(parts))]
        for directory, below in zip(components, components[1:]):
            try:
                st = os.lstat(directory)
            except OSError as exc:
                return f"directory {directory} above the church file cannot be checked ({exc.__class__.__name__})"
            if owners is not None and st.st_uid not in owners:
                return f"directory {directory} above the church file is owned by uid {st.st_uid}, not the serving uid or root"
            if stat.S_ISLNK(st.st_mode) or not st.st_mode & 0o022:
                continue
            if st.st_uid == 0 and st.st_mode & stat.S_ISVTX and owners is not None:
                try:
                    below_uid = os.lstat(below).st_uid
                except OSError as exc:
                    return f"directory {below} in sticky directory {directory} cannot be checked ({exc.__class__.__name__})"
                if below_uid in owners:
                    continue
                # Sticky stops others renaming only what they do not own: the
                # reason is the owner below, not the sticky directory's mode.
                return (
                    f"directory {below} in sticky directory {directory} is owned by uid {below_uid}, "
                    "not the serving uid or root"
                )
            return (
                f"directory {directory} above the church file is group- or world-writable "
                f"(mode {stat.S_IMODE(st.st_mode):o})"
            )
    return None


def _file_kind(mode: int) -> str:
    """What a non-regular file is, for a refusal (not 'not found': PR #37 r3 nit)."""
    for test, kind in (
        (stat.S_ISDIR, "a directory"),
        (stat.S_ISFIFO, "a FIFO"),
        (stat.S_ISCHR, "a character device"),
        (stat.S_ISBLK, "a block device"),
        (stat.S_ISSOCK, "a socket"),
    ):
        if test(mode):
            return kind
    return "not a regular file"


def _church_identity(path: Path) -> tuple[int, int] | None:
    ident = _file_id(path)
    return None if ident is None else ident[:2]


def church_path_problem(path: Path) -> str | None:
    """Why the church file's name, real file or real directory may not be served, or None.

    The name must not be a symlink (DEPLOY's rule for the classic library):
    a symlink lets a file in a directory other local users can write be
    served from a safe-looking one (PR #37 r1). The real file and the
    directory that really holds it must be owned by the serving uid or root
    and must not be group- or world-writable. So must every directory above
    it, on the name given and on the real path (``_ancestor_problem``).
    Never opens the file.
    """
    path = Path(path)
    try:
        if stat.S_ISLNK(os.lstat(path).st_mode):
            return f"{path.name} is a symlink; name the church file itself"
    except OSError as exc:
        return f"{path.name} cannot be checked ({exc.__class__.__name__})"
    real = Path(os.path.realpath(path))
    owners = _owners()
    for target, what in ((real, "church file"), (real.parent, "church file's directory")):
        try:
            st = os.stat(target)
        except OSError as exc:
            return f"{what} {target} cannot be checked ({exc.__class__.__name__})"
        if owners is not None and st.st_uid not in owners:
            return f"{what} {target} is owned by uid {st.st_uid}, not the serving uid or root"
        if st.st_mode & 0o022:
            return f"{what} {target} is group- or world-writable (mode {stat.S_IMODE(st.st_mode):o})"
    return _ancestor_problem(path)


def wal_mode(path: Path, identity: tuple[int, int] | None = None) -> bool | None:
    """True when the file's SQLite header says WAL; None when it cannot be read. Opens no database.

    The open never blocks and never follows a symlink (``O_NONBLOCK``,
    ``O_NOFOLLOW``): a FIFO swapped in under the name would block a plain
    ``open()`` forever, with the server's lock held (PR #37 r2 B). Only a
    regular file is read, and with ``identity`` only that
    ``(st_dev, st_ino)``; anything else gives None.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None
        if identity is not None and (st.st_dev, st.st_ino) != tuple(identity):
            return None
        header = os.pread(fd, 20, 0)
    except OSError:
        return None
    finally:
        os.close(fd)
    if len(header) < 20 or not header.startswith(b"SQLite format 3\x00"):
        return None
    return header[18] == 2 or header[19] == 2


def open_church_readonly(path: Path, *, classic: Path | None = None) -> tuple[sqlite3.Connection, tuple[int, int]]:
    """Open the church file read-only for search, or raise ``ChurchRefused``.

    Returns the connection and the file's ``(st_dev, st_ino)``; pass both to
    ``church_file_problem`` before every search. Nothing is written: the open
    is ``store.open_readonly`` (``mode=ro``, ``query_only``), which checks the
    -wal, -shm and -journal files first (``_sidecar_problem``, #33).

    Refused, in this order: no privacy config (``privacy.required_config``),
    a missing file, a classic or hardlinked file (``classic_church_refusal``),
    a symlinked name or a real file or directory with the wrong owner or
    mode (``church_path_problem``, every directory up to ``/``), a WAL-mode
    or non-regular file, the classic index itself, an unsafe sidecar, a
    file SQLite opened that is not the inode checked, a file that is not a
    church import (``_church_shape_problem``), a file without the
    publish-gate columns (``store.visible_sql`` gives ``"0"``), and a file
    replaced while it was opened. The connection never waits for a lock
    (``busy_timeout = 0``). Each one means the church side is empty; the caller logs
    the message and carries on with the classic side. WAL mode and a
    writer's lock (``--ack-review`` running) raise ``ChurchStartPaused``, a
    ``ChurchRefused`` whose ``reason`` the server logs as a pause before it
    retries the open later; a one-shot caller treats it as any refusal.
    """
    from preached.privacy import MissingConfig, required_config
    from preached.store import UnsafeSidecar, visible_sql

    path = Path(path)
    try:
        required_config()
    except MissingConfig as exc:
        raise ChurchRefused(f"{exc}; the church side is not searched") from exc
    except (ValueError, OSError) as exc:
        raise ChurchRefused(f"privacy config: {exc}; the church side is not searched") from exc
    try:
        mode = os.stat(path).st_mode
    except FileNotFoundError:
        raise ChurchRefused(f"{path.name} not found; the church side is empty") from None
    except OSError as exc:
        raise ChurchRefused(f"{path.name} cannot be checked ({exc.__class__.__name__}); it is not opened") from exc
    if not stat.S_ISREG(mode):
        raise ChurchRefused(f"{path.name} is not a regular file ({_file_kind(mode)}); it is not opened")
    refusal = classic_church_refusal(None, path) or church_path_problem(path)
    if refusal:
        raise ChurchRefused(refusal)
    identity = _church_identity(path)
    if identity is None:
        raise ChurchRefused(f"{path.name} cannot be checked; it is not opened")
    wal = wal_mode(path, identity)
    if wal is None:
        raise ChurchRefused(f"{path.name} cannot be read as the regular file that was checked; it is not opened")
    if wal:
        # A read-only open of a WAL file creates -wal and -shm beside it.
        # Approval (--ack-review) leaves the file in DELETE mode; while it
        # runs the file is in WAL mode, so the server waits (a pause).
        raise ChurchStartPaused(
            f"{path.name} is in WAL journal mode; run --ack-review (it leaves DELETE mode) before serving it",
            f"{path.name} is in WAL journal mode",
        )
    if classic is not None and identity == _church_identity(Path(classic)):
        raise ChurchRefused(f"{path.name} is the classic index; it cannot be your church")
    before = _descriptors()
    try:
        connection = open_readonly(path, check_same_thread=False)
    except UnsafeSidecar as exc:
        raise ChurchRefused(str(exc)) from exc
    except (OSError, sqlite3.Error) as exc:
        if is_busy(exc):
            reason = f"the church file is locked by a writer ({exc})"
            raise ChurchStartPaused(f"{reason}; it is not opened", reason) from exc
        raise ChurchRefused(f"{path.name} cannot be opened ({exc})") from exc
    problem = None
    paused = None
    try:
        # The name is re-resolved by the connect: the file SQLite opened must
        # be the one checked above (PR #37 r2 should-fix A, _Checked's check).
        try:
            opened, _now = _one_new_file(before)
            if (opened.st_dev, opened.st_ino) != identity:
                problem = f"{path.name} is not the file SQLite opened (the name changed); it is not opened"
        except ValueError as exc:
            problem = f"{path.name} {exc}; it is not opened"
        # A writer's lock pauses the church side; it never stalls the server.
        connection.execute("PRAGMA busy_timeout = 0")
        try:
            if problem is None:
                problem = church_file_problem(connection, path, identity)
        except ChurchPaused as exc:
            problem, paused = f"{exc}; it is not opened", str(exc)
        if problem is None and visible_sql(connection, "chunks", gated=True) == "0":
            problem = f"{path.name} has no publish-gate columns; nothing in it is served"
    except sqlite3.Error as exc:
        problem = f"{path.name} cannot be read ({exc})"
        if is_busy(exc):
            paused = f"the church file is locked by a writer ({exc})"
            problem = f"{paused}; it is not opened"
    if problem is not None:
        connection.close()
        if paused is not None:
            raise ChurchStartPaused(problem, paused)
        raise ChurchRefused(problem)
    return connection, identity


def church_file_problem(connection: sqlite3.Connection, path: Path, identity: tuple[int, int]) -> str | None:
    """Why the open church file may not be searched now, or None. Read-only.

    Run before every church search: ``church_path_problem`` (no symlink;
    owner and mode of the real file and directory), the name still points
    at the file that was opened (same ``(st_dev, st_ino)``, one link, not a classic), its
    sidecars are still safe (``_sidecar_problem``), and the open file still
    reads as a church import. A WAL-mode file raises ``ChurchPaused`` before
    anything is read, and so does a writer's lock (``is_busy``): skip this
    search, but it is not a refusal.
    """
    path = Path(path)
    problem = church_path_problem(path)
    if problem is not None:
        return f"{problem}; refused"
    if _church_identity(path) != identity:
        return f"{path.name} was replaced after it was opened; refused"
    reason = _protection(path)
    if reason == "classic":
        return _classic_church_error(path.name)
    if reason is not None:
        return _hardlink_church_error(path.name, _links(path))
    sidecar = _sidecar_problem(path)
    if sidecar is not None:
        return f"{path.name} {sidecar}; refused"
    wal = wal_mode(path, identity)
    if wal is None:
        return f"{path.name} cannot be read as the regular file that was opened; refused"
    if wal:
        # Before the first read: reading now would join the WAL (creating
        # -wal/-shm) and stop --ack-review's switch back to DELETE mode.
        raise ChurchPaused(f"{path.name} is in WAL journal mode")
    shape = _church_shape_problem(connection, busy_pauses=True)
    if shape is not None:
        return f"{path.name} {shape}; refused"
    return None
