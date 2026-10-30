"""W1-C alignment: normalization, anchoring, interpolation, both chunk paths."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "align"))

from asr_chunks import asr_chunks  # noqa: E402
from preached.corpus import load_chunk_config, word_tokens  # noqa: E402
from seqalign import EXACT, FUZZY, align_tokens, interpolate  # noqa: E402
from textnorm import asr_tokens, canonical_tokens, int_to_words, ordinal_words  # noqa: E402
from wesley import sentence_spans, span_times  # noqa: E402


def norms(pairs):
    return [tok for tok, _ in pairs]


class TextNormTest(unittest.TestCase):
    def test_numbers_and_years(self):
        self.assertEqual(int_to_words(34), ["thirty", "four"])
        self.assertEqual(int_to_words(1790), ["seventeen", "ninety"])
        self.assertEqual(int_to_words(1703), ["seventeen", "oh", "three"])
        self.assertEqual(ordinal_words(19), ["nineteenth"])
        self.assertEqual(ordinal_words(22), ["twenty", "second"])

    def test_both_sides_meet(self):
        canon = norms(canonical_tokens("He shewed his favour to-day; see Eph. 2:8, the 19th, &c."))
        asr = norms(asr_tokens("He showed his favor today; see Ephesians 2, 8, the nineteenth, et cetera.".split()))
        self.assertEqual(canon, asr)

    def test_canonical_indices_follow_word_tokens(self):
        text = "The Lord’s day, 1790. Rom. viii. 16."
        pairs = canonical_tokens(text)
        tokens = word_tokens(text)
        self.assertEqual(max(i for _, group in pairs for i in group), len(tokens) - 1)
        self.assertIn(("lords", [1, 2]), pairs)  # curly apostrophe: two tokens, one word
        self.assertIn("eight", norms(pairs))  # lowercase numeral in a reference

    def test_book_names_need_a_period(self):
        self.assertIn("job", norms(canonical_tokens("the patience of Job is known")))
        self.assertIn("romans", norms(canonical_tokens("Rom. 8")))


class AlignTest(unittest.TestCase):
    def test_skip_and_insertion(self):
        ref = "a b c d e f g h i j k l m n o p".split()
        hyp = "x y a b c d e f k l m n o p z".split()  # reader skipped g-j, added x y z
        anchors = align_tokens(ref, hyp)
        self.assertEqual(anchors[0], (2, EXACT))
        self.assertNotIn(6, anchors)
        self.assertEqual(anchors[10], (8, EXACT))

    def test_stranded_short_run_dropped(self):
        ref = [f"w{i}" for i in range(40)] + ["of", "the"] + [f"v{i}" for i in range(40)]
        hyp = [f"w{i}" for i in range(40)] + [f"u{i}" for i in range(30)] + ["of", "the"] + [f"u{i}x" for i in range(30)] + [f"v{i}" for i in range(40)]
        anchors = align_tokens(ref, hyp)
        self.assertNotIn(40, anchors)

    def test_fuzzy_pair_in_small_gap(self):
        ref = "a b c d hutcheson e f g h".split()
        hyp = "a b c d hutchinson e f g h".split()
        self.assertEqual(align_tokens(ref, hyp)[4], (4, FUZZY))

    def test_interpolate(self):
        times = [None, (0, 1.0, 2.0), None, None, (0, 5.0, 6.0), None]
        out = interpolate(times, [1, 1, 1, 3, 1, 1], [10.0])
        self.assertEqual(out[0], (0, 1.0, 1.0))
        self.assertEqual(out[2], (0, 2.0, 2.75))
        self.assertEqual(out[3], (0, 2.75, 5.0))
        self.assertEqual(out[5], (0, 6.0, 6.0))

    def test_interpolate_across_parts_stays_in_first(self):
        out = interpolate([(0, 1.0, 2.0), None, (1, 0.5, 1.0)], [1, 1, 1], [4.0, 9.0])
        self.assertEqual(out[1], (0, 2.0, 4.0))

    def test_span_plays_from_majority_part(self):
        words = [[0, 99.0, 99.0, 0]] + [[1, 10.0 + i, 10.5 + i, 1] for i in range(5)]
        self.assertEqual(span_times(words, 0, 6)[:3], (1, 10.0, 14.5))


class OutputTest(unittest.TestCase):
    def test_sentence_spans_cover_text(self):
        text = "\"By grace are ye saved.\"\n\nEph. 2:8.\n\n1. All the blessings. Which God hath given!"
        paragraphs = sentence_spans(text)
        last = paragraphs[-1]["sentences"][-1]
        self.assertEqual(last["word_end"], len(word_tokens(text)))

    def test_asr_chunks_record(self):
        words = []
        t = 0.0
        for i in range(400):
            word = f"word{i}" + ("." if i % 12 == 11 else "")
            words.append([t, t + 0.3, word])
            t += 0.4 if i != 200 else 3.0
        transcript = {
            "meta": {"id": "church-2026-11-01", "title": "Sample", "audio_url": "https://example.org/a.mp3", "reader": "Pastor"},
            "searchable_start": 0.0,
            "searchable_end": 1000.0,
            "segments": [{"start": 0, "end": t, "text": "", "words": words}],
        }
        config = load_chunk_config(ROOT / "corpus" / "chunk_config.json")
        rows = asr_chunks(transcript, config)
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["text_source"], "asr")
            self.assertLess(row["start_s"], row["end_s"])
            self.assertLessEqual(row["word_count"], config["max_words"] + 30)
        self.assertEqual(rows[0]["start_s"], 0.0)
        self.assertEqual(rows[-1]["end_s"], words[-1][1])


if __name__ == "__main__":
    unittest.main()
