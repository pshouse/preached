"""Fuse BM25 and dense rankings.

RRF uses k=60 (the usual Cormack value): score = sum 1/(k+rank).
Weighted fusion min-max normalizes each list, then
``dense_weight * dense + (1-dense_weight) * bm25``. A hit that only one
list returned is treated as the floor (0) of that list.
"""

from __future__ import annotations

import numpy as np


def dense_scores(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Cosine, because both sides are L2-normalized."""
    return matrix @ query.astype(np.float32)


def top_indices(scores: np.ndarray, limit: int) -> np.ndarray:
    limit = min(limit, scores.shape[0])
    if limit <= 0:
        return np.array([], dtype=np.int64)
    if limit == scores.shape[0]:
        return np.argsort(-scores)
    picked = np.argpartition(-scores, limit - 1)[:limit]
    return picked[np.argsort(-scores[picked])]


def dense_hits(rowids: list[int], scores: np.ndarray, limit: int) -> list[tuple[int, float]]:
    chosen = top_indices(scores, limit)
    return [(rowids[int(index)], float(scores[int(index)])) for index in chosen]


def reciprocal_rank_fusion(
    rankings: list[list[int]],
    k: int = 60,
    weights: list[float] | None = None,
) -> list[tuple[int, float]]:
    weights = weights or [1.0] * len(rankings)
    scores: dict[int, float] = {}
    for weight, ranking in zip(weights, rankings):
        for rank, rowid in enumerate(ranking, start=1):
            scores[rowid] = scores.get(rowid, 0.0) + weight / (k + rank)
    ordered = sorted(scores, key=lambda rowid: scores[rowid], reverse=True)
    return [(rowid, scores[rowid]) for rowid in ordered]


def _minmax(hits: list[tuple[int, float]]) -> dict[int, float]:
    if not hits:
        return {}
    values = [score for _, score in hits]
    low = min(values)
    high = max(values)
    span = high - low if high > low else 1.0
    return {rowid: (score - low) / span for rowid, score in hits}


def weighted_fusion(
    dense: list[tuple[int, float]],
    lexical: list[tuple[int, float]],
    dense_weight: float = 0.5,
) -> list[tuple[int, float]]:
    dense_norm = _minmax(dense)
    lexical_norm = _minmax(lexical)
    scored = []
    for rowid in set(dense_norm) | set(lexical_norm):
        score = dense_weight * dense_norm.get(rowid, 0.0) + (1.0 - dense_weight) * lexical_norm.get(rowid, 0.0)
        scored.append((rowid, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored
