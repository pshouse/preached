"""Pack sermon words into the same windows as the Wesley text chunker.

``corpus/chunk_config.json`` is the source of the sizes: about 45 seconds,
with a quarter overlap snapped to a sentence. Each chunk carries ``start_s``
and ``end_s`` from the first and last word in the window, on the video
timeline. Nothing is shifted and the audio is not cut.
"""

from __future__ import annotations

import re

from preached.youtube.words import Word

_SENTENCE_END = re.compile(r"[.!?…][\"')\]]*$")


def _sentence_end(text: str) -> bool:
    return bool(_SENTENCE_END.search(text.strip()))


def _units(words: list[Word], max_words: int) -> list[tuple[int, int]]:
    """Sentence spans as ``[start, end)`` indexes. A long sentence splits."""
    units: list[tuple[int, int]] = []
    start = 0
    for index, word in enumerate(words):
        length = index - start + 1
        if _sentence_end(word.text) or length >= max_words:
            units.append((start, index + 1))
            start = index + 1
    if start < len(words):
        units.append((start, len(words)))
    return units


def chunk_words(words: list[Word], config: dict) -> list[dict]:
    """Overlapping windows. A short sermon is still one chunk.

    ``word_start`` and ``word_end`` index ``words`` (end is exclusive) so the
    search server can drop the 25% neighbor instead of the whole sermon.
    """
    if not words:
        return []
    target = int(config["target_words"])
    minimum = int(config["min_words"])
    maximum = int(config["max_words"])
    overlap = float(config["overlap"])
    if maximum < 1:
        raise RuntimeError("max_words must be at least 1")
    units = _units(words, maximum)
    lengths = [end - start for start, end in units]
    chunks: list[dict] = []
    start_u = 0
    count = len(units)
    while start_u < count:
        words_n = 0
        end_u = start_u
        while end_u < count:
            next_words = words_n + lengths[end_u]
            if words_n > 0 and next_words > maximum:
                break
            if words_n >= target and words_n >= minimum:
                break
            words_n = next_words
            end_u += 1
            if words_n >= maximum:
                break
        if end_u == start_u:
            end_u = start_u + 1
        word_start = units[start_u][0]
        word_end = units[end_u - 1][1]
        piece = words[word_start:word_end]
        text = " ".join(word.text.strip() for word in piece if word.text.strip())
        chunks.append(
            {
                "text": text,
                "word_count": word_end - word_start,
                "word_start": word_start,
                "word_end": word_end,
                "start_s": float(piece[0].start),
                "end_s": float(piece[-1].end),
            }
        )
        if end_u >= count:
            break
        overlap_words = int((word_end - word_start) * overlap)
        back = 0
        cursor = end_u
        while cursor > start_u + 1 and back < overlap_words:
            cursor -= 1
            back += lengths[cursor]
        if cursor <= start_u:
            cursor = start_u + 1
        start_u = cursor
    return chunks
