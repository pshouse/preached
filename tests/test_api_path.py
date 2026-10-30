"""The benchmark scores the same list GET /api/search returns, and excerpts drop CCEL paragraph numbers."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from preached.search import SEARCH_POOL, Hit, api_search, dedupe_adjacent, display_excerpt

ROOT = Path(__file__).resolve().parents[1]


def hit(chunk_id: str, score: float, word_start: int, word_end: int, sermon_id: str = "wesley-001") -> Hit:
    return Hit(
        rowid=word_start,
        score=score,
        chunk_id=chunk_id,
        sermon_id=sermon_id,
        sermon_title="Salvation by Faith",
        text=f"{chunk_id} text",
        start_s=None,
        end_s=None,
        source_url=None,
        scripture=None,
        word_start=word_start,
        word_end=word_end,
    )


# 12 hits, ranked: c0 overlaps c1, c2 overlaps c3, ... so de-dup keeps every other one.
POOL = [hit(f"c{i}", 100 - i, i * 60, i * 60 + 80) for i in range(24)]


class FakeSearcher:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def bm25(self, query, limit):
        self.calls.append(("bm25", limit))
        return POOL[:limit]

    def dense(self, vector, limit):
        self.calls.append(("dense", limit))
        return POOL[:limit]

    def hybrid(self, query, vector, limit, fusion="rrf", rrf_k=60, dense_weight=0.5, candidates=100):
        self.calls.append(("hybrid", limit, fusion, rrf_k))
        return POOL[:limit]


def load_bench():
    spec = importlib.util.spec_from_file_location("preached_bench", ROOT / "search" / "bench.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ApiPathTests(unittest.TestCase):
    def test_api_search_asks_for_the_pool_then_dedupes_to_k(self) -> None:
        searcher = FakeSearcher()
        kept = api_search(searcher, "grace", object(), "hybrid", 10)
        self.assertEqual(searcher.calls, [("hybrid", SEARCH_POOL, "rrf", 60)])
        self.assertEqual(SEARCH_POOL, 100)
        self.assertEqual(len(kept), 10)
        self.assertEqual([h.chunk_id for h in kept], [h.chunk_id for h in dedupe_adjacent(POOL, 10)])
        # Raw top 10 would repeat overlapping neighbours; the API list does not.
        self.assertNotEqual([h.chunk_id for h in kept], [h.chunk_id for h in POOL[:10]])

    def test_unknown_mode_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            api_search(FakeSearcher(), "grace", None, "hybrid_weighted", 10)

    def test_bench_dedupe_mode_is_the_api_path(self) -> None:
        bench = load_bench()
        for bench_mode, api_mode in (("bm25", "bm25"), ("dense", "dense"), ("hybrid_rrf", "hybrid")):
            via_bench = bench.run_mode(FakeSearcher(), "grace", object(), bench_mode, dedupe=True)
            via_api = api_search(FakeSearcher(), "grace", object(), api_mode, 10)
            self.assertEqual([h.chunk_id for h in via_bench], [h.chunk_id for h in via_api], bench_mode)
        raw = FakeSearcher()
        self.assertEqual(len(bench.run_mode(raw, "grace", object(), "hybrid_rrf")), 10)
        self.assertEqual(raw.calls, [("hybrid", 10, "rrf", 60)])
        weighted = FakeSearcher()
        kept = bench.run_mode(weighted, "grace", object(), "hybrid_weighted", dedupe=True)
        self.assertEqual(weighted.calls, [("hybrid", SEARCH_POOL, "weighted", 60)])
        self.assertEqual(len(kept), 10)


class DisplayExcerptTests(unittest.TestCase):
    def test_paragraph_numbers_are_removed(self) -> None:
        cases = {
            '"By grace are ye saved through faith." Eph. 2:8. 1. All the blessings':
                '"By grace are ye saved through faith." Eph. 2:8. All the blessings',
            'to myself justice!" 8. Nearly related': 'to myself justice!" Nearly related',
            "3. Thirdly. The faith": "Thirdly. The faith",
            "of God. 11. But here": "of God. But here",
            "that cup. IV. 1. But as plainly": "that cup. But as plainly",
            "heart.\u201d 7. \u201cThis": "heart.\u201d \u201cThis",
        }
        for raw, shown in cases.items():
            self.assertEqual(display_excerpt(raw), shown, raw)

    def test_other_numbers_are_kept(self) -> None:
        for text in (
            "The first objection is, 1. That to preach",
            "in Christ Jesus 4. And being saved",
            "see p. 5. And then",
            "Romans 8:16 and Psalm 23",
            "in the year 1738. we",
            "",
        ):
            self.assertEqual(display_excerpt(text), text)


if __name__ == "__main__":
    unittest.main()
