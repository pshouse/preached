"""Church ASR chunks built from the words left after exclusions.

``align/asr_chunks.py`` keeps its own Wesley path unchanged. A church
sermon's words are split into kept runs at every excluded stretch
(``preached.exclusions``) and each run is chunked on its own, so no chunk
holds words from both sides of an excluded stretch. The same code rebuilds
the chunks at approval when the reviewer widened or added a stretch.
"""

from __future__ import annotations

from preached.corpus import chunk_text, word_tokens
from preached.exclusions import boundary_flags

PAUSE_S = 1.5
# ASR chunk ids live in their own namespace. Canonical (CCEL) ids are
# "{sermon_id}-cNNNN" with no colon, so a church sermon whose id reuses a CCEL
# sermon id can never hit chunks.chunk_id UNIQUE and fail the rebuild.
ASR_ID_PREFIX = "asr:"


def asr_chunk_id(sermon_id: str, index: int) -> str:
    return f"{ASR_ID_PREFIX}{sermon_id}-c{index:04d}"


def token_offsets(texts: list[str]) -> list[int]:
    """Index of each word's first token in the whole sermon's token stream."""
    offsets, total = [], 0
    for text in texts:
        offsets.append(total)
        total += len(word_tokens(text))
    return offsets


def run_pieces(run: list[dict], config: dict, pause_s: float = PAUSE_S) -> list[dict]:
    """``chunk_text`` over one kept run; ``word_start``/``word_end`` are sermon token offsets.

    Each word is ``{"i", "s", "e", "t", "k"}``: word index, start, end, text
    and the index of its first token in the whole sermon.
    """
    owner: list[int] = []
    pieces: list[str] = []
    for index, word in enumerate(run):
        if index and word["s"] - run[index - 1]["e"] >= pause_s:
            pieces.append("\n\n")
        elif index:
            pieces.append(" ")
        pieces.append(word["t"])
        owner.extend([index] * len(word_tokens(word["t"])))
    text = "".join(pieces)
    if len(owner) != len(word_tokens(text)):
        raise RuntimeError("token map does not match the transcript text")
    base = run[0]["k"] if run else 0
    out = []
    for piece in chunk_text(text, config):
        first = run[owner[piece["word_start"]]]
        last = run[owner[piece["word_end"] - 1]]
        out.append({
            **piece,
            "first": owner[piece["word_start"]],
            "last": owner[piece["word_end"] - 1],
            "start_s": first["s"],
            "end_s": last["e"],
            "word_start": base + piece["word_start"],
            "word_end": base + piece["word_end"],
        })
    return out


def church_records(
    runs: list[list[dict]],
    config: dict,
    *,
    sermon_id: str,
    title: str,
    meta: dict,
    token: str,
    items: list,
    pause_s: float = PAUSE_S,
    count: int,
) -> list[dict]:
    """The chunk records for the kept runs of one church sermon, gate-keyed and flagged.

    ``count`` is the sermon's word count. The chunks on either side of an
    excluded stretch are flagged too (``exclusions.boundary_flags``).
    """
    records = []
    for run, (head, tail) in zip(runs, boundary_flags(runs, count)):
        pieces = run_pieces(run, config, pause_s)
        for number, piece in enumerate(pieces):
            words = run[piece["first"] : piece["last"] + 1]
            ends = [w["e"] for w in words if token in w["t"]]
            ends += [i["end"] for i in items or () if i["start"] < piece["end_s"] and i["end"] > piece["start_s"]]
            ends += [v for v in (head if number == 0 else None, tail if number == len(pieces) - 1 else None) if v is not None]
            records.append({
                "chunk_id": asr_chunk_id(sermon_id, len(records)),
                "sermon_id": sermon_id,
                "sermon_title": title,
                "text": piece["text"],
                "start_s": piece["start_s"],
                "end_s": piece["end_s"],
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
                "video_id": sermon_id,
                "flag_end_s": max(ends) if ends else None,
            })
    return records
