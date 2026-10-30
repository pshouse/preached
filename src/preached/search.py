"""Search the Wesley chunk index. BM25, dense, or hybrid."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np

from preached.rank import dense_hits, dense_scores, reciprocal_rank_fusion, weighted_fusion
from preached.store import bm25_search, load_embeddings

CANDIDATES = 100


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


class Searcher:
    def __init__(self, connection: sqlite3.Connection, model: str | None = None):
        self.connection = connection
        self.model = model
        self._rows = {
            int(row["rowid"]): row
            for row in connection.execute("SELECT * FROM chunks")
        }
        self._rowids: list[int] | None = None
        self._matrix: np.ndarray | None = None
        if model:
            self._rowids, self._matrix = load_embeddings(connection, model)

    def _pack(self, scored: list[tuple[int, float]], limit: int) -> list[Hit]:
        hits = []
        for rowid, score in scored[:limit]:
            row = self._rows.get(rowid)
            if row is None:
                continue
            hits.append(
                Hit(
                    rowid=rowid,
                    score=score,
                    chunk_id=row["chunk_id"],
                    sermon_id=row["sermon_id"],
                    sermon_title=row["sermon_title"],
                    text=row["text"],
                    start_s=row["start_s"],
                    end_s=row["end_s"],
                    source_url=row["source_url"],
                    scripture=row["scripture"],
                )
            )
        return hits

    def bm25(self, query: str, limit: int) -> list[Hit]:
        return self._pack(bm25_search(self.connection, query, limit), limit)

    def dense(self, vector: np.ndarray, limit: int) -> list[Hit]:
        if self._matrix is None or self._rowids is None:
            raise RuntimeError("dense search needs a model index")
        scores = dense_scores(vector, self._matrix)
        return self._pack(dense_hits(self._rowids, scores, limit), limit)

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
        if self._matrix is None or self._rowids is None:
            raise RuntimeError("hybrid search needs a model index")
        lexical = bm25_search(self.connection, query, candidates)
        scores = dense_scores(vector, self._matrix)
        semantic = dense_hits(self._rowids, scores, candidates)
        if fusion == "weighted":
            fused = weighted_fusion(semantic, lexical, dense_weight=dense_weight)
        elif fusion == "rrf":
            fused = reciprocal_rank_fusion(
                [[rowid for rowid, _ in semantic], [rowid for rowid, _ in lexical]],
                k=rrf_k,
            )
        else:
            raise RuntimeError(f"unknown fusion {fusion}")
        return self._pack(fused, limit)
