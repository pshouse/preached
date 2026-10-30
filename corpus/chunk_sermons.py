"""Chunk /cache/corpus/wesley/sermons.jsonl into passage records.

Each record is {chunk_id, sermon_id, sermon_title, text, start_s, end_s}
plus optional metadata (scripture, source_url, word spans). Timestamps are
null until a transcript chunk supplies them.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from preached.corpus import build_chunks, load_chunk_config  # noqa: E402
from preached.paths import CHUNKS_JSONL  # noqa: E402


def main() -> None:
    config = load_chunk_config()
    chunks = build_chunks(config)
    words = [item["word_count"] for item in chunks]
    words.sort()
    median = words[len(words) // 2]
    print(
        f"wrote {len(chunks)} chunks to {CHUNKS_JSONL}\n"
        f"  words min/median/max: {words[0]}/{median}/{words[-1]}\n"
        f"  params: target={config['target_words']} min={config['min_words']} "
        f"max={config['max_words']} overlap={config['overlap']}"
    )


if __name__ == "__main__":
    main()
