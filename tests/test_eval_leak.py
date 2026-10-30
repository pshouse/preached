"""The retrieval eval's "plain" group must not leak its sermon titles."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_title_leak as lint  # noqa: E402

GROUPS = {"plain", "names-topic", "title-keyword", "scripture-keyword", "unanswerable"}


def load() -> list[dict]:
    return [json.loads(line) for line in (ROOT / "eval" / "questions.jsonl").read_text().splitlines() if line.strip()]


class TitleLeakTest(unittest.TestCase):
    def test_plain_questions_do_not_share_title_words(self):
        self.assertEqual(lint.check(load()), {})

    def test_every_question_has_a_known_group(self):
        for q in load():
            self.assertIn(q.get("group"), GROUPS, q["id"])
            self.assertEqual(q["group"] == "unanswerable", q["type"] == "unanswerable", q["id"])

    def test_each_names_topic_question_has_a_plain_rewrite_with_the_same_labels(self):
        by_id = {q["id"]: q for q in load()}
        named = [q for q in by_id.values() if q["group"] == "names-topic"]
        self.assertTrue(named)
        for q in named:
            rewrite = by_id.get(q["id"] + "-plain")
            self.assertIsNotNone(rewrite, q["id"])
            self.assertEqual(rewrite["group"], "plain")
            self.assertEqual(rewrite["rewrite_of"], q["id"])
            self.assertEqual(rewrite["relevant"], q["relevant"])
            # The original is the leaky one, so the lint must catch it.
            self.assertTrue(lint.leaks(q), q["id"])

    def test_stemming_matches_inflections(self):
        self.assertTrue(lint.same_word("justified", "justification"))
        self.assertTrue(lint.same_word("heavy", "heaviness"))
        self.assertTrue(lint.same_word("believe", "believers"))
        self.assertTrue(lint.same_word("perfect", "perfection"))
        self.assertFalse(lint.same_word("saved", "salvation"))
        self.assertTrue(lint.same_word("pray", "prayer"))
        self.assertTrue(lint.same_word("spirit", "spiritually"))  # prefix match, shorter stem >= 5
        self.assertFalse(lint.same_word("mean", "meant"))  # 4-letter stems match only exactly

    def test_stopwords_and_short_words_are_ignored(self):
        q = {"query": "What did he say upon the Mount of God?", "relevant": [
            {"sermon_id": "x", "sermon_title": "Upon our Lord's Sermon on the Mount, Discourse 6"}]}
        self.assertEqual(lint.leaks(q), ['title word "mount" (Upon our Lord\'s Sermon on the Mount, Discourse 6) ~ "mount"'])


if __name__ == "__main__":
    unittest.main()
