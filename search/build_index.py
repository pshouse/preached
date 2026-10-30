"""Load chunk JSONL into the SQLite index (only if its content changed). Does not embed.

Embeddings are written by search/bench.py so each model is timed on the GPU.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from preached.paths import INDEX_PATH, StaleChunks, index_chunks_jsonl  # noqa: E402
from preached.store import chunk_count, connect, sync_chunks  # noqa: E402


def main() -> None:
    try:
        chunks_path = index_chunks_jsonl()
    except StaleChunks as exc:
        raise SystemExit(f"error: {exc}") from exc
    if not chunks_path.exists():
        raise SystemExit(f"missing {chunks_path}")
    connection = connect(INDEX_PATH)
    sync_chunks(connection, chunks_path)
    print(f"indexed {chunk_count(connection)} chunks at {INDEX_PATH}")


if __name__ == "__main__":
    main()
