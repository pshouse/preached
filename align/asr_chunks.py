"""Timed chunks straight from a Whisper transcript (``text_source: "asr"``).

For sermons with no published text (church recordings), the searchable
words are Whisper's. Same record and the same chunk params as the canonical
path (``corpus/chunk_config.json``, W1-B's ``chunk_text``), so the index
treats both alike and the page can say "Wording follows the recording."

Input is a W1-A-style transcript: ``segments[].words = [[start, end, word]]``,
optional ``searchable_start`` / ``searchable_end`` and ``meta``. A pause of
``--pause`` seconds starts a new paragraph, so unpunctuated stretches still
break near a natural boundary instead of only at ``max_words``.

    python3 align/asr_chunks.py /cache/transcripts/wesley/wesley-s1-01.json --out /tmp/asr.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from preached.corpus import chunk_text, load_chunk_config, word_tokens, write_jsonl  # noqa: E402

PAUSE_S = 1.5
# ASR chunk ids live in their own namespace. Canonical (CCEL) ids are
# "{sermon_id}-cNNNN" with no colon, so a church sermon whose id reuses a CCEL
# sermon id can never hit chunks.chunk_id UNIQUE and fail the rebuild.
ASR_ID_PREFIX = "asr:"


def asr_chunk_id(sermon_id: str, index: int) -> str:
    return f"{ASR_ID_PREFIX}{sermon_id}-c{index:04d}"


def transcript_words(transcript: dict) -> list[tuple[float, float, str]]:
    lo = transcript.get("searchable_start", float("-inf"))
    hi = transcript.get("searchable_end", float("inf"))
    words = [
        (start, end, word.strip())
        for segment in transcript["segments"]
        if not segment.get("boilerplate")
        for start, end, word in segment["words"]
        if lo <= start < hi and word.strip()
    ]
    words.sort(key=lambda item: item[0])
    return words


def asr_chunks(
    transcript: dict,
    config: dict,
    sermon_id: str | None = None,
    sermon_title: str | None = None,
    pause_s: float = PAUSE_S,
) -> list[dict]:
    meta = transcript.get("meta", {})
    sermon_id = sermon_id or meta["id"]
    words = transcript_words(transcript)
    # Token index -> Whisper word index. Tokens never cross a space, so the
    # tokens of the joined text are the tokens of each word in order.
    owner: list[int] = []
    pieces: list[str] = []
    for index, (start, _, word) in enumerate(words):
        if index and start - words[index - 1][1] >= pause_s:
            pieces.append("\n\n")
        elif index:
            pieces.append(" ")
        pieces.append(word)
        owner.extend([index] * len(word_tokens(word)))
    text = "".join(pieces)
    if len(owner) != len(word_tokens(text)):
        raise RuntimeError("token map does not match the transcript text")
    records = []
    for index, piece in enumerate(chunk_text(text, config)):
        first = words[owner[piece["word_start"]]]
        last = words[owner[piece["word_end"] - 1]]
        records.append({
            "chunk_id": asr_chunk_id(sermon_id, index),
            "sermon_id": sermon_id,
            "sermon_title": sermon_title or meta.get("title") or sermon_id,
            "text": piece["text"],
            "start_s": first[0],
            "end_s": last[1],
            "audio_url": meta.get("audio_url"),
            "reader": meta.get("reader") or meta.get("preacher"),
            "text_source": "asr",
            "sermon_number": meta.get("sermon_number"),
            "scripture": meta.get("scripture"),
            "source_url": meta.get("source_url") or meta.get("ia_url"),
            "word_count": piece["word_count"],
            "word_start": piece["word_start"],
            "word_end": piece["word_end"],
            "librivox_id": None,
        })
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("transcripts", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pause", type=float, default=PAUSE_S, help="seconds of silence that start a paragraph")
    args = parser.parse_args()
    config = load_chunk_config(ROOT / "corpus" / "chunk_config.json")
    rows = []
    for path in args.transcripts:
        rows.extend(asr_chunks(json.loads(path.read_text()), config, pause_s=args.pause))
    write_jsonl(args.out, rows)
    print(f"wrote {len(rows)} asr chunks from {len(args.transcripts)} transcripts to {args.out}")


if __name__ == "__main__":
    main()
