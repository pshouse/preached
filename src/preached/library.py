"""Which SQLite file is a library, and which one is the user's church.

Each library is still its own file (``/cache/index/<slug>.sqlite``). A search
reads one connection, so rows from another file cannot appear in its hits.
The church mark is a row in the ``meta`` table that file already has. There
is no combined index and no new database.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from preached.libraries import PUBLIC_DOMAIN, canonical_index, classic_index_problem
from preached.store import connect, open_readonly

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
    church index whose name or canonical path is one of those libraries are
    both refused. Spurgeon and edwards go through ``libraries.PUBLIC_DOMAIN``
    and ``classic_index_problem``. The caller raises ``SystemExit`` for an
    explicit request and leaves the side empty when the path was only
    auto-detected.
    """
    if is_classic_slug(slug) or (path is not None and is_protected_classic(path)):
        name = slug or Path(path).name
        return _classic_church_error(name)
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
) -> None:
    """Mark ``path`` as the church and clear that mark on any sibling file.

    Classic libraries (wesley, spurgeon, edwards, and their canonical paths)
    are not opened. ``store.connect`` migrates the schema and sets
    ``journal_mode=WAL``; a mistaken mark on a copy of wesley.sqlite used to
    rewrite that file. Siblings that do get cleared are opened with a plain
    ``sqlite3`` connection, which does not migrate and does not change the
    journal mode. The target itself is the church file this import just
    wrote, so it still goes through ``store.connect``.
    """
    target = Path(path).resolve()
    if is_protected_classic(target):
        raise ValueError(_classic_church_error(target.name))
    for candidate in church_index_matches(index_dir, exclude=target):
        if is_protected_classic(candidate):
            continue
        _clear_church_mark(candidate)
    connection = connect(target)
    try:
        mark_your_church(connection, label=label, sample=sample)
        connection.commit()
    finally:
        connection.close()


def is_protected_classic(path: Path) -> bool:
    """True for a classic slug or a canonical classic index path.

    The stem check covers a copy (``/tmp/wesley.sqlite``). Spurgeon and
    edwards canonical paths go through ``libraries.classic_index_problem``
    and ``canonical_index``. Wesley's place is ``paths.INDEX_PATH``, read
    at call time. The file is not opened.
    """
    if is_classic_slug(Path(path).stem):
        return True
    resolved = _resolve(path)
    if resolved is None:
        return False
    from preached import paths

    for candidate in (paths.INDEX_PATH, paths.INDEX_DIR / "wesley.sqlite"):
        canonical = _resolve(candidate)
        if canonical is not None and resolved == canonical:
            return True
    for slug in PUBLIC_DOMAIN:
        # None means #14 would serve this path as that classic library.
        if classic_index_problem(slug, path) is None:
            return True
        canonical = _resolve(canonical_index(slug))
        if canonical is not None and resolved == canonical:
            return True
    return False


def _clear_church_mark(path: Path) -> None:
    """Drop ``role=church`` without migrating the file or enabling WAL.

    ``store.connect`` runs the schema script and ``PRAGMA journal_mode=WAL``.
    A plain connection does neither. The journal mode already on the file
    stays as it is.
    """
    connection = sqlite3.connect(path)
    try:
        clear_church_role(connection)
        connection.commit()
    finally:
        connection.close()


def _resolve(path: Path | None) -> Path | None:
    if path is None:
        return None
    try:
        return Path(path).resolve()
    except OSError:
        return None
