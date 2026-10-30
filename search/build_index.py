"""Load chunk JSONL into the SQLite index. Does not embed.

Embeddings are written by search/bench.py so each model is timed on the GPU.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from preached.corpus import read_jsonl  # noqa: E402
from preached.paths import CHUNKS_JSONL, INDEX_PATH  # noqa: E402
from preached.store import chunk_count, connect, replace_chunks  # noqa: E402


def main() -> None:
    if not CHUNKS_JSONL.exists():
        raise SystemExit(f"missing {CHUNKS_JSONL}")
    chunks = read_jsonl(CHUNKS_JSONL)
    connection = connect(INDEX_PATH)
    replace_chunks(connection, chunks)
    print(f"indexed {chunk_count(connection)} chunks at {INDEX_PATH}")


if __name__ == "__main__":
    main()
