"""FTS query shaping, fusion, and graded retrieval metrics."""

from __future__ import annotations

import unittest

import torch

from preached.embed import LoadedModel, extended_encoder_mask, format_documents, format_query
from preached.models import MODELS
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
        # SQLite 3.53 here rejects the infix "NEAR/4" form.
        self.assertIn("NEAR(", match)
        self.assertNotIn("NEAR/", match)

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


class MaskShimTests(unittest.TestCase):
    def test_encoder_mask_is_additive(self) -> None:
        mask = torch.tensor([[1, 1, 0]], dtype=torch.int64)
        extended = extended_encoder_mask(mask, mask.shape, torch.float32)
        self.assertEqual(tuple(extended.shape), (1, 1, 1, 3))
        self.assertEqual(float(extended[0, 0, 0, 0]), 0.0)
        self.assertEqual(float(extended[0, 0, 0, 1]), 0.0)
        self.assertEqual(float(extended[0, 0, 0, 2]), torch.finfo(torch.float32).min)
        # MoE code squeezes this back to a (batch, seq) keep-mask.
        keep = torch.where(extended.squeeze() == 0, 1, 0)
        self.assertEqual(keep.tolist(), [1, 1, 0])

    def test_empty_document_prompt_is_not_used(self) -> None:
        loaded = LoadedModel(
            spec=MODELS["nomic-embed-text-v2-moe"],
            model=None,
            device="cpu",
            batch_size=1,
            prompts={"document": "", "passage": "search_document: ", "query": "search_query: "},
        )
        docs, name = format_documents(loaded, ["Salvation by Faith"], ["By grace are ye saved."])
        self.assertEqual(name, "passage")
        self.assertEqual(docs, ["By grace are ye saved."])
        text, query_name = format_query(loaded, "What did Wesley say about worry?")
        self.assertEqual(query_name, "query")
        self.assertEqual(text, "What did Wesley say about worry?")


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
