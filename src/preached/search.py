"""Search the Wesley chunk index. BM25, dense, or hybrid.

Chunks overlap their neighbors by about 25% (see corpus/chunk_config.json).
``dedupe_adjacent`` drops a lower-ranked hit when it repeats a hit already
kept from the same sermon, so a result list does not show those words twice.
A neighbour the ranker placed inside the requested top k is merged into the
kept hit instead of dropped when the passages stitch exactly within
``MERGE_MAX_WORDS``; otherwise it is dropped and its words outside the kept
passage are not shown.
"""

from __future__ import annotations

import logging
import math
import re
import sqlite3
from dataclasses import dataclass, field, replace

import numpy as np

from preached.rank import dense_hits, dense_scores, reciprocal_rank_fusion, weighted_fusion
from preached.store import bm25_search, check_fingerprint, load_embeddings, visible_count, visible_sql

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

# A merged passage (dedupe_adjacent) stops growing at this many words: twice
# the chunker's max_words (150, corpus/chunk_config.json), about two minutes
# read aloud. Past it the neighbour is dropped, as before merging existed,
# so a card never turns into a whole section of the sermon.
MERGE_MAX_WORDS = 300

# Player pre-roll. start_s stays the true onset of the chunk's first word
# (honest for citations, same on the canonical and ASR paths); only the play
# position starts this much earlier, as a safety margin for chunk starts that
# land late against the audio. It is a margin, not a measured bound (no
# measurement data is kept). app/static/app.js uses the same value.
PREROLL_S = 0.75


def play_start(start_s: float | None) -> float | None:
    """Where the player seeks for a passage: max(0, start_s - PREROLL_S)."""
    if start_s is None:
        return None
    value = float(start_s)
    if not math.isfinite(value) or value < 0:  # NaN, +/-inf or negative: no seek (JS Number.isFinite)
        return None
    return max(0.0, round(value - PREROLL_S, 2))


@dataclass(frozen=True)
class Why:
    """Why a hit is on the list: its place in each candidate list the ranker used.

    Ranks are 1-based positions in the gated BM25 (``keyword_rank``) and
    dense (``meaning_rank``) lists of this search; None when the hit is not
    in that list or the mode did not run it. ``similarity`` is the dense
    cosine from the same list, rounded to 3 decimals. Built only in
    ``Searcher._pack`` from the lists ``_lexical`` and ``_semantic`` returned
    through the publish gate, so a hidden row never moves a visible rank.
    """

    keyword_rank: int | None
    meaning_rank: int | None
    similarity: float | None

    @property
    def found_by(self) -> str:
        if self.keyword_rank is not None and self.meaning_rank is not None:
            return "both"
        return "keyword" if self.keyword_rank is not None else "meaning"

    def as_dict(self) -> dict:
        return {
            "keyword_rank": self.keyword_rank,
            "meaning_rank": self.meaning_rank,
            "similarity": self.similarity,
            "found_by": self.found_by,
        }


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
    # Every chunk in this passage, in reading order, when dedupe_adjacent
    # merged overlapping neighbours into it. Empty means just chunk_id.
    merged_ids: tuple[str, ...] = ()
    # Set by Searcher._pack (see Why). Not part of equality: two hits with
    # the same row and score are the same passage however they were found.
    why: Why | None = field(default=None, compare=False)

    @property
    def chunk_ids(self) -> list[str]:
        return list(self.merged_ids) if self.merged_ids else [self.chunk_id]


@dataclass
class Visible:
    """What a gated file may serve right now (``Searcher._visible``)."""

    fts: sqlite3.Connection
    rowids: list[int]
    matrix: np.ndarray | None


