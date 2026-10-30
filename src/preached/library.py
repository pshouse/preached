"""Which SQLite file is a library, and which one is the user's church.

Each library is still its own file (``/cache/index/<slug>.sqlite``). A search
reads one connection, so rows from another file cannot appear in its hits.
The church mark is a row in the ``meta`` table that file already has. There
is no combined index and no new database.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

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

    Siblings are opened for writing only when they are already marked, so a
    Wesley index sitting in the same directory is not migrated just to be
    inspected.
    """
    target = Path(path).resolve()
    for candidate in church_index_matches(index_dir, exclude=target):
        connection = connect(candidate)
        try:
            clear_church_role(connection)
            connection.commit()
        finally:
            connection.close()
    connection = connect(target)
    try:
        mark_your_church(connection, label=label, sample=sample)
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
