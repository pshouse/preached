"""Write one church library SQLite file the search server can open.

The chunks table is the W1 schema from ``preached.store``, plus the audio
columns the server already reads when they exist: ``audio_url``, ``reader``,
``text_source``. YouTube rows also store ``video_id``, ``title``, and
``published``. Embeddings are Granite English R2 float32 BLOBs. FTS5 is the
same trigger-maintained ``chunks_fts`` table. There is no vector database.

``reader`` is NULL. The voice is the recording, and ``text_source`` is ``asr``.
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import date, datetime, timezone

import numpy as np

from preached.models import DEFAULT_MODEL, MODELS
from preached.store import connect, save_embedding_info

# Columns the Wesley index does not have. Added on the library file only.
EXTRA_COLUMNS = (
    ("audio_url", "TEXT"),
    ("reader", "TEXT"),
    ("text_source", "TEXT"),
    ("video_id", "TEXT"),
    ("title", "TEXT"),
    ("published", "TEXT"),
    ("flag_end_s", "REAL"),
)

# Publish gate, on the videos table. A sermon is served only when
# approved_sha256 equals review_sha256 (see preached.store.hidden_rowids).
VIDEO_EXTRA_COLUMNS = (
    ("review_sha256", "TEXT"),
    ("approved_sha256", "TEXT"),
    ("approved_at", "TEXT"),
    # preached.privacy.config_sha256 of the config the import ran under.
    ("privacy_sha256", "TEXT"),
    # JSON list of [start_s, end_s] uncovered non-silent spans (preached.youtube.coverage).
    # NULL means the check never ran; approval refuses both NULL and a non-empty list.
    ("coverage_gaps", "TEXT"),
    # sha256 of the review file without its "exclude" lines (preached.exclusions):
    # the reviewer may widen or add exclusions, and nothing else.
    ("review_base_sha256", "TEXT"),
)

MODEL_KEY = DEFAULT_MODEL

# Seconds to wait between WAL checkpoint attempts. A reader (the server in the
# middle of a query) keeps a TRUNCATE checkpoint from finishing; each attempt
# also waits CHECKPOINT_BUSY_MS for it. About 8 s in all, then refused.
CHECKPOINT_WAITS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0)
CHECKPOINT_BUSY_MS = 200


class CheckpointBusy(RuntimeError):
    """The WAL could not be checkpointed: deleted words may still be in ``-wal``."""


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
    have_videos = {row[1] for row in connection.execute("PRAGMA table_info(videos)")}
    for name, kind in VIDEO_EXTRA_COLUMNS:
        if name not in have_videos:
            connection.execute(f"ALTER TABLE videos ADD COLUMN {name} {kind}")
    connection.commit()


def open_library(path) -> sqlite3.Connection:
    """Open a church library file for writing, with SQLite ``secure_delete`` on.

    Every delete (``--redo``, a rebuild at approval) then zeroes the freed
    content, so removed words do not survive in free pages. Raises when this
    SQLite cannot turn it on.
    """
    connection = connect(path)
    if connection.execute("PRAGMA secure_delete = ON").fetchone()[0] != 1:
        connection.close()
        raise RuntimeError("SQLite secure_delete could not be enabled; refusing to write a church library")
    ensure_library(connection)
    return connection


def checkpoint(connection: sqlite3.Connection) -> None:
    """``wal_checkpoint(TRUNCATE)``, checked: retried with backoff, else ``CheckpointBusy``.

    The pragma reports ``(busy, wal frames, frames checkpointed)``; it only
    finished when busy is 0 and every frame was copied back. Until then the
    old pages (and any words a delete removed) are still in ``-wal``.
    """
    previous = connection.execute("PRAGMA busy_timeout").fetchone()[0]
    db_path = next((row[2] for row in connection.execute("PRAGMA database_list") if row[1] == "main"), "") or "(in memory)"
    connection.execute(f"PRAGMA busy_timeout = {int(CHECKPOINT_BUSY_MS)}")
    try:
        for wait in (*CHECKPOINT_WAITS, None):
            busy, frames, done = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if busy == 0 and frames == done:
                return
            if wait is None:
                break
            time.sleep(wait)
    finally:
        connection.execute(f"PRAGMA busy_timeout = {int(previous)}")
    raise CheckpointBusy(
        f"the WAL checkpoint did not finish after {len(CHECKPOINT_WAITS) + 1} tries (a reader such as the "
        f"server held it); removed words may still be in {db_path} or {db_path}-wal. Stop the reader and run it again"
    )


def scrub(connection: sqlite3.Connection) -> None:
    """After a delete: merge the FTS index, commit, then a checked checkpoint.

    Old FTS segments keep removed words until they are merged; with
    ``secure_delete`` the freed pages are zeroed, and the checkpoint moves
    the zeroed pages into the main file and empties ``-wal``.
    """
    connection.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('optimize')")
    connection.commit()
    checkpoint(connection)


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
    review_sha256: str | None = None,
    privacy_sha256: str | None = None,
    coverage_gaps: list | None = None,
    review_base_sha256: str | None = None,
    reader: str | None = None,
    sermon_number: int | None = None,
    librivox_id: str | None = None,
) -> list[int]:
    """Replace any earlier attempt at this video and commit chunks plus vectors.

    The video lands unpublished: ``review_sha256`` is stored and any earlier
    approval is cleared, so a re-import needs a new approval
    (``preached.exclusions.approve``).

    One transaction so a crash does not leave chunks without embeddings.
    The next run then sees the video is not ``ok`` and tries again. When
    earlier rows were replaced (``--redo``, a rebuild), ``scrub`` runs after
    the commit, so the old words leave the file and ``-wal``
    (``CheckpointBusy`` if the checkpoint cannot finish).
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
        replaced = connection.execute("DELETE FROM chunks WHERE video_id = ?", (video_id,)).rowcount
        rowids: list[int] = []
        for chunk in chunks:
            cursor = connection.execute(
                """
                INSERT INTO chunks (
                    chunk_id, sermon_id, sermon_title, text, start_s, end_s,
                    sermon_number, scripture, source_url, word_count, word_start,
                    word_end, librivox_id, audio_url, reader, text_source,
                    video_id, title, published, flag_end_s
                ) VALUES (
                    :chunk_id, :sermon_id, :sermon_title, :text, :start_s, :end_s,
                    :sermon_number, :scripture, :source_url, :word_count, :word_start,
                    :word_end, :librivox_id, :audio_url, :reader, :text_source,
                    :video_id, :title, :published, :flag_end_s
                )
                """,
                {
                    "chunk_id": chunk["chunk_id"],
                    "sermon_id": video_id,
                    "sermon_title": title,
                    "text": chunk["text"],
                    "start_s": chunk["start_s"],
                    "end_s": chunk["end_s"],
                    "sermon_number": sermon_number,
                    "scripture": None,
                    "source_url": chunk["source_url"],
                    "word_count": chunk["word_count"],
                    "word_start": chunk["word_start"],
                    "word_end": chunk["word_end"],
                    "librivox_id": librivox_id,
                    "audio_url": chunk["audio_url"],
                    "reader": reader,
                    "text_source": "asr",
                    "video_id": video_id,
                    "title": title,
                    "published": published_text,
                    "flag_end_s": chunk.get("flag_end_s"),
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
            "UPDATE videos SET review_sha256 = ?, privacy_sha256 = ?, review_base_sha256 = ?, coverage_gaps = ?, "
            "approved_sha256 = NULL, approved_at = NULL WHERE video_id = ?",
            (
                review_sha256,
                privacy_sha256,
                review_base_sha256,
                None if coverage_gaps is None else json.dumps([[float(a), float(b)] for a, b in coverage_gaps]),
                video_id,
            ),
        )
        connection.execute(
            "INSERT INTO meta (key, value) VALUES ('embed_model', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (MODEL_KEY,),
        )
        _stamp_fingerprint(connection)
    except Exception:
        connection.rollback()
        raise
    if replaced:
        scrub(connection)
    return rowids


def _stamp_fingerprint(connection: sqlite3.Connection) -> None:
    """Record the models.toml fingerprint for the vectors just written.

    Searcher refuses a model key whose stored fingerprint does not match.
    ``save_embedding_info`` commits this transaction with the chunks.
    """
    expected = MODELS[MODEL_KEY].fingerprint()
    key = f"embeddings:{MODEL_KEY}"
    row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row is not None:
        stored = json.loads(row[0]).get("fingerprint")
        if stored != expected:
            raise RuntimeError(
                f"stored vectors for {MODEL_KEY} have fingerprint {stored}, "
                f"but search/models.toml gives {expected}"
            )
    save_embedding_info(connection, MODEL_KEY, {"fingerprint": expected})
