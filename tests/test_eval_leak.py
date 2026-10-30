"""The retrieval eval's "plain" group must not leak its sermon titles."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_title_leak as lint  # noqa: E402

GROUPS = {"plain", "plain-blind", "names-topic", "title-keyword", "scripture-keyword", "unanswerable"}


def load() -> list[dict]:
    return [json.loads(line) for line in (ROOT / "eval" / "questions.jsonl").read_text().splitlines() if line.strip()]


class TitleLeakTest(unittest.TestCase):
    def test_plain_questions_do_not_share_title_words(self):
        self.assertEqual(lint.check(load()), {})

    def test_every_question_has_a_known_group(self):
        for q in load():
            self.assertIn(q.get("group"), GROUPS, q["id"])
            if q["group"] == "plain-blind":
                # Blind candidates keep their group either way; type follows the grading.
                self.assertEqual(q["type"] == "unanswerable", not q["relevant"] and not q.get("excluded"), q["id"])
            else:
                self.assertEqual(q["group"] == "unanswerable", q["type"] == "unanswerable", q["id"])

    def test_proposed_labels_are_marked_and_explained(self):
        for q in load():
            for p in q["relevant"]:
                if p.get("status") == "proposed":
                    self.assertTrue(p.get("reason"), p["passage_id"])
                # Existing labels carry no status; only grading adds "proposed".
                self.assertIn(p.get("status"), (None, "proposed"), p["passage_id"])
            if q["group"] == "plain-blind":
                self.assertTrue(all(p.get("status") == "proposed" for p in q["relevant"]), q["id"])

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
        self.assertTrue(lint.same_word("denied", "denial"))
        self.assertTrue(lint.same_word("deny", "denial"))
        self.assertTrue(lint.same_word("sinning", "sin"))
        self.assertTrue(lint.same_word("sins", "sin"))

    def test_three_letter_title_words_count(self):
        q = {"query": "Does sin stay in me after I believe?", "relevant": [
            {"sermon_id": "wesley-013", "sermon_title": "On Sin in Believers", "grade": 2, "quote": "x"}]}
        hits = lint.leaks(q, {})
        self.assertIn('title word "sin" (On Sin in Believers) ~ "sin"', hits)
        self.assertIn('title word "believers" (On Sin in Believers) ~ "believe"', hits)

    def test_inflection_and_synonym_of_title(self):
        denial = {"query": "Must I be denied everything I enjoy?", "relevant": [
            {"sermon_id": "wesley-048", "sermon_title": "Self-denial", "grade": 2, "quote": "x"}]}
        self.assertIn('title word "denial" (Self-denial) ~ "denied"', lint.leaks(denial, {}))
        devil = {"query": "Is the devil after me?", "relevant": [
            {"sermon_id": "wesley-042", "sermon_title": "Satan's Devices", "grade": 2, "quote": "x"}]}
        self.assertIn('synonym "devil" (Satan\'s Devices) ~ "devil"', lint.leaks(devil, {}))
        grief = {"query": "How long does grief last?", "relevant": [
            {"sermon_id": "wesley-135", "sermon_title": "On Mourning for the Dead", "grade": 2, "quote": "x"}]}
        self.assertTrue(any(h.startswith('synonym "grief"') for h in lint.leaks(grief, {})))

    def test_quote_and_scripture_phrases_leak(self):
        worry = {"query": "What about taking thought for the future?", "relevant": [
            {"passage_id": "w-p1", "sermon_id": "wesley-029", "sermon_title": "Discourse 9", "grade": 2,
             "quote": "Take therefore no thought for the morrow"}]}
        self.assertIn('quote phrase "taking thought" (w-p1)', lint.leaks(worry, {}))
        child = {"query": "Am I really a child of God?", "relevant": [
            {"passage_id": "a-p1", "sermon_id": "wesley-010", "sermon_title": "Witness", "grade": 2, "quote": "unrelated words here"}]}
        scripture = {"wesley-010": {"scripture": "Rom 8:16",
                                    "text": "The Spirit itself beareth witness with our spirit, that we are the children of God."}}
        self.assertIn('scripture phrase "child god" (wesley-010 Rom 8:16)', lint.leaks(child, scripture))
        # Grade-1 quotes and pairs of generic words do not count.
        loose = {"query": "Does the Lord Jesus love me?", "relevant": [
            {"passage_id": "l-p1", "sermon_id": "x", "sermon_title": "Y", "grade": 2, "quote": "the Lord Jesus Christ"},
            {"passage_id": "l-p2", "sermon_id": "x", "sermon_title": "Y", "grade": 1, "quote": "Jesus love me"}]}
        self.assertEqual(lint.leaks(loose, {}), [])

    def test_proposed_grade1_titles_are_not_checked(self):
        q = {"query": "Will God take me back?", "relevant": [
            {"sermon_id": "wesley-086", "sermon_title": "A Call to Backsliders", "grade": 2, "quote": "x"},
            {"sermon_id": "wesley-019", "sermon_title": "Born of God", "grade": 1, "quote": "y", "status": "proposed"}]}
        self.assertEqual(lint.leaks(q, {}), [])

    def test_plain_blind_leaks_do_not_fail(self):
        q = {"id": "p-x", "group": "plain-blind", "query": "Is the devil after me?", "relevant": [
            {"sermon_id": "wesley-042", "sermon_title": "Satan's Devices", "grade": 2, "quote": "x"}]}
        self.assertEqual(lint.check([q]), {})
        self.assertIn("p-x", lint.check([q], "plain-blind"))

    def test_stopwords_and_short_words_are_ignored(self):
        q = {"query": "What did he say upon the Mount of God?", "relevant": [
            {"sermon_id": "x", "sermon_title": "Upon our Lord's Sermon on the Mount, Discourse 6"}]}
        self.assertEqual(lint.leaks(q), ['title word "mount" (Upon our Lord\'s Sermon on the Mount, Discourse 6) ~ "mount"'])


if __name__ == "__main__":
    unittest.main()
