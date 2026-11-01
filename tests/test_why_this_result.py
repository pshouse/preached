"""Each /api/search result says why it is listed (``why``).

``keyword_rank`` and ``meaning_rank`` are 1-based places in the gated BM25
and dense candidate lists the ranker fused; ``similarity`` is the dense
cosine from that list. They are read off the lists the search already ran,
so no extra pass, and a hidden chunk never moves a visible chunk's rank.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.server import RESULT_FIELDS, STATIC_DIR, App, Searcher, hit_dict  # noqa: E402
from preached.search import Hit, Why, api_search  # noqa: E402
from preached.store import open_readonly  # noqa: E402
from test_gate_signals import ORDER_QUERY, ORDER_ROWS, build, encode  # noqa: E402
from test_side import FIXTURE_FP, build_library, classic_rows, make_app  # noqa: E402

WHY_KEYS = {"keyword_rank", "meaning_rank", "similarity", "found_by"}

# Query "grace", vector [1, 0, 0, 0].
# BM25: A (says grace three times) #1, B #2; C and D lack the word.
# Dense: A 1.0 #1, C 0.8 #2, B 0.6 #3, D 0.0 #4.
ROWS = [
    ("why-a", "grace grace grace for all who ask", [1, 0, 0, 0]),
    ("why-b", "grace and peace be with you all today", [0.6, 0.8, 0, 0]),
    ("why-c", "mercy endures for every one of us", [0.8, 0.6, 0, 0]),
    ("why-d", "the river runs down to the sea", [0, 0, 1, 0]),
]


def grace(_query: str) -> np.ndarray:
    return np.array([1, 0, 0, 0], dtype=np.float32)


def why_of(hits) -> dict[str, dict]:
    return {hit.chunk_id: hit.why.as_dict() for hit in hits}


class WhyFieldTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "wesley.sqlite"
        rows = [
            {
                "chunk_id": chunk_id,
                "sermon_id": f"wesley-{index:03d}",
                "sermon_number": index,
                "text": text,
                "word_start": 0,
                "word_end": 8,
            }
            for index, (chunk_id, text, _) in enumerate(ROWS, start=1)
        ]
        build_library(path, rows, [vector for _, _, vector in ROWS])
        self.connection = open_readonly(path, check_same_thread=False)
        self.addCleanup(self.connection.close)
        self.searcher = Searcher(self.connection, model="fixture", fingerprint=FIXTURE_FP)

    def app(self, encode=grace) -> App:
        return App(
            connection=self.connection,
            searcher=self.searcher,
            encode=encode,
            fallback_note=None,
            model_name="fixture" if encode else None,
            hosts={"127.0.0.1"},
            static_dir=STATIC_DIR,
            library="wesley",
            floor=0.5,
        )

    def test_hybrid_both_and_meaning_only(self) -> None:
        hits = api_search(self.searcher, "grace", grace("grace"), "hybrid", 10)
        self.assertEqual(why_of(hits), {
            "why-a": {"keyword_rank": 1, "meaning_rank": 1, "similarity": 1.0, "found_by": "both"},
            "why-b": {"keyword_rank": 2, "meaning_rank": 3, "similarity": 0.6, "found_by": "both"},
            "why-c": {"keyword_rank": None, "meaning_rank": 2, "similarity": 0.8, "found_by": "meaning"},
            "why-d": {"keyword_rank": None, "meaning_rank": 4, "similarity": 0.0, "found_by": "meaning"},
        })
        # score is unchanged: the RRF sum of the same ranks.
        scores = {hit.chunk_id: hit.score for hit in hits}
        self.assertAlmostEqual(scores["why-a"], 1 / 61 + 1 / 61)
        self.assertAlmostEqual(scores["why-b"], 1 / 62 + 1 / 63)
        self.assertAlmostEqual(scores["why-c"], 1 / 62)

    def test_hybrid_keyword_only(self) -> None:
        # Two dense candidates (A, C): B is in the BM25 list only.
        hits = self.searcher.hybrid("grace", grace("grace"), 10, candidates=2)
        self.assertEqual(why_of(hits)["why-b"], {
            "keyword_rank": 2, "meaning_rank": None, "similarity": None, "found_by": "keyword",
        })
        self.assertEqual(why_of(hits)["why-a"]["found_by"], "both")

    def test_bm25_mode_has_no_meaning_fields(self) -> None:
        hits = api_search(self.searcher, "grace", None, "bm25", 10)
        self.assertEqual(why_of(hits), {
            "why-a": {"keyword_rank": 1, "meaning_rank": None, "similarity": None, "found_by": "keyword"},
            "why-b": {"keyword_rank": 2, "meaning_rank": None, "similarity": None, "found_by": "keyword"},
        })

    def test_dense_mode_has_no_keyword_fields(self) -> None:
        hits = api_search(self.searcher, "grace", grace("grace"), "dense", 10)
        self.assertEqual([hit.chunk_id for hit in hits], ["why-a", "why-c", "why-b", "why-d"])
        for rank, hit in enumerate(hits, start=1):
            why = hit.why.as_dict()
            self.assertEqual((why["keyword_rank"], why["meaning_rank"], why["found_by"]), (None, rank, "meaning"))
        self.assertEqual([hit.why.similarity for hit in hits], [1.0, 0.8, 0.6, 0.0])

    def test_similarity_is_the_cosine_rounded_to_three_places(self) -> None:
        vector = np.array([0.6, 0.8, 0, 0], dtype=np.float32) * np.float32(0.99991)
        hits = api_search(self.searcher, "grace", vector, "dense", 10)
        cosines = {chunk_id: float(np.dot(np.array(v, dtype=np.float32), vector)) for chunk_id, _, v in ROWS}
        for hit in hits:
            self.assertEqual(hit.why.similarity, round(cosines[hit.chunk_id], 3))
            self.assertIsInstance(hit.why.similarity, float)

    def test_hit_equality_ignores_why(self) -> None:
        hit = api_search(self.searcher, "grace", None, "bm25", 1)[0]
        from dataclasses import replace

        self.assertEqual(replace(hit, why=None), hit)

    def test_json_shape(self) -> None:
        self.assertIn("why", RESULT_FIELDS)
        self.assertEqual(RESULT_FIELDS[-2:], ("score", "why"))
        for mode in ("hybrid", "bm25", "dense"):
            payload = self.app().search("grace", 10, mode)
            with self.subTest(mode=mode):
                self.assertTrue(payload["results"])
                for result in payload["results"]:
                    self.assertEqual(list(result)[: len(RESULT_FIELDS)], list(RESULT_FIELDS))
                    why = result["why"]
                    self.assertEqual(set(why), WHY_KEYS)
                    for key in ("keyword_rank", "meaning_rank"):
                        self.assertTrue(why[key] is None or (type(why[key]) is int and why[key] >= 1), why)
                    self.assertTrue(why["similarity"] is None or type(why["similarity"]) is float)
                    self.assertIn(why["found_by"], ("both", "keyword", "meaning"))
                    self.assertIsInstance(result["score"], float)
                    if mode == "bm25":
                        self.assertEqual((why["meaning_rank"], why["similarity"], why["found_by"]),
                                         (None, None, "keyword"))
                    if mode == "dense":
                        self.assertEqual((why["keyword_rank"], why["found_by"]), (None, "meaning"))

    def test_keyword_only_server_says_keyword(self) -> None:
        # No query encoder: the server falls back to bm25, so no meaning fields.
        payload = self.app(encode=None).search("grace", 10, "hybrid")
        self.assertEqual(payload["mode"], "bm25")
        self.assertEqual([r["why"]["found_by"] for r in payload["results"]], ["keyword", "keyword"])

    def test_a_hit_without_why_is_explicit_null(self) -> None:
        hit = Hit(rowid=1, score=0.5, chunk_id="x", sermon_id="wesley-001", sermon_title="T", text="t",
                  start_s=None, end_s=None, source_url=None, scripture=None)
        self.assertIsNone(hit_dict(hit)["why"])
        hit.why = Why(3, None, None)
        self.assertEqual(hit_dict(hit)["why"],
                         {"keyword_rank": 3, "meaning_rank": None, "similarity": None, "found_by": "keyword"})

    def test_no_extra_search_passes(self) -> None:
        # Before why: api_search runs each list once and compute_signals once more.
        counts = {"lexical": 0, "semantic": 0}
        lexical, semantic = Searcher._lexical, Searcher._semantic

        def count_lexical(searcher, *args):
            counts["lexical"] += 1
            return lexical(searcher, *args)

        def count_semantic(searcher, *args):
            counts["semantic"] += 1
            return semantic(searcher, *args)

        with patch.object(Searcher, "_lexical", count_lexical), patch.object(Searcher, "_semantic", count_semantic):
            self.app().search("grace", 10, "hybrid")
        self.assertEqual(counts, {"lexical": 2, "semantic": 2})


class WhyIgnoresHiddenChunksTests(unittest.TestCase):
    """PRIVACY: ranks and similarity come only from rows the publish gate shows."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def apps(self, extra=()) -> dict[bool, App]:
        apps = {}
        for hidden in (False, True):
            path = self.tmp / f"church-{hidden}-{len(extra)}.sqlite"
            build(path, hidden=hidden, extra=list(extra))
            connection = open_readonly(path, check_same_thread=False)
            self.addCleanup(connection.close)
            apps[hidden] = App(
                connection=connection,
                searcher=Searcher(connection, model="fixture", fingerprint=FIXTURE_FP),
                encode=encode,
                fallback_note=None,
                model_name="fixture",
                hosts={"127.0.0.1"},
                static_dir=STATIC_DIR,
                library="church",
                floor=0.5,
            )
        return apps

    def whys(self, app: App, query: str, mode: str) -> list[tuple[str, dict]]:
        return [(r["chunk_id"], r["why"]) for r in app.search(query, 10, mode)["results"]]

    def test_hidden_chunk_that_would_rank_first_does_not_shift_meaning_ranks(self) -> None:
        apps = self.apps()
        # Ungated, the hidden chunk (vector [0, 1, 0, 0]) is the top dense hit for "righteousness".
        raw = Searcher(apps[True].connection, model="fixture", fingerprint=FIXTURE_FP)
        raw._where = lambda: None
        self.assertEqual(raw.dense(encode("righteousness"), 10)[0].sermon_id, "hidden0001")
        for mode in ("dense", "hybrid"):
            with self.subTest(mode=mode):
                gated = self.whys(apps[True], "righteousness", mode)
                self.assertEqual(gated, self.whys(apps[False], "righteousness", mode))
                self.assertEqual(gated[0][1]["meaning_rank"], 1)
                self.assertNotIn("hidden0001-c0000", [chunk_id for chunk_id, _ in gated])

    def test_hidden_rows_that_would_reorder_bm25_do_not_shift_keyword_ranks(self) -> None:
        # Eight hidden "lantern" sermons would put orderb above ordera if they counted
        # (test_gate_signals.test_hidden_rows_do_not_move_the_bm25_order).
        apps = self.apps(ORDER_ROWS)
        for mode in ("bm25", "hybrid"):
            with self.subTest(mode=mode):
                gated = self.whys(apps[True], ORDER_QUERY, mode)
                self.assertEqual(gated, self.whys(apps[False], ORDER_QUERY, mode))
                ranks = {chunk_id: why["keyword_rank"] for chunk_id, why in gated}
                self.assertEqual((ranks["ordera0001-c0000"], ranks["orderb0001-c0000"]), (1, 2))

    def test_every_query_and_mode_matches_a_file_without_the_hidden_chunk(self) -> None:
        apps = self.apps()
        for query in ("righteousness", "grace", "zzyzxnonsense"):
            for mode in ("bm25", "dense", "hybrid"):
                with self.subTest(query=query, mode=mode):
                    self.assertEqual(self.whys(apps[True], query, mode), self.whys(apps[False], query, mode))


