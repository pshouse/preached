"""Chunk windows stay inside the spoken-length bounds and overlap."""

from __future__ import annotations

import unittest

from preached.corpus import chunk_text, split_sentences, word_tokens


CONFIG = {
    "target_words": 112,
    "min_words": 75,
    "max_words": 150,
    "overlap": 0.25,
    "wpm": 150,
}


def _paragraph(sentences: int, words_each: int = 20) -> str:
    parts = []
    for index in range(sentences):
        tokens = [f"Word{index}x{n}" for n in range(words_each - 1)]
        parts.append(" ".join(tokens) + ".")
    return " ".join(parts)


class ChunkTests(unittest.TestCase):
    def test_abbreviations_do_not_split(self) -> None:
        text = "Mr. Wesley preached at St. Mary's. Rom. 8:16 is the text."
        sentences = split_sentences(text)
        self.assertEqual(len(sentences), 2)
        self.assertTrue(sentences[0].startswith("Mr. Wesley"))
        self.assertIn("St. Mary's", sentences[0])

    def test_windows_and_overlap(self) -> None:
        text = _paragraph(40, 20)
        chunks = chunk_text(text, CONFIG)
        self.assertGreaterEqual(len(chunks), 4)
        for chunk in chunks[:-1]:
            self.assertGreaterEqual(chunk["word_count"], CONFIG["min_words"])
            self.assertLessEqual(chunk["word_count"], CONFIG["max_words"])
        self.assertLessEqual(chunks[-1]["word_count"], CONFIG["max_words"])
        # 25% overlap means the next chunk starts before the previous ends.
        for previous, nxt in zip(chunks, chunks[1:]):
            self.assertLess(nxt["word_start"], previous["word_end"])
            self.assertGreater(nxt["word_start"], previous["word_start"])

    def test_empty(self) -> None:
        self.assertEqual(chunk_text("   ", CONFIG), [])

    def test_word_tokens_keep_apostrophes(self) -> None:
        self.assertEqual(word_tokens("God's grace"), ["God's", "grace"])


if __name__ == "__main__":
    unittest.main()
