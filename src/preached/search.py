"""Search the Wesley chunk index. BM25, dense, or hybrid.

Chunks overlap their neighbors by about 25% (see corpus/chunk_config.json).
``dedupe_adjacent`` drops a lower-ranked hit when it repeats a hit already
kept from the same sermon, so a result list does not show those words twice.
"""

from __future__ import annotations

import logging
import math
import re
import sqlite3
from dataclasses import dataclass

import numpy as np

from preached.rank import dense_hits, dense_scores, reciprocal_rank_fusion, top_indices, weighted_fusion
from preached.store import bm25_search, check_fingerprint, load_embeddings, visible_count, visible_rowids, visible_sql

CANDIDATES = 100
# GET /api/search asks the ranker for this many hits, then de-dups down to k.
SEARCH_POOL = 100
API_MODES = ("hybrid", "bm25", "dense")

# Adjacent text chunks share a sentence boundary. Eight words is enough to
# call that a repeat, and short enough to catch the 25% overlap on a short
# chunk. A single shared word is not.
BOUNDARY_WORDS = 8
# Timestamp fallback when word offsets are missing. Ignore a sub-second
# touch that is just float rounding.
TIME_OVERLAP_S = 0.4

# Player pre-roll. start_s stays the true onset of the chunk's first word
# (honest for citations, same on the canonical and ASR paths); only the play
# position starts this much earlier. W1-C's measured chunk starts are off by
# a median 0.42 s and at most 0.76 s against the audio, sometimes late, so
# 0.75 s keeps the first word. app/static/app.js uses the same value.
PREROLL_S = 0.75


def play_start(start_s: float | None) -> float | None:
    """Where the player seeks for a passage: max(0, start_s - PREROLL_S)."""
    if start_s is None:
        return None
    value = float(start_s)
    if not math.isfinite(value) or value < 0:  # NaN, +/-inf or negative: no seek (JS Number.isFinite)
        return None
    return max(0.0, round(value - PREROLL_S, 2))


@dataclass
class Hit:
    rowid: int
    score: float
    chunk_id: str
    sermon_id: str
    sermon_title: str
    text: str
    start_s: float | None
    end_s: float | None
    source_url: str | None
    scripture: str | None
    sermon_number: int | None = None
    audio_url: str | None = None
    reader: str | None = None
    text_source: str | None = None
    word_start: int | None = None
    word_end: int | None = None
    video_id: str | None = None
    flag_end_s: float | None = None