class Searcher:
    def __init__(
        self,
        connection: sqlite3.Connection,
        model: str | None = None,
        fingerprint: str | None = None,
        gated: bool = False,
        library: str | None = None,
        *,
        allow_eval_only: bool = False,
    ):
        """model: a key in search/models.toml. Its stored document vectors
        must carry the fingerprint the config gives now (or `fingerprint`,
        when passed); otherwise EmbeddingMismatch is raised instead of
        silently mixing old document vectors with new query vectors.

        gated: this file is a church library, so the publish gate applies even
        if its schema is incomplete (see ``store.visible_sql``).

        library: the slug this file is served as. Only an allow-listed
        public-domain library's own file is exempt from the gate
        (``store.public_domain_file``, re-checked per call).

        allow_eval_only: only the evaluation harnesses (search/bench.py,
        eval/pool.py, scripts/check_*.py) pass this, to score eval-only
        models. The product never does."""
        self.connection = connection
        self.model = model
        self._gated = bool(gated)
        self.library = library
        self._fingerprint = fingerprint
        self._rowids: list[int] | None = None
        self._matrix: np.ndarray | None = None
        # The rows visible now, for search on a gated file (``_visible``).
        self._visible_cache: Visible | None = None
        self._visible_key: tuple | None = None
        if model:
            from preached.models import MODELS

            # An explicit fingerprint is for fixture models that are not in
            # models.toml; a configured eval-only model is refused unless the
            # evaluation harness opts in.
            if not allow_eval_only and model in MODELS and MODELS[model].eval_only:
                raise RuntimeError(f"model {model!r} is eval-only and cannot be used by the product")
            if fingerprint is None:
                if model not in MODELS:
                    raise RuntimeError(f"unknown model {model!r}; see search/models.toml")
                self._fingerprint = MODELS[model].fingerprint()
            self._load_vectors()
        self._version = self._data_version()

    @property
    def gated(self) -> bool:
        """Read-only: ``s.gated = False`` and ``setattr`` raise AttributeError.
        ``gate_on`` turns it on; nothing turns it off."""
        return self._gated

    def gate_on(self) -> None:
        """Apply the publish gate from now on (``App`` does this for every library but wesley)."""
        self._gated = True

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
        return visible_sql(self.connection, "chunks", gated=self.gated, library=self.library)

    def _pack(
        self,
        scored: list[tuple[int, float]],
        limit: int,
        where: str | None,
        lexical: list[tuple[int, float]] | None = None,
        semantic: list[tuple[int, float]] | None = None,
    ) -> list[Hit]:
        """Rows for the top ``limit`` of ``scored``. ``lexical`` and
        ``semantic`` are the candidate lists ``scored`` came from (None when
        the mode did not run one); each hit's ``why`` is read off them."""
        scored = scored[:limit]
        if not scored:
            return []
        keyword = {rowid: rank for rank, (rowid, _) in enumerate(lexical or (), start=1)}
        meaning = {rowid: (rank, cosine) for rank, (rowid, cosine) in enumerate(semantic or (), start=1)}
        rows = {}
        wanted = [rowid for rowid, _ in scored]
        sql = f"SELECT * FROM chunks WHERE rowid IN ({', '.join('?' * len(wanted))})"
        if where:
            sql += f" AND {where}"
        for row in self.connection.execute(sql, wanted):
            rows[int(row["rowid"])] = row
        hits = []
        for rowid, score in scored:
            if rowid not in rows:
                continue
            rank, cosine = meaning.get(rowid, (None, None))
            hit = hit_from_row(rows[rowid], score)
            hit.why = Why(keyword.get(rowid), rank, None if cosine is None else round(float(cosine), 3))
            hits.append(hit)
        return hits

    def _lexical(self, query: str, limit: int, where: str | None) -> list[tuple[int, float]]:
        """BM25 over chunks visible now.

        Filtering the file's own FTS index is not enough on a gated file:
        SQLite's bm25() takes its term statistics (row count, document
        frequency, mean length) from every indexed row, hidden ones
        included, so the scores and the order of visible rows would change
        with what an unpublished sermon says. A gated file is searched in a
        private in-memory index of the visible rows only, which scores
        exactly as a file that never held the hidden ones.
        """
        if where is None:
            return bm25_search(self.connection, query, limit)
        return bm25_search(self._visible(where).fts, query, limit)

    def _semantic(self, vector: np.ndarray, limit: int, where: str | None) -> list[tuple[int, float]]:
        """Dense over chunks visible now. On a gated file only the visible
        rows are scored, so no hidden row changes a score (BLAS rounding
        depends on the matrix shape) or how long the search takes."""
        if where is None:
            return dense_hits(self._rowids, dense_scores(vector, self._matrix), limit)
        visible = self._visible(where)
        if not visible.rowids:
            return []
        return dense_hits(visible.rowids, dense_scores(vector, visible.matrix), limit)

    def _visible(self, where: str) -> Visible:
        """The visible rows: an FTS5 copy and their vectors. Rebuilt when the
        file changes (``PRAGMA data_version``), the gate condition changes, or
        the vectors are reloaded."""
        key = (self._data_version(), where, id(self._matrix))
        if self._visible_cache is not None and self._visible_key == key:
            return self._visible_cache
        rows = self.connection.execute(
            f"SELECT rowid, text, sermon_title, coalesce(scripture, '') FROM chunks WHERE {where} ORDER BY rowid"
        ).fetchall()
        memory = sqlite3.connect(":memory:", check_same_thread=False)
        memory.row_factory = sqlite3.Row
        memory.execute(
            "CREATE VIRTUAL TABLE chunks_fts USING fts5("
            f"text, sermon_title, scripture, tokenize={fts_tokenizer(self.connection)!r})"
        )
        memory.executemany("INSERT INTO chunks_fts(rowid, text, sermon_title, scripture) VALUES (?, ?, ?, ?)", rows)
        memory.commit()
        rowids: list[int] = []
        matrix = None
        if self._matrix is not None and self._rowids is not None:
            position = {rowid: index for index, rowid in enumerate(self._rowids)}
            rowids = [int(row[0]) for row in rows if int(row[0]) in position]
            matrix = self._matrix[[position[rowid] for rowid in rowids]]
        if self._visible_cache is not None:
            self._visible_cache.fts.close()
        self._visible_cache, self._visible_key = Visible(memory, rowids, matrix), key
        return self._visible_cache

    def bm25(self, query: str, limit: int) -> list[Hit]:
        where = self._where()
        lexical = self._lexical(query, limit, where)
        return self._pack(lexical, limit, where, lexical=lexical)

    def visible_count(self) -> int:
        return visible_count(self.connection, gated=self.gated, library=self.library)

    def dense(self, vector: np.ndarray, limit: int) -> list[Hit]:
        self._refresh()
        if self._matrix is None or self._rowids is None:
            raise RuntimeError("dense search needs a model index")
        where = self._where()
        semantic = self._semantic(vector, limit, where)
        return self._pack(semantic, limit, where, semantic=semantic)

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
        return self._pack(fused, limit, where, lexical=lexical, semantic=semantic)


