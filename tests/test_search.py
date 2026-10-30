"""FTS query shaping, fusion, and graded retrieval metrics."""

from __future__ import annotations

import unittest

from preached.fts import scripture_match, to_fts_query
from preached.metrics import mrr_at, ndcg_at, recall_at
from preached.rank import reciprocal_rank_fusion, weighted_fusion


class FtsTests(unittest.TestCase):
    def test_scripture_uses_wesley_abbreviation(self) -> None:
        match = scripture_match("Romans 8:16")
        self.assertIsNotNone(match)
        self.assertIn('"rom"', match)
        self.assertIn('"8"', match)
        self.assertIn('"16"', match)

    def test_long_question_is_or(self) -> None:
        query = to_fts_query(
            "What should a Christian do when anxious about money, health, and tomorrow?"
        )
        self.assertIn(" OR ", query)
        self.assertNotIn("wesley", query.lower())

    def test_short_keyword_is_and(self) -> None:
        query = to_fts_query("Christian perfection")
        self.assertIn(" AND ", query)
        self.assertIn("Christian", query)
        self.assertIn("perfection", query)


class MetricTests(unittest.TestCase):
    def test_recall_and_mrr(self) -> None:
        quotes = [{"quote": "take no thought for the morrow", "grade": 2}]
        ranked = ["unrelated words", "he said take no thought for the morrow and rest"]
        self.assertEqual(recall_at(ranked, quotes, 5), 1.0)
        self.assertEqual(mrr_at(ranked, quotes, 10), 0.5)
        self.assertEqual(mrr_at(["nothing here"], quotes, 10), 0.0)

    def test_overlap_counts_once(self) -> None:
        quotes = [{"quote": "the witness of the Spirit", "grade": 2}]
        ranked = [
            "the witness of the Spirit is the Spirit itself",
            "again the witness of the Spirit is repeated by overlap",
        ]
        # Ideal is one grade-2 hit. Finding it at rank 1 is perfect even
        # though the next chunk repeats it.
        self.assertAlmostEqual(ndcg_at(ranked, quotes, 10), 1.0)

    def test_ndcg_prefers_higher_grade_first(self) -> None:
        quotes = [
            {"quote": "directly answers the question here", "grade": 2},
            {"quote": "only related background material", "grade": 1},
        ]
        good = [
            "directly answers the question here in Wesley's words",
            "only related background material follows",
        ]
        bad = [
            "only related background material follows",
            "directly answers the question here in Wesley's words",
        ]
        self.assertGreater(ndcg_at(good, quotes, 10), ndcg_at(bad, quotes, 10))


class FusionTests(unittest.TestCase):
    def test_rrf_rewards_agreement(self) -> None:
        fused = reciprocal_rank_fusion([[2, 1, 3], [2, 4, 1]], k=60)
        self.assertEqual(fused[0][0], 2)
        self.assertGreater(fused[0][1], fused[1][1])

    def test_weighted_uses_both_lists(self) -> None:
        fused = weighted_fusion([(1, 0.9), (2, 0.1)], [(2, 5.0), (3, 1.0)], dense_weight=0.5)
        ids = [rowid for rowid, _ in fused]
        self.assertEqual(set(ids), {1, 2, 3})


if __name__ == "__main__":
    unittest.main()
