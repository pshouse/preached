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
    librivox_id TEXT
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
    connection.executescript(TRIGGERS)
    return connection


# Every column replace_chunks writes. The legacy-index check below compares
# all of them, so a timing-only change (W1-C alignment) is never dropped.
CHUNK_COLUMNS = (
    "chunk_id", "sermon_id", "sermon_title", "text", "start_s", "end_s",
    "sermon_number", "scripture", "source_url", "word_count", "word_start",
    "word_end", "librivox_id",
)


def replace_chunks(connection: sqlite3.Connection, chunks: list[dict]) -> None:
    connection.execute("DELETE FROM embeddings")
    connection.execute("DELETE FROM chunks")
    connection.executemany(
        f"INSERT INTO chunks ({', '.join(CHUNK_COLUMNS)}) "
        f"VALUES ({', '.join(':' + c for c in CHUNK_COLUMNS)})",
        chunks,
    )
    connection.commit()


def sync_chunks(connection: sqlite3.Connection, chunks_path: Path) -> int:
    """Load chunks only when the chunk file's content changed.

    Compares the file's sha256 with the one recorded in meta. The hash is of
    the whole file, so it covers every field, timing included. Same content:
    nothing is touched, so cached embeddings survive. New content: chunks are
    replaced and embeddings are dropped, because their rowids no longer match.

    An index built before the hash was recorded is adopted only when every
    stored row equals the file's row in every column (not just the text).
    Otherwise it is rebuilt.
    """
    import hashlib

    digest = hashlib.sha256(chunks_path.read_bytes()).hexdigest()
    row = connection.execute("SELECT value FROM meta WHERE key = 'chunks_sha256'").fetchone()
    if row is not None and row[0] == digest:
        return chunk_count(connection)
    if row is None and chunk_count(connection) > 0:
        # Index built before the hash was recorded. Adopt it only if every
        # column of every row matches; a text-only check would keep stale
        # start_s/end_s forever once the hash is recorded.
        wanted = [
            tuple(chunk.get(c) for c in CHUNK_COLUMNS)
            for chunk in (json.loads(line) for line in chunks_path.read_text().splitlines() if line.strip())
        ]
        stored = [
            tuple(r)
            for r in connection.execute(f"SELECT {', '.join(CHUNK_COLUMNS)} FROM chunks ORDER BY rowid")
        ]
        if stored == wanted:
            connection.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('chunks_sha256', ?)", (digest,))
            connection.commit()
            return len(stored)
    chunks = [json.loads(line) for line in chunks_path.read_text().splitlines() if line.strip()]
    replace_chunks(connection, chunks)
    connection.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('chunks_sha256', ?)", (digest,))
    connection.execute("DELETE FROM meta WHERE key LIKE 'embeddings:%'")
    connection.commit()
    return len(chunks)


def chunk_count(connection: sqlite3.Connection) -> int:
    return int(connection.execute("SELECT count(*) FROM chunks").fetchone()[0])


def load_chunk_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(connection.execute("SELECT * FROM chunks ORDER BY rowid"))


def bm25_search(connection: sqlite3.Connection, query: str, limit: int) -> list[tuple[int, float]]:
    """Return (rowid, higher-is-better score). SQLite bm25() is lower-is-better."""
    match = to_fts_query(query)
    try:
        rows = connection.execute(
            """
            SELECT rowid, bm25(chunks_fts) AS score
            FROM chunks_fts
            WHERE chunks_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (match, limit),
        ).fetchall()
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
