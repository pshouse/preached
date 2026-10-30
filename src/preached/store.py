"""One SQLite file: chunks, FTS5, and embedding BLOBs.

Vectors are float32, L2-normalized, so cosine similarity is a dot product.
Search is brute force in numpy. There is no vector database.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np

from preached.fts import to_fts_query
from preached.paths import INDEX_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    rowid INTEGER PRIMARY KEY,
    chunk_id TEXT UNIQUE NOT NULL,
    sermon_id TEXT NOT NULL,
    sermon_title TEXT NOT NULL,
    text TEXT NOT NULL,
    start_s REAL,
    end_s REAL,
    sermon_number INTEGER,
    scripture TEXT,
    source_url TEXT,
    word_count INTEGER,
    word_start INTEGER,
    word_end INTEGER,
    librivox_id TEXT,
    audio_url TEXT,
    reader TEXT,
    text_source TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    sermon_title,
    scripture,
    content='chunks',
    content_rowid='rowid',
    tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS embeddings (
    rowid INTEGER NOT NULL,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY (rowid, model)
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text, sermon_title, scripture)
    VALUES (new.rowid, new.text, new.sermon_title, coalesce(new.scripture, ''));
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, sermon_title, scripture)
    VALUES ('delete', old.rowid, old.text, old.sermon_title, coalesce(old.scripture, ''));
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, sermon_title, scripture)
    VALUES ('delete', old.rowid, old.text, old.sermon_title, coalesce(old.scripture, ''));
    INSERT INTO chunks_fts(rowid, text, sermon_title, scripture)
    VALUES (new.rowid, new.text, new.sermon_title, coalesce(new.scripture, ''));
END;
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    index_path = path or INDEX_PATH
    index_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(index_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(SCHEMA)
    have = {row[1] for row in connection.execute("PRAGMA table_info(chunks)")}
    for column in LATE_COLUMNS:
        if column not in have:
            connection.execute(f"ALTER TABLE chunks ADD COLUMN {column} TEXT")
    connection.executescript(TRIGGERS)
    return connection


def open_readonly(path: Path | None = None, *, check_same_thread: bool = True) -> sqlite3.Connection:
    """Open an existing index without creating or writing it.

    ``mode=ro`` plus ``query_only`` so the web server cannot migrate the
    file out from under the ingest job. Missing audio columns stay missing;
    callers read them with ``row_value``.
    """
    index_path = path or INDEX_PATH
    if not index_path.is_file():
        raise FileNotFoundError(f"missing index {index_path}")
    uri = index_path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, check_same_thread=check_same_thread)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


# Every column replace_chunks writes. The legacy-index check below compares
# all of them, so a timing-only change (W1-C alignment) is never dropped.
CHUNK_COLUMNS = (
    "chunk_id", "sermon_id", "sermon_title", "text", "start_s", "end_s",
    "sermon_number", "scripture", "source_url", "word_count", "word_start",
    "word_end", "librivox_id", "audio_url", "reader", "text_source",
)
# Added by W1-C; an index created before them gets them by ALTER TABLE.
LATE_COLUMNS = ("audio_url", "reader", "text_source")
# Everything a stored document vector depends on (embed.document_title uses
# sermon_title and scripture; the chunk text is the body), plus the id. When
# these match row for row, in order, the vectors still describe the same rows.
EMBED_KEY_COLUMNS = ("chunk_id", "sermon_title", "scripture", "text")
# The rest (timing, audio, reader, spans, ...) can change without re-embedding.
METADATA_COLUMNS = tuple(c for c in CHUNK_COLUMNS if c not in EMBED_KEY_COLUMNS)


class DuplicateChunkId(ValueError):
    """Two chunks in one file share a chunk_id (chunks.chunk_id is UNIQUE)."""


def check_unique_ids(chunks: list[dict], source: object = "chunk file") -> None:
    seen: set = set()
    for chunk in chunks:
        chunk_id = chunk.get("chunk_id")
        if chunk_id in seen:
            raise DuplicateChunkId(
                f"duplicate chunk_id {chunk_id!r} in {source}; ASR chunk ids must keep their 'asr:' prefix"
            )
        seen.add(chunk_id)


def _refuse_review_items(chunks: list[dict]) -> None:
    from preached.privacy import ReviewItem, ReviewList

    if isinstance(chunks, ReviewList) or any(isinstance(c, ReviewItem) for c in chunks):
        raise ValueError("privacy review items hold real names and must never be indexed")
    # Church chunks carry the publish-gate key. This table has no gate, so
    # loading them here would serve unapproved sermons.
    if any(isinstance(c, dict) and c.get("video_id") is not None for c in chunks):
        raise ValueError("church chunks (with video_id) go into a gated library file, never this index")


def update_chunk_metadata(connection: sqlite3.Connection, chunks: list[dict]) -> None:
    """Rewrite only METADATA_COLUMNS, row for row, keeping rowids and vectors.

    The caller has checked that EMBED_KEY_COLUMNS match in the same order.
    """
    _refuse_review_items(chunks)
    rowids = [int(r[0]) for r in connection.execute("SELECT rowid FROM chunks ORDER BY rowid")]
    if len(rowids) != len(chunks):
        raise RuntimeError("update_chunk_metadata: row count changed")
    assignments = ", ".join(f"{c} = :{c}" for c in METADATA_COLUMNS)
    connection.executemany(
        f"UPDATE chunks SET {assignments} WHERE rowid = :rowid",
        [{**{c: chunk.get(c) for c in METADATA_COLUMNS}, "rowid": rowid} for rowid, chunk in zip(rowids, chunks)],
    )


def replace_chunks(connection: sqlite3.Connection, chunks: list[dict]) -> None:
    """Replace every chunk and drop all embeddings and their fingerprints.

    Does not commit: the caller commits, so a rebuild (this, the hash write)
    is one transaction and a crash leaves the index fully old or fully new.
    Privacy review items are refused before anything is written.
    """
    _refuse_review_items(chunks)
    connection.execute("DELETE FROM embeddings")
    connection.execute("DELETE FROM meta WHERE key LIKE 'embeddings:%'")
    connection.execute("DELETE FROM chunks")
    connection.executemany(
        f"INSERT INTO chunks ({', '.join(CHUNK_COLUMNS)}) "
        f"VALUES ({', '.join(':' + c for c in CHUNK_COLUMNS)})",
        # Text-only chunk files have no audio fields; missing keys are NULL.
        [{column: chunk.get(column) for column in CHUNK_COLUMNS} for chunk in chunks],
    )


def _after_replace() -> None:
    """No-op seam between the chunk replace and the hash write (tests patch it)."""


def sync_chunks(connection: sqlite3.Connection, chunks_path: Path) -> int:
    """Load chunks only when the chunk file's content changed.

    Compares the file's sha256 with the one recorded in meta. The hash is of
    the whole file, so it covers every field, timing included.

    - Same hash: nothing is touched, so cached embeddings survive.
    - New hash, but the same chunk ids with the same embedding inputs
      (EMBED_KEY_COLUMNS) in the same order: only the other columns (start_s,
      end_s, audio, reader, ...) are updated in place. Rowids, vectors and
      their fingerprints are kept, so an alignment re-run never re-embeds.
    - Anything else: chunks are replaced and embeddings are dropped, because
      their rowids or inputs no longer match.

    An index built before the hash was recorded follows the same rule, so a
    legacy index picks up new timing too (it is never adopted on text alone).
    Duplicate chunk ids are refused before anything is written.
    """
    import hashlib

    digest = hashlib.sha256(chunks_path.read_bytes()).hexdigest()
    row = connection.execute("SELECT value FROM meta WHERE key = 'chunks_sha256'").fetchone()
    if row is not None and row[0] == digest:
        return chunk_count(connection)
    chunks = [json.loads(line) for line in chunks_path.read_text().splitlines() if line.strip()]
    check_unique_ids(chunks, chunks_path)
    if chunk_count(connection) > 0:
        stored = [
            tuple(r)
            for r in connection.execute(f"SELECT {', '.join(EMBED_KEY_COLUMNS)} FROM chunks ORDER BY rowid")
        ]
        wanted = [tuple(chunk.get(c) for c in EMBED_KEY_COLUMNS) for chunk in chunks]
        if stored == wanted:
            update_chunk_metadata(connection, chunks)
            connection.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('chunks_sha256', ?)", (digest,))
            connection.commit()
            return len(chunks)
    replace_chunks(connection, chunks)
    # Test hook point: a crash here must roll back the replace (see test_store).
    _after_replace()
    connection.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('chunks_sha256', ?)", (digest,))
    connection.commit()
    return len(chunks)


def chunk_count(connection: sqlite3.Connection) -> int:
    return int(connection.execute("SELECT count(*) FROM chunks").fetchone()[0])


def load_chunk_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(connection.execute("SELECT * FROM chunks ORDER BY rowid"))


def bm25_search(connection: sqlite3.Connection, query: str, limit: int, where: str | None = None) -> list[tuple[int, float]]:
    """Return (rowid, higher-is-better score). SQLite bm25() is lower-is-better.

    ``where`` is a ``visible_sql(connection, "chunks")`` condition; it filters
    in the same query, so hidden rows never take a slot.
    """
    match = to_fts_query(query)
    if where is None:
        sql = """
            SELECT rowid, bm25(chunks_fts) AS score
            FROM chunks_fts
            WHERE chunks_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """
    else:
        sql = f"""
            SELECT chunks_fts.rowid AS rowid, bm25(chunks_fts) AS score
            FROM chunks_fts JOIN chunks ON chunks.rowid = chunks_fts.rowid
            WHERE chunks_fts MATCH ? AND {where}
            ORDER BY score
            LIMIT ?
            """
    try:
        rows = connection.execute(sql, (match, limit)).fetchall()
    except sqlite3.OperationalError as exc:
        # Do not turn a broken query into "nothing found".
        raise RuntimeError(f"FTS5 query failed for MATCH {match!r}: {exc}") from exc
    return [(int(row["rowid"]), -float(row["score"])) for row in rows]


def write_embeddings(
    connection: sqlite3.Connection,
    model: str,
    rowids: list[int],
    matrix: np.ndarray,
) -> None:
    if matrix.dtype != np.float32:
        matrix = matrix.astype(np.float32)
    if matrix.ndim != 2 or len(rowids) != matrix.shape[0]:
        raise RuntimeError("embedding matrix does not match rowids")
    connection.execute("DELETE FROM embeddings WHERE model = ?", (model,))
    connection.executemany(
        "INSERT INTO embeddings (rowid, model, dim, vector) VALUES (?, ?, ?, ?)",
        (
            (rowid, model, int(matrix.shape[1]), matrix[index].tobytes())
            for index, rowid in enumerate(rowids)
        ),
    )
    connection.commit()


class EmbeddingMismatch(RuntimeError):
    """Stored document vectors were not built with the configured model."""


def embedding_info(connection: sqlite3.Connection, model: str) -> dict | None:
    row = connection.execute("SELECT value FROM meta WHERE key = ?", (f"embeddings:{model}",)).fetchone()
    return json.loads(row[0]) if row else None


def stored_fingerprint(connection: sqlite3.Connection, model: str) -> str | None:
    info = embedding_info(connection, model)
    return info.get("fingerprint") if info else None


def save_embedding_info(connection: sqlite3.Connection, model: str, info: dict) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (f"embeddings:{model}", json.dumps(info))
    )
    connection.commit()


def check_fingerprint(connection: sqlite3.Connection, model: str, expected: str) -> None:
    """Refuse to pair new query vectors with document vectors from another
    model revision or document setting (see ModelSpec.fingerprint)."""
    stored = stored_fingerprint(connection, model)
    if stored != expected:
        raise EmbeddingMismatch(
            f"stored vectors for {model} have fingerprint {stored or 'none recorded'}, but "
            f"search/models.toml gives {expected} (model id, pinned revision or document "
            f"settings changed). Re-embed: uv run --group bench search/bench.py --models {model}"
        )


def load_embeddings(connection: sqlite3.Connection, model: str) -> tuple[list[int], np.ndarray]:
    rows = connection.execute(
        "SELECT rowid, dim, vector FROM embeddings WHERE model = ? ORDER BY rowid",
        (model,),
    ).fetchall()
    if not rows:
        raise RuntimeError(
            f"no embeddings for {model} in the index. Run: uv run search/bench.py --models {model}"
        )
    dim = int(rows[0]["dim"])
    matrix = np.zeros((len(rows), dim), dtype=np.float32)
    rowids = []
    for index, row in enumerate(rows):
        vector = np.frombuffer(row["vector"], dtype=np.float32)
        if vector.shape != (dim,):
            raise RuntimeError(f"bad embedding blob for rowid {row['rowid']}")
        matrix[index] = vector
        rowids.append(int(row["rowid"]))
    return rowids, matrix


def embedding_bytes(connection: sqlite3.Connection, model: str) -> int:
    row = connection.execute(
        "SELECT coalesce(sum(length(vector)), 0) FROM embeddings WHERE model = ?",
        (model,),
    ).fetchone()
    return int(row[0])


def file_bytes(path: Path | None = None) -> int:
    index_path = path or INDEX_PATH
    return index_path.stat().st_size if index_path.exists() else 0


def visible_sql(connection: sqlite3.Connection, alias: str = "chunks", *, gated: bool = False) -> str | None:
    """SQL condition for the chunks a reader may see, or None when nothing is gated.

    Evaluated against the file as it is now, so callers run it per request:
    an import, ``--redo`` or approval made while the server runs takes effect
    on the next request. A church library's chunks carry a ``video_id``; they
    are served only when that sermon's ``videos`` row is ``ok`` and a human
    approved the review file whose sha256 is stored (``approved_sha256 ==
    review_sha256``). A row with a NULL ``video_id`` is never served. A
    library file without the gate columns fails closed (``"0"``). Wesley's
    index has no ``video_id`` column and no ``videos`` table and is not gated,
    unless ``gated`` says this file must be (any library but wesley).
    """
    chunk_cols = {row[1] for row in connection.execute("PRAGMA table_info(chunks)")}
    video_cols = {row[1] for row in connection.execute("PRAGMA table_info(videos)")}
    if "video_id" not in chunk_cols and not video_cols and not gated:
        return None
    if "video_id" not in chunk_cols or not {"review_sha256", "approved_sha256", "status"} <= video_cols:
        return "0"
    return (
        f"{alias}.video_id IS NOT NULL AND EXISTS ("
        f"SELECT 1 FROM videos v WHERE v.video_id = {alias}.video_id AND v.status = 'ok' "
        "AND v.approved_sha256 IS NOT NULL AND v.review_sha256 IS NOT NULL "
        "AND v.approved_sha256 = v.review_sha256)"
    )


def visible_count(connection: sqlite3.Connection, *, gated: bool = False) -> int:
    where = visible_sql(connection, "chunks", gated=gated)
    sql = "SELECT count(*) FROM chunks" + (f" WHERE {where}" if where else "")
    return int(connection.execute(sql).fetchone()[0])


def visible_rowids(connection: sqlite3.Connection, rowids, *, gated: bool = False) -> set[int]:
    """The subset of ``rowids`` that may be served right now."""
    wanted = [int(r) for r in rowids]
    if not wanted:
        return set()
    where = visible_sql(connection, "chunks", gated=gated)
    found: set[int] = set()
    for start in range(0, len(wanted), 500):
        part = wanted[start : start + 500]
        sql = f"SELECT rowid FROM chunks WHERE rowid IN ({', '.join('?' * len(part))})"
        if where:
            sql += f" AND {where}"
        found.update(int(r[0]) for r in connection.execute(sql, part))
    return found


def pending_review_count(connection: sqlite3.Connection) -> int:
    """Imported sermons waiting for approval (a count; never ids or titles)."""
    video_cols = {row[1] for row in connection.execute("PRAGMA table_info(videos)")}
    if not {"review_sha256", "approved_sha256", "status"} <= video_cols:
        return 0
    row = connection.execute(
        "SELECT count(*) FROM videos WHERE status = 'ok' "
        "AND (approved_sha256 IS NULL OR review_sha256 IS NULL OR approved_sha256 != review_sha256)"
    ).fetchone()
    return int(row[0])


def hidden_rowids(connection: sqlite3.Connection, *, gated: bool = False) -> set[int]:
    """Rowids that search, the API and the page must not serve right now (see ``visible_sql``)."""
    where = visible_sql(connection, "chunks", gated=gated)
    if where is None:
        return set()
    return {int(r[0]) for r in connection.execute(f"SELECT rowid FROM chunks WHERE NOT ({where})")}
