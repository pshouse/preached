"""FTS query shaping, fusion, and graded retrieval metrics."""

from __future__ import annotations

import unittest

import torch

import dataclasses

from preached.embed import extended_encoder_mask, format_documents, format_query
from preached.models import DEFAULT_MODEL, MODELS, REFERENCE
from preached.stats import bootstrap_ci, paired_bootstrap
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


class ModelConfigTests(unittest.TestCase):
    def test_every_model_is_pinned(self) -> None:
        for spec in MODELS.values():
            self.assertRegex(spec.revision, r"^[0-9a-f]{40}$", spec.key)
        self.assertIn(DEFAULT_MODEL, MODELS)
        self.assertIn(REFERENCE["model"], MODELS)

    def test_embeddinggemma_never_fp16(self) -> None:
        # The EmbeddingGemma cards say fp16 returns NaN or silently worse vectors.
        for spec in MODELS.values():
            if "embeddinggemma" in spec.hf_id:
                self.assertNotIn("fp16", (spec.dtype_gpu, spec.dtype_cpu))

    def test_gemma_prompts_match_card(self) -> None:
        spec = MODELS["embeddinggemma-2"]
        docs, prompt = format_documents(spec, ["Salvation by Faith (Eph 2:8)"], ["By grace are ye saved."])
        self.assertEqual(prompt, "")
        self.assertEqual(docs, ["title: Salvation by Faith (Eph 2:8) | text: By grace are ye saved."])
        _, question = format_query(spec, "What did Wesley say about worry?")
        self.assertEqual(question, "task: question answering | query: ")
        _, keyword = format_query(spec, "Christian perfection")
        self.assertEqual(keyword, "task: search result | query: ")

    def test_nomic_uses_search_document_prefix(self) -> None:
        spec = MODELS["nomic-embed-text-v2-moe"]
        docs, prompt = format_documents(spec, ["t"], ["By grace are ye saved."])
        self.assertEqual((docs, prompt), (["By grace are ye saved."], "search_document: "))
        self.assertEqual(format_query(spec, "Christian perfection")[1], "search_query: ")

    def test_granite_has_no_prefix(self) -> None:
        spec = MODELS["granite-english-r2"]
        self.assertEqual(format_documents(spec, ["t"], ["x"]), (["x"], ""))
        self.assertEqual(format_query(spec, "why pray?"), ("why pray?", ""))

    def test_fingerprint_tracks_document_side_only(self) -> None:
        spec = MODELS["granite-english-r2"]
        self.assertNotEqual(spec.fingerprint(), dataclasses.replace(spec, revision="0" * 40).fingerprint())
        self.assertNotEqual(spec.fingerprint(), dataclasses.replace(spec, dtype_gpu="fp16").fingerprint())
        self.assertEqual(spec.fingerprint(), dataclasses.replace(spec, question_prefix="q: ").fingerprint())


class StatsTests(unittest.TestCase):
    def test_ci_brackets_mean(self) -> None:
        ci = bootstrap_ci([0.0, 1.0] * 20)
        self.assertAlmostEqual(ci["mean"], 0.5)
        self.assertLess(ci["ci95"][0], 0.5)
        self.assertGreater(ci["ci95"][1], 0.5)

    def test_paired_counts(self) -> None:
        result = paired_bootstrap([1.0, 1.0, 0.0, 0.5], [0.0, 1.0, 0.0, 1.0])
        self.assertEqual((result["wins"], result["ties"], result["losses"]), (1, 2, 1))
        self.assertAlmostEqual(result["diff"], 0.125)


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