class Searcher:
    def __init__(
        self,
        connection: sqlite3.Connection,
        model: str | None = None,
        fingerprint: str | None = None,
        gated: bool = False,
    ):
        """model: a key in search/models.toml. Its stored document vectors
        must carry the fingerprint the config gives now (or `fingerprint`,
        when passed); otherwise EmbeddingMismatch is raised instead of
        silently mixing old document vectors with new query vectors.

        gated: this file is a church library, so the publish gate applies even
        if its schema is incomplete (see ``store.visible_sql``)."""
        self.connection = connection
        self.model = model
        self.gated = gated
        self._fingerprint = fingerprint
        self._rowids: list[int] | None = None
        self._matrix: np.ndarray | None = None
        if model:
            if fingerprint is None:
                from preached.models import MODELS

                if model not in MODELS:
                    raise RuntimeError(f"unknown model {model!r}; see search/models.toml")
                self._fingerprint = MODELS[model].fingerprint()
            self._load_vectors()
        self._version = self._data_version()

    # The publish gate is checked on every call, in SQL, against the file as
    # it is now (store.visible_sql): nothing cached here decides what is
    # served. Rows are read per call too, so a --redo never serves stale text.
    # Vectors are cached; when another process commits (an import or an
    # approval), they are reloaded so new sermons become findable by dense.

    def _data_version(self) -> int:
        return int(self.connection.execute("PRAGMA data_version").fetchone()[0])

    def _load_vectors(self) -> None:
        check_fingerprint(self.connection, self.model, self._fingerprint)
        self._rowids, self._matrix = load_embeddings(self.connection, self.model)

    def _refresh(self) -> None:
        version = self._data_version()
        if version == self._version:
            return
        self._version = version
        if self.model:
            try:
                self._load_vectors()
            except Exception:
                logging.exception("could not reload vectors after the index changed; keeping the old ones")

    def _where(self) -> str | None:
        return visible_sql(self.connection, "chunks", gated=self.gated)

    def _pack(self, scored: list[tuple[int, float]], limit: int, where: str | None) -> list[Hit]:
        scored = scored[:limit]
        if not scored:
            return []
        rows = {}
        wanted = [rowid for rowid, _ in scored]
        sql = f"SELECT * FROM chunks WHERE rowid IN ({', '.join('?' * len(wanted))})"
        if where:
            sql += f" AND {where}"
        for row in self.connection.execute(sql, wanted):
            rows[int(row["rowid"])] = row
        return [hit_from_row(rows[rowid], score) for rowid, score in scored if rowid in rows]

    def _lexical(self, query: str, limit: int, where: str | None) -> list[tuple[int, float]]:
        """BM25 over chunks visible now; the gate is part of the query."""
        return bm25_search(self.connection, query, limit, where)

    def _semantic(self, vector: np.ndarray, limit: int, where: str | None) -> list[tuple[int, float]]:
        scores = dense_scores(vector, self._matrix)
        if where is None:
            return dense_hits(self._rowids, scores, limit)
        # Walk the full ranking and keep the first ``limit`` rows visible now.
        order = top_indices(scores, scores.shape[0])
        kept: list[tuple[int, float]] = []
        for start in range(0, len(order), max(limit, 1) * 4):
            batch = [(self._rowids[int(i)], float(scores[int(i)])) for i in order[start : start + max(limit, 1) * 4]]
            visible = visible_rowids(self.connection, [rowid for rowid, _ in batch], gated=self.gated)
            kept.extend(item for item in batch if item[0] in visible)
            if len(kept) >= limit:
                break
        return kept[:limit]

    def bm25(self, query: str, limit: int) -> list[Hit]:
        where = self._where()
        return self._pack(self._lexical(query, limit, where), limit, where)

    def visible_count(self) -> int:
        return visible_count(self.connection, gated=self.gated)

    def dense(self, vector: np.ndarray, limit: int) -> list[Hit]:
        self._refresh()
        if self._matrix is None or self._rowids is None:
            raise RuntimeError("dense search needs a model index")
        where = self._where()
        return self._pack(self._semantic(vector, limit, where), limit, where)

    def hybrid(
        self,
        query: str,
        vector: np.ndarray,
        limit: int,
        fusion: str = "rrf",
        rrf_k: int = 60,
        dense_weight: float = 0.5,
        candidates: int = CANDIDATES,
    ) -> list[Hit]:
        self._refresh()
        if self._matrix is None or self._rowids is None:
            raise RuntimeError("hybrid search needs a model index")
        where = self._where()
        lexical = self._lexical(query, candidates, where)
        semantic = self._semantic(vector, candidates, where)
        if fusion == "weighted":
            fused = weighted_fusion(semantic, lexical, dense_weight=dense_weight)
        elif fusion == "rrf":
            fused = reciprocal_rank_fusion(
                [[rowid for rowid, _ in semantic], [rowid for rowid, _ in lexical]],
                k=rrf_k,
            )
        else:
            raise RuntimeError(f"unknown fusion {fusion}")
        return self._pack(fused, limit, where)


def row_value(row: sqlite3.Row, key: str):
    """Column value, or None when the column was never added.

    W1-C may add ``audio_url``, ``reader``, and ``text_source``. An older
    index simply lacks those columns. NULL and a missing column are the
    same for the page.
    """
    if key not in row.keys():
        return None
    return row[key]


