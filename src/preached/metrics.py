"""Retrieval metrics over overlapping chunks.

Judgments are quotes, not chunk ids. A chunk hits a quote when the quote's
normalized text is contained in the chunk. Overlap means two chunks can hold
the same quote; that quote counts once, at the first chunk that contains it.

Recall@k is the fraction of grade>=1 quotes hit inside the top k chunks.
MRR@k is 1/rank of the first grade>=1 quote, or 0 if that rank is past k.
nDCG@k gives each chunk the max grade of quotes it newly covers. The ideal
list is one chunk per quote, best grade first. Queries with no relevant
quotes are omitted (nDCG is undefined when nothing is relevant).
"""

from __future__ import annotations

import math
import re


def normalize(text: str) -> str:
    text = text.lower().replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", text).strip()


def contains_quote(chunk_text: str, quote: str) -> bool:
    return normalize(quote) in normalize(chunk_text)


def _gains(ranked_texts: list[str], quotes: list[dict]) -> list[int]:
    seen: set[int] = set()
    gains: list[int] = []
    for text in ranked_texts:
        gain = 0
        for index, quote in enumerate(quotes):
            if index in seen:
                continue
            if contains_quote(text, quote["quote"]):
                gain = max(gain, int(quote["grade"]))
                seen.add(index)
        gains.append(gain)
    return gains


def dcg(gains: list[int], k: int) -> float:
    total = 0.0
    for index, gain in enumerate(gains[:k]):
        total += (2 ** gain - 1) / math.log2(index + 2)
    return total


def recall_at(ranked_texts: list[str], quotes: list[dict], k: int) -> float:
    relevant = [quote for quote in quotes if int(quote["grade"]) >= 1]
    if not relevant:
        raise ValueError("recall is undefined with no relevant quotes")
    hit = 0
    for quote in relevant:
        if any(contains_quote(text, quote["quote"]) for text in ranked_texts[:k]):
            hit += 1
    return hit / len(relevant)


def mrr_at(ranked_texts: list[str], quotes: list[dict], k: int) -> float:
    relevant = [quote for quote in quotes if int(quote["grade"]) >= 1]
    if not relevant:
        raise ValueError("mrr is undefined with no relevant quotes")
    for rank, text in enumerate(ranked_texts[:k], start=1):
        if any(contains_quote(text, quote["quote"]) for quote in relevant):
            return 1.0 / rank
    return 0.0


def ndcg_at(ranked_texts: list[str], quotes: list[dict], k: int) -> float:
    relevant = [quote for quote in quotes if int(quote["grade"]) >= 1]
    if not relevant:
        raise ValueError("ndcg is undefined with no relevant quotes")
    gains = _gains(ranked_texts, relevant)
    ideal = sorted((int(quote["grade"]) for quote in relevant), reverse=True)
    ideal_dcg = dcg(ideal, k)
    if ideal_dcg == 0:
        raise ValueError("ndcg is undefined with zero ideal gain")
    return dcg(gains, k) / ideal_dcg


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def summarize(rows: list[dict]) -> dict:
    """rows: {recall@5, mrr@10, ndcg@10} for answerable queries only."""
    return {
        "n": len(rows),
        "recall@5": mean([row["recall@5"] for row in rows]),
        "mrr@10": mean([row["mrr@10"] for row in rows]),
        "ndcg@10": mean([row["ndcg@10"] for row in rows]),
    }
