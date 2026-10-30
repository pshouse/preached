"""Adjacent chunks from one sermon are not shown twice."""

from __future__ import annotations

import unittest

from preached.search import Hit, boundary_overlap, dedupe_adjacent, merge_overlapping


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


def words(prefix: str, start: int, end: int) -> str:
    """Text of sermon words start..end-1, so overlapping chunks share a boundary."""
    return " ".join(f"{prefix}{i}" for i in range(start, end))


class MergeTests(unittest.TestCase):
    """A neighbour inside the top ``limit`` is merged, not dropped."""

    def test_neighbour_inside_limit_is_merged(self) -> None:
        best = hit(chunk_id="c1", score=3, word_start=100, word_end=200, text=words("w", 100, 200),
                   start_s=50.0, end_s=95.0, audio_url="https://archive.org/a.mp3")
        before = hit(chunk_id="c0", score=2, word_start=20, word_end=125, text=words("w", 20, 125),
                     start_s=10.0, end_s=60.0, audio_url="https://archive.org/a.mp3")
        kept = dedupe_adjacent([best, before], limit=10)
        self.assertEqual(len(kept), 1)
        merged = kept[0]
        self.assertEqual(merged.chunk_id, "c1")
        self.assertEqual(merged.score, 3)
        self.assertEqual(merged.chunk_ids, ["c0", "c1"])
        self.assertEqual(merged.text, words("w", 20, 200))
        self.assertEqual((merged.word_start, merged.word_end), (20, 200))
        # Playback starts at the merged passage's first word.
        self.assertEqual((merged.start_s, merged.end_s), (10.0, 95.0))

    def test_neighbour_after_the_kept_passage(self) -> None:
        best = hit(chunk_id="c0", score=3, word_start=0, word_end=100, text=words("w", 0, 100),
                   start_s=0.0, end_s=40.0)
        after = hit(chunk_id="c1", score=2, word_start=75, word_end=180, text=words("w", 75, 180),
                    start_s=30.0, end_s=70.0)
        merged = dedupe_adjacent([best, after], limit=2)[0]
        self.assertEqual(merged.chunk_ids, ["c0", "c1"])
        self.assertEqual(merged.text, words("w", 0, 180))
        self.assertEqual((merged.start_s, merged.end_s), (0.0, 70.0))

    def test_neighbour_below_limit_is_dropped(self) -> None:
        best = hit(chunk_id="c0", score=3, word_start=0, word_end=100, text=words("w", 0, 100))
        other = hit(chunk_id="x", score=2.5, sermon_id="wesley-002", word_start=0, word_end=100,
                    text=words("x", 0, 100))
        after = hit(chunk_id="c1", score=2, word_start=75, word_end=180, text=words("w", 75, 180))
        later = hit(chunk_id="c9", score=1, word_start=900, word_end=1000, text=words("w", 900, 1000))
        kept = dedupe_adjacent([best, other, after, later], limit=2)
        self.assertEqual([item.chunk_ids for item in kept], [["c0"], ["x"]])
        self.assertEqual(kept[0].text, words("w", 0, 100))

    def test_bridge_folds_two_kept_passages(self) -> None:
        left = hit(chunk_id="a", score=3, word_start=0, word_end=100, text=words("w", 0, 100))
        right = hit(chunk_id="c", score=2, word_start=150, word_end=250, text=words("w", 150, 250))
        bridge = hit(chunk_id="b", score=1, word_start=75, word_end=175, text=words("w", 75, 175))
        kept = dedupe_adjacent([left, right, bridge], limit=10)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].chunk_ids, ["a", "b", "c"])
        self.assertEqual(kept[0].text, words("w", 0, 250))
        self.assertEqual(kept[0].score, 3)

    def test_no_word_is_lost_from_the_plain_top_k(self) -> None:
        pool = [
            hit(chunk_id=f"c{i}", score=10 - i, word_start=i * 75, word_end=i * 75 + 100,
                text=words("w", i * 75, i * 75 + 100))
            for i in (3, 1, 4, 0, 2)
        ]
        plain = sorted(pool, key=lambda item: -item.score)[:3]
        shown = " ".join(item.text for item in dedupe_adjacent(pool, limit=3)).split()
        for item in plain:
            for word in item.text.split():
                self.assertIn(word, shown)
        self.assertEqual(len(shown), len(set(shown)))  # and nothing twice

    def test_merge_stops_at_the_word_cap(self) -> None:
        best = hit(chunk_id="a", score=2, word_start=0, word_end=200, text=words("w", 0, 200))
        neighbour = hit(chunk_id="b", score=1, word_start=150, word_end=350, text=words("w", 150, 350))
        self.assertIsNone(merge_overlapping(best, neighbour, max_words=300))
        kept = dedupe_adjacent([best, neighbour], limit=10)
        self.assertEqual([item.chunk_ids for item in kept], [["a"]])  # dropped, as before merging
        self.assertEqual(len(merge_overlapping(best, neighbour, max_words=350).text.split()), 350)

    def test_no_merge_without_a_shared_boundary(self) -> None:
        best = hit(chunk_id="a", score=2, word_start=0, word_end=100, text="alpha " * 20)
        neighbour = hit(chunk_id="b", score=1, word_start=80, word_end=160, text="beta " * 20)
        self.assertIsNone(merge_overlapping(best, neighbour))
        kept = dedupe_adjacent([best, neighbour], limit=10)
        self.assertEqual([item.chunk_ids for item in kept], [["a"]])

    def test_no_merge_across_audio_files(self) -> None:
        best = hit(chunk_id="a", score=2, word_start=0, word_end=100, text=words("w", 0, 100),
                   audio_url="https://archive.org/one.mp3")
        neighbour = hit(chunk_id="b", score=1, word_start=75, word_end=175, text=words("w", 75, 175),
                        audio_url="https://archive.org/two.mp3")
        self.assertIsNone(merge_overlapping(best, neighbour))

    def test_no_merge_without_word_offsets(self) -> None:
        best = hit(chunk_id="a", score=2, word_start=None, word_end=None, start_s=0, end_s=30)
        neighbour = hit(chunk_id="b", score=1, word_start=None, word_end=None, start_s=20, end_s=50)
        self.assertIsNone(merge_overlapping(best, neighbour))


if __name__ == "__main__":
    unittest.main()
