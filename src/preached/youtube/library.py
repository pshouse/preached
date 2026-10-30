"""Write one church library SQLite file the search server can open.

The chunks table is the W1 schema from ``preached.store``, plus the audio
columns the server already reads when they exist: ``audio_url``, ``reader``,
``text_source``. YouTube rows also store ``video_id``, ``title``, and
``published``. Embeddings are Granite English R2 float32 BLOBs. FTS5 is the
same trigger-maintained ``chunks_fts`` table. There is no vector database.

``reader`` is NULL. The voice is the recording, and ``text_source`` is ``asr``.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone

import numpy as np

from preached.models import DEFAULT_MODEL
from preached.store import connect

# Columns the Wesley index does not have. Added on the library file only.
EXTRA_COLUMNS = (
    ("audio_url", "TEXT"),
    ("reader", "TEXT"),
    ("text_source", "TEXT"),
    ("video_id", "TEXT"),
    ("title", "TEXT"),
    ("published", "TEXT"),
)

MODEL_KEY = DEFAULT_MODEL


def ensure_library(connection: sqlite3.Connection) -> None:
    have = {row[1] for row in connection.execute("PRAGMA table_info(chunks)")}
    for name, kind in EXTRA_COLUMNS:
        if name not in have:
            connection.execute(f"ALTER TABLE chunks ADD COLUMN {name} {kind}")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS videos (
            video_id TEXT PRIMARY KEY,
            title TEXT,
            published TEXT,
            duration_s REAL,
            license TEXT,
            uploader TEXT,
            status TEXT NOT NULL,
            error TEXT,
            imported_at TEXT
        )
        """
    )
    connection.commit()


def open_library(path) -> sqlite3.Connection:
    connection = connect(path)
    ensure_library(connection)
    return connection


def imported_ok(connection: sqlite3.Connection) -> set[str]:
    """Video ids that should not be fetched again.

    ``ok`` is imported. ``skipped`` is a recorded decision (for example the
    license was not Creative Commons) and is not retried unless ``--redo``.
    ``error`` is absent here so the next run tries that video again.
    """
    rows = connection.execute(
        "SELECT video_id FROM videos WHERE status IN ('ok', 'skipped')"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day else None


def mark_video(
    connection: sqlite3.Connection,
    *,
    video_id: str,
    title: str,
    published: date | None,
    duration_s: float | None,
    license_text: str | None,
    uploader: str | None,
    status: str,
    error: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO videos (
            video_id, title, published, duration_s, license, uploader,
            status, error, imported_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(video_id) DO UPDATE SET
            title = excluded.title,
            published = excluded.published,
            duration_s = excluded.duration_s,
            license = excluded.license,
            uploader = excluded.uploader,
            status = excluded.status,
            error = excluded.error,
            imported_at = excluded.imported_at
        """,
        (
            video_id,
            title,
            _iso(published),
            duration_s,
            license_text,
            uploader,
            status,
            error,
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ),
    )


def index_video(
    connection: sqlite3.Connection,
    *,
    video_id: str,
    title: str,
    published: date | None,
    duration_s: float | None,
    license_text: str | None,
    uploader: str | None,
    chunks: list[dict],
    matrix: np.ndarray,
) -> list[int]:
    """Replace any earlier attempt at this video and commit chunks plus vectors.

    One transaction so a crash does not leave chunks without embeddings.
    The next run then sees the video is not ``ok`` and tries again.
    """
    if len(chunks) != len(matrix):
        raise RuntimeError("embedding rows do not match chunks")
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.ndim != 2:
        raise RuntimeError("embedding matrix must be two-dimensional")
    if not np.isfinite(matrix).all():
        raise RuntimeError("embeddings contain NaN or inf")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = (matrix / np.maximum(norms, 1e-12)).astype(np.float32)
    published_text = _iso(published)
    try:
        connection.execute(
            "DELETE FROM embeddings WHERE rowid IN (SELECT rowid FROM chunks WHERE video_id = ?)",
            (video_id,),
        )
        connection.execute("DELETE FROM chunks WHERE video_id = ?", (video_id,))
        rowids: list[int] = []
        for chunk in chunks:
            cursor = connection.execute(
                """
                INSERT INTO chunks (
                    chunk_id, sermon_id, sermon_title, text, start_s, end_s,
                    sermon_number, scripture, source_url, word_count, word_start,
                    word_end, librivox_id, audio_url, reader, text_source,
                    video_id, title, published
                ) VALUES (
                    :chunk_id, :sermon_id, :sermon_title, :text, :start_s, :end_s,
                    :sermon_number, :scripture, :source_url, :word_count, :word_start,
                    :word_end, :librivox_id, :audio_url, :reader, :text_source,
                    :video_id, :title, :published
                )
                """,
                {
                    "chunk_id": chunk["chunk_id"],
                    "sermon_id": video_id,
                    "sermon_title": title,
                    "text": chunk["text"],
                    "start_s": chunk["start_s"],
                    "end_s": chunk["end_s"],
                    "sermon_number": None,
                    "scripture": None,
                    "source_url": chunk["source_url"],
                    "word_count": chunk["word_count"],
                    "word_start": chunk["word_start"],
                    "word_end": chunk["word_end"],
                    "librivox_id": None,
                    "audio_url": chunk["audio_url"],
                    "reader": None,
                    "text_source": "asr",
                    "video_id": video_id,
                    "title": title,
                    "published": published_text,
                },
            )
            rowids.append(int(cursor.lastrowid))
        connection.executemany(
            "INSERT INTO embeddings (rowid, model, dim, vector) VALUES (?, ?, ?, ?)",
            (
                (rowid, MODEL_KEY, int(matrix.shape[1]), matrix[index].tobytes())
                for index, rowid in enumerate(rowids)
            ),
        )
        mark_video(
            connection,
            video_id=video_id,
            title=title,
            published=published,
            duration_s=duration_s,
            license_text=license_text,
            uploader=uploader,
            status="ok",
            error=None,
        )
        connection.execute(
            "INSERT INTO meta (key, value) VALUES ('embed_model', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (MODEL_KEY,),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return rowids