FTS_TOKENIZE = re.compile(r"tokenize\s*=\s*'((?:[^']|'')*)'", re.IGNORECASE)


def fts_tokenizer(connection: sqlite3.Connection) -> str:
    """The ``tokenize`` option of the file's ``chunks_fts`` (store.SCHEMA: ``porter unicode61``)."""
    row = connection.execute("SELECT sql FROM sqlite_master WHERE name = 'chunks_fts'").fetchone()
    match = FTS_TOKENIZE.search(row[0] if row and row[0] else "")
    return match.group(1).replace("''", "'") if match else "porter unicode61"


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


def _boundary_size(first: list[str], second: list[str]) -> int:
    """Longest run that ends ``first`` and starts ``second`` (0 if none)."""
    for size in range(min(len(first), len(second)), 0, -1):
        if first[-size:] == second[:size]:
            return size
    return 0


def merge_overlapping(kept: Hit, neighbour: Hit, max_words: int = MERGE_MAX_WORDS) -> Hit | None:
    """One passage covering both overlapping chunks, or None if they cannot
    be stitched exactly.

    The merged hit keeps ``kept``'s score and chunk_id (its rank does not
    move). Text, word span, ``start_s`` and ``end_s`` cover both chunks, so
    the player starts at the merged passage's first word. Only chunks with
    word offsets, from the same sermon, audio file and text source, whose
    texts share a boundary run (the chunker's sentence overlap) are merged.
    Anything else, or a merge longer than ``max_words``, returns None and
    the caller drops the neighbour as before.

    Privacy: chunks are never merged when either side is flagged
    (``flag_end_s`` set: a ``[name]`` or review item, see
    ``preached.audio_policy``), or when their ``video_id``s differ. A merged
    card keeps only ``kept``'s flag fields, so merging a flagged neighbour
    into an unflagged card would give it a normal play link over the name.
    """
    if kept.sermon_id != neighbour.sermon_id or kept.video_id != neighbour.video_id:
        return None
    if kept.flag_end_s is not None or neighbour.flag_end_s is not None:
        return None
    if None in (kept.word_start, kept.word_end, neighbour.word_start, neighbour.word_end):
        return None
    if kept.audio_url != neighbour.audio_url or kept.text_source != neighbour.text_source:
        return None
    if neighbour.word_start >= kept.word_start and neighbour.word_end <= kept.word_end:
        return kept  # already inside the kept passage
    if kept.word_start >= neighbour.word_start and kept.word_end <= neighbour.word_end:
        return None  # the neighbour holds the kept passage; not an adjacent overlap
    if neighbour.word_start < kept.word_start:
        first, second = neighbour, kept
    else:
        first, second = kept, neighbour
    first_words = (first.text or "").split()
    second_words = (second.text or "").split()
    size = _boundary_size(first_words, second_words)
    if size == 0:
        return None
    words = first_words + second_words[size:]
    if len(words) > max_words:
        return None
    return replace(
        kept,
        text=" ".join(words),
        word_start=first.word_start,
        word_end=second.word_end,
        start_s=first.start_s,
        end_s=second.end_s,
        merged_ids=tuple(first.chunk_ids + second.chunk_ids),
    )