def _optional_float(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _optional_int(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _text_or_none(value) -> str | None:
    if not isinstance(value, str) or value.strip() == "":
        return None
    return value


def hit_from_row(row: sqlite3.Row, score: float) -> Hit:
    return Hit(
        rowid=int(row["rowid"]),
        score=float(score),
        chunk_id=row["chunk_id"],
        sermon_id=row["sermon_id"],
        sermon_title=row["sermon_title"],
        text=row["text"],
        start_s=_optional_float(row_value(row, "start_s")),
        end_s=_optional_float(row_value(row, "end_s")),
        source_url=_text_or_none(row_value(row, "source_url")),
        scripture=_text_or_none(row_value(row, "scripture")),
        sermon_number=_optional_int(row_value(row, "sermon_number")),
        audio_url=_text_or_none(row_value(row, "audio_url")),
        reader=_text_or_none(row_value(row, "reader")),
        text_source=_text_or_none(row_value(row, "text_source")),
        word_start=_optional_int(row_value(row, "word_start")),
        word_end=_optional_int(row_value(row, "word_end")),
        video_id=_text_or_none(row_value(row, "video_id")),
        flag_end_s=_optional_float(row_value(row, "flag_end_s")),
    )


def _span_overlap(a0, a1, b0, b1) -> float | None:
    if None in (a0, a1, b0, b1):
        return None
    return min(a1, b1) - max(a0, b0)


def _words(text: str) -> list[str]:
    return [word.casefold() for word in text.split()]


def boundary_overlap(a: str, b: str, minimum: int = BOUNDARY_WORDS) -> bool:
    """True when two excerpts share a prefix/suffix, the shape of a 25% overlap.

    A sentence quoted again in the middle of another chunk does not count.
    The shared run has to sit on the boundary between the two excerpts.
    Identical text counts, so a duplicated chunk is not shown twice.
    """
    wa = _words(a)
    wb = _words(b)
    if not wa or not wb:
        return False
    if wa == wb:
        return True
    limit = min(len(wa), len(wb))
    if limit < minimum:
        return False
    for size in range(limit, minimum - 1, -1):
        if wa[-size:] == wb[:size] or wb[-size:] == wa[:size]:
            return True
    return False


def repeats_kept(hit: Hit, kept: Hit) -> bool:
    """Whether ``hit`` repeats words already shown in ``kept``.

    Rule, in order:

    1. Different sermons never collapse.
    2. The same ``chunk_id`` collapses.
    3. If both chunks have word offsets, they collapse only when those
       ranges overlap. The chunker overlaps only adjacent windows (25%),
       so this is the adjacent-passage case. A later non-overlapping
       passage from the same sermon stays.
    4. If word offsets are missing and both chunks have timestamps, they
       collapse when the times overlap by at least ``TIME_OVERLAP_S``.
    5. If those spans are missing too, they collapse when the texts share
       a boundary run of at least ``BOUNDARY_WORDS`` (or are identical).
    """
    if hit.sermon_id != kept.sermon_id:
        return False
    if hit.chunk_id and hit.chunk_id == kept.chunk_id:
        return True
    word_overlap = _span_overlap(hit.word_start, hit.word_end, kept.word_start, kept.word_end)
    if word_overlap is not None:
        return word_overlap > 0
    time_overlap = _span_overlap(hit.start_s, hit.end_s, kept.start_s, kept.end_s)
    if time_overlap is not None:
        return time_overlap >= TIME_OVERLAP_S
    return boundary_overlap(hit.text or "", kept.text or "")


def dedupe_adjacent(hits: list[Hit], limit: int) -> list[Hit]:
    """Keep the best ``limit`` hits that do not repeat an adjacent neighbor.

    Higher score wins. Ties keep the earlier hit. The caller should pass a
    wider pool than ``limit`` so dropping a neighbor still leaves a full page.
    """
    if limit <= 0:
        return []
    ordered = sorted(enumerate(hits), key=lambda item: (-item[1].score, item[0]))
    kept: list[Hit] = []
    for _, hit in ordered:
        if any(repeats_kept(hit, previous) for previous in kept):
            continue
        kept.append(hit)
        if len(kept) >= limit:
            break
    return kept


def ranked(searcher: Searcher, query: str, vector, mode: str, limit: int) -> list[Hit]:
    """One ranker's top ``limit`` for an API mode, before de-dup.

    ``hybrid`` is reciprocal rank fusion with k=60 over the top 100 of BM25
    and dense. ``vector`` may be None for ``bm25``.
    """
    if mode == "bm25":
        return searcher.bm25(query, limit)
    if mode == "dense":
        return searcher.dense(vector, limit)
    if mode == "hybrid":
        return searcher.hybrid(query, vector, limit, fusion="rrf", rrf_k=60)
    raise ValueError(f"unknown mode {mode}")


def api_search(
    searcher: Searcher,
    query: str,
    vector,
    mode: str,
    k: int,
    pool: int = SEARCH_POOL,
) -> list[Hit]:
    """Exactly what GET /api/search ranks: top ``pool``, then ``dedupe_adjacent`` to ``k``.

    The server and ``search/bench.py --dedupe`` both call this, so the
    benchmark measures the list a user sees.
    """
    return dedupe_adjacent(ranked(searcher, query, vector, mode, max(pool, k)), k)


# CCEL keeps Wesley's paragraph numbers inline: "...to myself justice!" 8. Nearly
# related ...". A number (optionally after a Roman section number, "IV. 1.")
# is a paragraph number when it starts the excerpt or follows the end of a
# sentence, and a capital letter or an opening quote follows it. "Eph. 2:8.",
# "is, 1. That ..." (an inline list) and "p. 5." are left alone.
PARAGRAPH_NUMBER = re.compile(
    r"(^|[.!?][\"'\u201d\u2019)\]]*\s+)(?:[IVXL]{1,5}\.\s+)?\d{1,3}\.\s+(?=[\"'\u201c\u2018(\[]?[A-Z])"
)
_ABBREVIATION = re.compile(r"(?i)(?:^|\s)(?:p|pp|ver|chap|vol|no|sect|art)\.\s+$")


def display_excerpt(text: str) -> str:
    """Excerpt for the page: the indexed text minus CCEL paragraph numbers.

    Display only. The index, BM25, embeddings, and the eval are unchanged.
    """
    if not text:
        return text

    def drop(match: re.Match[str]) -> str:
        lead = match.group(1)
        if lead and _ABBREVIATION.search(text[: match.start() + len(lead)]):
            return match.group(0)
        return lead.lstrip() if match.start() == 0 else lead

    return PARAGRAPH_NUMBER.sub(drop, text)
