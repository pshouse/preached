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

from preached.libraries import PUBLIC_DOMAIN, canonical_index, classic_index_problem
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
    goes through ``_open_checked``: the descriptor SQLite actually opened
    must have one link and must not be a classic file, and the church shape
    is read again through that connection, before the first write.

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
    if not church_shaped(target):
        raise ValueError(f"error: {target.name} is not a church import (no videos table); it is not marked")
    skipped = _marked_siblings_not_cleared(index_dir, target)
    for candidate in church_index_matches(index_dir, exclude=target):
        if is_protected_classic(candidate) or not church_shaped(candidate):
            continue
        problem = _clear_church_mark(candidate)
        if problem is not None:
            skipped.append((candidate, problem))
    connection = _open_checked(target)
    try:
        problem = _church_shape_problem(connection)
        if problem is not None:
            raise ValueError(f"error: {target.name} {problem}; it is not marked")
        migrate(connection)
        mark_your_church(connection, label=label, sample=sample)
        connection.commit()
    finally:
        connection.close()
    return sorted(skipped)


def _marked_siblings_not_cleared(index_dir: Path, target: Path) -> list[tuple[Path, str]]:
    """Marked files ``church_index_matches`` leaves out, other than classics.

    A classic library is never opened. A hardlinked or non-church-shaped file
    is opened read-only to see whether it carries ``role=church``.
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
    church-shaped, so it is not written.
    """
    try:
        connection = open_readonly(Path(path))
    except (OSError, sqlite3.Error):
        return False
    try:
        return _church_shape_problem(connection) is None
    finally:
        connection.close()


def _church_shape_problem(connection: sqlite3.Connection) -> str | None:
    """None when the open file has a ``videos`` table and a ``chunks.video_id``
    column, with no ``meta.library`` naming a classic.

    Wesley's index has neither table nor column; build_library.py records
    its slug in ``meta.library``.
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
        return f"cannot be read ({exc})"
    return None


def _open_descriptors() -> set[int]:
    """Descriptors open in this process. The one ``listdir`` used is closed
    by the time it returns, so ``fstat`` drops it."""
    found = set()
    for name in os.listdir("/dev/fd"):
        try:
            os.fstat(int(name))
        except (OSError, ValueError):
            continue
        found.add(int(name))
    return found


class UnsafeOpen(ValueError):
    """The file SQLite opened is not one this module may write. ``why`` has no file name."""

    def __init__(self, path: Path, why: str) -> None:
        super().__init__(f"error: {Path(path).name} {why}; it is not written")
        self.why = why


def _open_checked(path: Path) -> sqlite3.Connection:
    """A plain connection to ``path``, refused unless the file SQLite opened is safe.

    SQLite opens the main database file when it connects, before any read
    (the -wal and -shm files come later). The descriptors that appeared
    across ``sqlite3.connect`` are fstat'ed: each must be a regular file
    with one link whose ``(st_dev, st_ino)`` is not a classic file
    (``_classic_ids``). That is the file every later write goes to, whatever
    the name points at by then. No new descriptor means nothing could be
    checked, which is refused too. Raises ``UnsafeOpen``.
    """
    before = _open_descriptors()
    connection = sqlite3.connect(path)
    try:
        opened = []
        for fd in sorted(_open_descriptors() - before):
            try:
                st = os.fstat(fd)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                opened.append(st)
        if not opened:
            raise UnsafeOpen(path, "could not be checked once opened (no new descriptor)")
        classic = _classic_ids()
        for st in opened:
            if st.st_nlink != 1:
                raise UnsafeOpen(path, f"has {st.st_nlink} hard links once opened")
            if (st.st_dev, st.st_ino) in classic:
                raise UnsafeOpen(path, "is a classic library file once opened")
    except BaseException:
        connection.close()
        raise
    return connection


def _clear_church_mark(path: Path) -> str | None:
    """Drop ``role=church`` without migrating the file or enabling WAL.

    ``store.connect`` runs the schema script and ``PRAGMA journal_mode=WAL``.
    A plain connection does neither. The journal mode already on the file
    stays as it is. Callers check ``is_protected_classic`` and
    ``church_shaped`` first; the open file is checked again here
    (``_open_checked``, ``_church_shape_problem``) before the delete.
    Returns why the mark was left in place, or None when it was cleared.
    """
    try:
        connection = _open_checked(path)
    except UnsafeOpen as exc:
        return exc.why
    try:
        problem = _church_shape_problem(connection)
        if problem is not None:
            return problem
        clear_church_role(connection)
        connection.commit()
    finally:
        connection.close()
    return None


def _resolve(path: Path | None) -> Path | None:
    if path is None:
        return None
    try:
        return Path(path).resolve()
    except OSError:
        return None