def dedupe_adjacent(hits: list[Hit], limit: int) -> list[Hit]:
    """Keep the best ``limit`` hits that do not repeat an adjacent neighbor.

    Higher score wins. Ties keep the earlier hit. The caller should pass a
    wider pool than ``limit`` so dropping a neighbor still leaves a full page.

    A neighbour that ranks inside the top ``limit`` (so the list without
    de-dup would have shown it) is merged into the kept passage(s) it
    overlaps (``merge_overlapping``) when every join succeeds; if any join
    fails (no exact boundary, different audio or text source, or past
    ``MERGE_MAX_WORDS``) it is dropped and the kept passages are unchanged.
    A neighbour ranked below ``limit`` is always dropped, so passages grow
    only from hits the user would have seen.

    Guaranteed: no two returned hits repeat each other by the rules of
    ``repeats_kept`` (for chunks with word offsets: same sermon, overlapping
    word ranges), so no word is shown twice; a merge never makes a passage
    longer than ``MERGE_MAX_WORDS``; and the function is idempotent
    (de-duping its own output returns the same list). Not guaranteed: every word of the plain top
    ``limit`` stays on the page. A dropped neighbour's words outside the
    kept passage are hidden, as before merging existed.
    """
    if limit <= 0:
        return []
    ordered = sorted(enumerate(hits), key=lambda item: (-item[1].score, item[0]))
    kept: list[Hit] = []
    for position, (_, hit) in enumerate(ordered):
        overlapping = [index for index, previous in enumerate(kept) if repeats_kept(hit, previous)]
        if not overlapping:
            kept.append(hit)
            if len(kept) >= limit:
                break
            continue
        if position >= limit:
            continue
        # Fold the neighbour, and any kept passage it bridges to, into the
        # best-ranked kept passage it overlaps.
        # All or nothing: if any join fails (usually the word cap), the
        # neighbour is dropped and the kept passages stay as they were.
        # A partial merge would leave the merged card overlapping the kept
        # passage it failed to absorb, so some words would show twice.
        target = overlapping[0]
        merged = merge_overlapping(kept[target], hit)
        for index in overlapping[1:]:
            if merged is None:
                break
            merged = merge_overlapping(merged, kept[index])
        if merged is None:
            continue
        kept[target] = merged
        for index in reversed(overlapping[1:]):
            del kept[index]
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