class ChurchSideWhyTests(unittest.TestCase):
    def test_church_and_side_results_carry_why(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            classic_path, church_path = Path(tmp) / "wesley.sqlite", Path(tmp) / "church.sqlite"
            build_library(classic_path, *classic_rows())
            build(church_path, hidden=True)  # two approved sermons and one hidden
            app = make_app(classic_path, church_path)
            try:
                side = app.side("grace", 10, "hybrid")
                church = app.search("grace", 10, "hybrid", library="sample")
            finally:
                app.connection.close()
                app.church_connection.close()
        self.assertTrue(side["church"]["present"])
        self.assertEqual(side["church"]["results"], church["results"])
        for column in (side["classic"], church):
            self.assertTrue(column["results"])
            for result in column["results"]:
                self.assertEqual(set(result["why"]), WHY_KEYS)
        # Church: "grace upon grace" is #1 by both lists; the hidden sermon is ranked nowhere.
        self.assertEqual([(r["chunk_id"], r["why"]) for r in church["results"]], [
            ("visible001-c0000", {"keyword_rank": 1, "meaning_rank": 1, "similarity": 1.0, "found_by": "both"}),
            ("visible002-c0000", {"keyword_rank": 2, "meaning_rank": 2, "similarity": 0.9, "found_by": "both"}),
        ])

if __name__ == "__main__":
    unittest.main()
