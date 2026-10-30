"""Adjacent chunks from one sermon are not shown twice."""

from __future__ import annotations

import unittest

from preached.search import Hit, boundary_overlap, dedupe_adjacent


def hit(**kwargs) -> Hit:
    base = dict(
        rowid=1,
        score=1.0,
        chunk_id="wesley-001-c0000",
        sermon_id="wesley-001",
        sermon_title="Salvation by Faith",
        text="grace " * 30,
        start_s=None,
        end_s=None,
        source_url="https://ccel.org/example",
        scripture="Eph 2:8",
        sermon_number=1,
        audio_url=None,
        reader=None,
        text_source=None,
        word_start=0,
        word_end=40,
    )
    base.update(kwargs)
    return Hit(**base)


class DedupeTests(unittest.TestCase):
    def test_word_overlap_drops_the_lower_score(self) -> None:
        best = hit(chunk_id="keep", score=3, word_start=0, word_end=100, text="alpha " * 20)
        neighbor = hit(chunk_id="drop", score=2, word_start=80, word_end=160, text="beta " * 20)
        later = hit(chunk_id="later", score=1, word_start=400, word_end=480, text="gamma " * 20)
        other = hit(
            chunk_id="other",
            score=2.5,
            sermon_id="wesley-002",
            sermon_number=2,
            word_start=0,
            word_end=80,
            text="delta " * 20,
        )
        # Neighbor is listed before the winner so order alone cannot save it.
        kept = dedupe_adjacent([neighbor, other, best, later], limit=10)
        ids = [item.chunk_id for item in kept]
        self.assertEqual(ids, ["keep", "other", "later"])

    def test_touching_word_ranges_both_stay(self) -> None:
        first = hit(chunk_id="a", score=2, word_start=0, word_end=100)
        second = hit(chunk_id="b", score=1, word_start=100, word_end=180)
        ids = [item.chunk_id for item in dedupe_adjacent([first, second], limit=10)]
        self.assertEqual(ids, ["a", "b"])

    def test_timestamp_overlap_when_word_offsets_are_missing(self) -> None:
        first = hit(chunk_id="a", score=2, word_start=None, word_end=None, start_s=0, end_s=30)
        second = hit(chunk_id="b", score=1, word_start=None, word_end=None, start_s=20, end_s=50)
        ids = [item.chunk_id for item in dedupe_adjacent([first, second], limit=10)]
        self.assertEqual(ids, ["a"])

    def test_short_timestamp_touch_stays(self) -> None:
        first = hit(chunk_id="a", score=2, word_start=None, word_end=None, start_s=0, end_s=10)
        second = hit(chunk_id="b", score=1, word_start=None, word_end=None, start_s=9.8, end_s=20)
        ids = [item.chunk_id for item in dedupe_adjacent([first, second], limit=10)]
        self.assertEqual(ids, ["a", "b"])

    def test_text_boundary_when_spans_are_missing(self) -> None:
        shared = " ".join(f"shared{i}" for i in range(12))
        first = hit(
            chunk_id="a",
            score=2,
            word_start=None,
            word_end=None,
            text="opening words of the passage " + shared,
        )
        second = hit(
            chunk_id="b",
            score=1,
            word_start=None,
            word_end=None,
            text=shared + " and the next sentence continues",
        )
        self.assertTrue(boundary_overlap(first.text, second.text))
        ids = [item.chunk_id for item in dedupe_adjacent([first, second], limit=10)]
        self.assertEqual(ids, ["a"])

    def test_repeated_sentence_in_the_middle_is_kept(self) -> None:
        phrase = "one two three four five six seven eight nine ten"
        first = hit(
            chunk_id="a",
            score=2,
            word_start=None,
            word_end=None,
            text=phrase + " and then more words follow here today",
        )
        second = hit(
            chunk_id="b",
            score=1,
            word_start=None,
            word_end=None,
            text="completely different opening phrase before " + phrase + " appears later",
        )
        self.assertFalse(boundary_overlap(first.text, second.text))
        ids = [item.chunk_id for item in dedupe_adjacent([first, second], limit=10)]
        self.assertEqual(ids, ["a", "b"])

    def test_limit_fills_from_survivors(self) -> None:
        hits = [
            hit(chunk_id="a", score=5, word_start=0, word_end=10),
            hit(chunk_id="b", score=4, word_start=5, word_end=15),
            hit(chunk_id="c", score=3, word_start=40, word_end=50),
        ]
        ids = [item.chunk_id for item in dedupe_adjacent(hits, limit=1)]
        self.assertEqual(ids, ["a"])


if __name__ == "__main__":
    unittest.main()