def sermon_flagged(connection: sqlite3.Connection, sermon_id: object) -> bool:
    """Whether any chunk of this sermon is flagged (``flag_end_s`` set), visible or not.

    Patrick's link rule: such a sermon keeps the timed links of its
    unflagged passages, but its untimed sermon-level links (a ``source_url``,
    a watch link with no ``t=``, an audio file with no seek) all play from
    0:00 and are dropped everywhere. Wesley's index has no ``flag_end_s``.
    """
    columns = {row[1] for row in connection.execute("PRAGMA table_info(chunks)")}
    if "flag_end_s" not in columns:
        return False
    return connection.execute(
        "SELECT 1 FROM chunks WHERE sermon_id = ? AND flag_end_s IS NOT NULL LIMIT 1", (sermon_id,)
    ).fetchone() is not None


# A link may land this much before its seek (keyframes, player rounding), and
# ASR word ends run late against the audio, so a flagged word that ends up to
# this long before the seek still counts. Measured (large-v3-turbo vs forced
# alignment, clean studio audio): word ends p95 0.12 s late, p99 0.48 s, max
# 3.58 s. p99 + 0.5 s = 0.98 s; 1.5 is that plus headroom. Never rounded: seek_time floors toward the name.
SEEK_SLACK_S = 1.5


def seek_time(start_s: float | None) -> float | None:
    """The earliest second any link for a passage starting at ``start_s`` seeks to.

    The audio player seeks to ``play_start`` (``#t=``, 0.01 s); a YouTube
    link to the whole second below it (``listing.watch_url``: ``int(start_s
    - PREROLL_S)``). The smaller of the two, or None when there is no seek.
    """
    seek = play_start(start_s)
    if seek is None:
        return None
    return min(seek, float(math.floor(max(0.0, float(start_s) - PREROLL_S))))


def touches_flagged(connection: sqlite3.Connection, hit: Hit) -> bool:
    """Whether a card's play link could reach a flagged chunk of its sermon.

    The one check for this, used by the API cards, /api/sermon and
    ``search/query.py``. True when the card itself is flagged, or when any
    chunk of the same sermon with ``flag_end_s`` set:

    - ends its flagged words after the card's seek minus SEEK_SLACK_S
      (``seek_time``) and starts before the card's end (no end: anywhere
      after). Back-to-back chunks share no words, so a word-span test alone
      let the next chunk keep a link whose pre-roll starts inside or just
      before the name (CTO round 4: ``&t=379s`` with the name at
      378.86-379.22 s). A flagged chunk with no start counts.
    - or overlaps the card's word span (its time span when it has no word span).

    A card with no seek and no span touches any flagged chunk of its sermon.
    An index without ``flag_end_s`` (Wesley) never touches one.
    """
    if hit.flag_end_s is not None:
        return True
    columns = {row[1] for row in connection.execute("PRAGMA table_info(chunks)")}
    if "flag_end_s" not in columns:
        return False
    base = "SELECT 1 FROM chunks WHERE sermon_id = ? AND flag_end_s IS NOT NULL"
    seek = seek_time(hit.start_s)
    if seek is not None and "start_s" in columns:
        sql = base + " AND flag_end_s > ?"
        args = [hit.sermon_id, seek - SEEK_SLACK_S]
        if _finite(hit.end_s):
            sql += " AND (start_s IS NULL OR start_s < ?)"
            args.append(float(hit.end_s))
        if connection.execute(sql + " LIMIT 1", args).fetchone() is not None:
            return True
    if hit.word_start is not None and hit.word_end is not None and {"word_start", "word_end"} <= columns:
        sql = base + " AND word_start < ? AND word_end > ? LIMIT 1"
        args = (hit.sermon_id, hit.word_end, hit.word_start)
    elif hit.start_s is not None and hit.end_s is not None:
        sql = base + " AND start_s < ? AND end_s > ? LIMIT 1"
        args = (hit.sermon_id, hit.end_s, hit.start_s)
    else:
        # No span to compare: any flagged chunk in the sermon counts.
        sql = base + " LIMIT 1"
        args = (hit.sermon_id,)
    return connection.execute(sql, args).fetchone() is not None


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


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
