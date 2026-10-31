"""The retrieval eval's "plain" group must not leak its sermon titles."""

from __future__ import annotations

import csv
import importlib.util
import json
import re
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_title_leak as lint  # noqa: E402
from preached import paths  # noqa: E402

# By path, so eval/ (pool.py, timestamps.py) never goes on sys.path.
_spec = importlib.util.spec_from_file_location("eval_validate", ROOT / "eval" / "validate.py")
validate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validate)

GROUPS = {"plain", "plain-blind", "names-topic", "title-keyword", "scripture-keyword", "unanswerable"}


def load() -> list[dict]:
    return [json.loads(line) for line in (ROOT / "eval" / "questions.jsonl").read_text().splitlines() if line.strip()]


def load_verdicts() -> dict[str, str]:
    with (ROOT / "reports" / "W3-LABEL-VERDICTS.csv").open(newline="", encoding="utf-8") as handle:
        return {row["row id"]: row["verdict"] for row in csv.DictReader(handle)}


def load_partials() -> list[dict]:
    return [json.loads(line) for line in (ROOT / "eval" / "partial_verdicts.jsonl").read_text().splitlines() if line.strip()]


def load_chunk_texts() -> list[dict] | None:
    """Chunk id + text from chunks.jsonl, else from the index sqlite opened read-only; None if neither exists."""
    if validate.CHUNKS_JSONL.is_file():
        return validate.read_jsonl(validate.CHUNKS_JSONL)
    index = paths.INDEX_PATH
    if not index.is_file():
        return None
    # immutable=1 never touches -wal/-shm or the file itself; the private index is not written or copied.
    conn = sqlite3.connect(f"file:{index}?mode=ro&immutable=1", uri=True)
    try:
        return [{"chunk_id": cid, "text": text}
                for cid, text in conn.execute("SELECT chunk_id, text FROM chunks ORDER BY rowid")]
    finally:
        conn.close()


def load_sheet_chunks() -> dict[str, str]:
    """Sheet row id -> real chunk id, from the KEY table."""
    rows = {}
    for line in (ROOT / "reports" / "W3-LABEL-SHEET-KEY.md").read_text().splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) > 6 and cells[0].startswith("L") and cells[0][1:].isdigit():
            rows[cells[0]] = cells[6]
    return rows


def load_key_segments() -> dict[str, list[str]]:
    """Sheet row id -> the quoted KEY segments (split at ` ... `) for that row."""
    rows = {}
    for line in (ROOT / "reports" / "W3-LABEL-SHEET-KEY.md").read_text().splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) > 8 and cells[0].startswith("L") and cells[0][1:].isdigit():
            rows[cells[0]] = [s for q in re.findall(r'"([^"]+)"', cells[8]) for s in q.split(" ... ")]
    return rows


def confirmed_labels() -> list[dict]:
    """Every confirmed label: primary ones in questions.jsonl and the sensitivity-only partial file."""
    return ([p for q in load() for p in q["relevant"] if p.get("status") == "confirmed"]
            + [line["label"] for line in load_partials()])


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

    def check_label(self, p: dict, verdicts: dict[str, str], primary: bool = True) -> None:
        if p.get("status") == "proposed":
            self.assertTrue(p.get("reason"), p["passage_id"])
            self.assertEqual(p.get("found_by"), "llm-proposed:claude", p["passage_id"])
        elif p.get("status") == "confirmed":
            # Patrick's blind verdict: the sheet row must exist and carry this grade.
            self.assertEqual(p.get("found_by"), "human:patrick-blind-w3", p["passage_id"])
            self.assertIn(p.get("sheet_row"), verdicts, p["passage_id"])
            self.assertEqual(verdicts[p["sheet_row"]], str(p["grade"]), p["passage_id"])
            self.assertIn(p.get("quote_source"), ("key-segment", "chunk-unique"), p["passage_id"])
            if primary:
                # Ruling (a): only verdict 2 becomes a scored label; verdict 1 lives in eval/partial_verdicts.jsonl.
                self.assertEqual(p["grade"], 2, p["passage_id"])
                self.assertEqual(verdicts[p["sheet_row"]], "2", p["passage_id"])
        else:
            self.assertNotIn("found_by", p, p["passage_id"])
        # Existing labels carry no status; grading adds "proposed", blind verdicts "confirmed".
        self.assertIn(p.get("status"), (None, "proposed", "confirmed"), p["passage_id"])

    def test_proposed_labels_are_marked_and_explained(self):
        verdicts = load_verdicts()
        for q in load():
            for p in q["relevant"]:
                self.check_label(p, verdicts)
            if q["group"] == "plain-blind":
                self.assertEqual(q.get("provenance"), "llm-written:grok", q["id"])
                self.assertTrue(all(p.get("status") in ("proposed", "confirmed") for p in q["relevant"]), q["id"])
        candidates = [json.loads(line) for line in (ROOT / "eval" / "plain_candidates.jsonl").read_text().splitlines() if line.strip()]
        self.assertEqual(len(candidates), 30)
        for cand in candidates:
            self.assertEqual(cand.get("provenance"), "llm-written:grok", cand["id"])

    def test_confirmed_label_needs_a_valid_sheet_row(self):
        verdicts = load_verdicts()
        good = {"passage_id": "x", "grade": 2, "status": "confirmed", "found_by": "human:patrick-blind-w3", "sheet_row": "L02",
                "quote_source": "key-segment"}
        self.check_label(good, verdicts)
        self.check_label({**good, "quote_source": "chunk-unique"}, verdicts)
        partial = {**good, "grade": 1, "sheet_row": "L06"}
        self.check_label(partial, verdicts, primary=False)
        for bad in ({"sheet_row": None}, {"sheet_row": "L99"}, {"sheet_row": "L01"}, {"found_by": "human:someone"},
                    {"found_by": "human:patrick-blind-w3\n"}, {"quote_source": None}, {"quote_source": "picked"},
                    {"grade": 1, "sheet_row": "L06"}, {"grade": 1}, {"sheet_row": "L06"}):
            with self.subTest(bad=bad), self.assertRaises(AssertionError):
                self.check_label({**good, **bad}, verdicts)
        with self.assertRaises(AssertionError):
            self.check_label({k: v for k, v in good.items() if k != "sheet_row"}, verdicts)

    def test_partial_verdicts_are_verdict_1_labels_with_exact_mirrors(self):
        verdicts = load_verdicts()
        by_id = {q["id"]: q for q in load()}
        lines = load_partials()
        self.assertTrue(lines)
        sources = {}
        seen = set()
        for line in lines:
            label, where = line["label"], f'{line["question_id"]} {line["sheet_row"]}'
            self.assertIn(line["question_id"], by_id, where)
            self.assertEqual(line["verdict"], 1, where)
            self.assertEqual(verdicts.get(line["sheet_row"]), "1", where)
            self.assertEqual(label.get("grade"), 1, where)
            self.assertEqual(label.get("sheet_row"), line["sheet_row"], where)
            self.assertEqual(label.get("status"), "confirmed", where)
            self.check_label(label, verdicts, primary=False)
            self.assertNotIn((line["question_id"], line["sheet_row"]), seen, f"duplicate line: {where}")
            seen.add((line["question_id"], line["sheet_row"]))
            if "mirrored_from" not in line:
                sources[(line["question_id"], line["sheet_row"])] = line
        for line in lines:
            if "mirrored_from" in line:
                where = f'{line["question_id"]} {line["sheet_row"]}'
                source = sources.get((line["mirrored_from"], line["sheet_row"]))
                if source is None:
                    self.fail(f"mirror has no source line: {where}")
                self.assertEqual(line["label"], source["label"], where)
                # The mirror goes on the original of that -plain rewrite.
                self.assertEqual(by_id[line["mirrored_from"]].get("rewrite_of"), line["question_id"], where)
        # And the other way: every non-mirror line on a -plain rewrite has exactly one mirror on its original.
        for (qid, row), line in sources.items():
            original = by_id[qid].get("rewrite_of")
            if original:
                mirrors = [m for m in lines if m["question_id"] == original and m.get("mirrored_from") == qid
                           and m["sheet_row"] == row]
                self.assertEqual(len(mirrors), 1, f"{qid} {row}: needs exactly one mirror on {original}")

    def test_key_segment_quotes_are_key_segments_of_their_row(self):
        segments = load_key_segments()
        self.assertEqual(len(segments), 24)
        for p in confirmed_labels():
            if p["quote_source"] == "key-segment":
                self.assertIn(p["quote"], segments[p["sheet_row"]], f'{p["passage_id"]} {p["sheet_row"]}')

    def test_confirmed_quotes_resolve_to_exactly_their_sheet_chunk(self):
        chunks = load_chunk_texts()
        if chunks is None:
            self.skipTest("needs chunks.jsonl or the index sqlite in PREACHED_CACHE")
        sheet = load_sheet_chunks()
        self.assertEqual(len(sheet), 24)
        labels = confirmed_labels()
        self.assertTrue(labels)
        for p in labels:
            with self.subTest(passage=p["passage_id"], sheet_row=p["sheet_row"]):
                hits = [c["chunk_id"] for c in chunks if validate.contains_quote(c["text"], p["quote"])]
                self.assertEqual(hits, [sheet[p["sheet_row"]]])
                self.assertEqual(p["chunk_ids"], hits)
                self.assertIn(p["quote_source"], ("key-segment", "chunk-unique"))

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

    def test_enemy_and_trick_are_synonyms_of_satans_devices(self):
        # (word in the question, synonym it should match)
        for word, syn in (("enemy", "enemy"), ("enemies", "enemy"), ("trick", "trick"), ("tricked", "trick"),
                          ("deceive", "deceive"), ("deception", "deception")):
            q = {"query": f"How does the {word} catch me?", "relevant": [
                {"sermon_id": "wesley-042", "sermon_title": "Satan's Devices", "grade": 2, "quote": "x"}]}
            self.assertTrue(any(h.startswith(f'synonym "{syn}"') for h in lint.leaks(q, {})), word)

    def test_plain_blind_leaks_do_not_fail(self):
        q = {"id": "p-x", "group": "plain-blind", "query": "Is the devil after me?", "relevant": [
            {"sermon_id": "wesley-042", "sermon_title": "Satan's Devices", "grade": 2, "quote": "x"}]}
        self.assertEqual(lint.check([q]), {})
        self.assertIn("p-x", lint.check([q], "plain-blind"))

    def test_modern_verse_wording(self):
        # "anxious about tomorrow" is Matt 6:34, "Take no thought for the morrow".
        q = {"query": "I am anxious about tomorrow.", "relevant": [
            {"passage_id": "w-p1", "sermon_id": "wesley-029", "sermon_title": "Discourse 9", "grade": 2,
             "quote": "Take therefore no thought for the morrow"}]}
        scripture = {"wesley-029": {"scripture": "Matt 6:34",
                                    "text": "Take no thought for the morrow: for the morrow shall take thought for the things of itself."}}
        hits = lint.leaks(q, scripture)
        self.assertIn('quote phrase "anxious tomorrow" (w-p1)', hits)
        self.assertIn('scripture phrase "anxious tomorrow" (wesley-029 Matt 6:34)', hits)

    def test_single_distinctive_word(self):
        q = {"query": "What does sanctification look like in ordinary life?", "relevant": [
            {"passage_id": "s-p1", "sermon_id": "wesley-043", "sermon_title": "The Scripture Way of Salvation",
             "grade": 2, "quote": "works of mercy are in some sense necessary to sanctification"}]}
        hits = lint.leaks(q, {})
        self.assertIn('distinctive word "sanctification" (s-p1) ~ "sanctification"', hits)
        # A short shared word is not, on its own, a leak.
        ordinary = {"query": "Is love enough?", "relevant": [
            {"passage_id": "o", "sermon_id": "x", "sermon_title": "Y", "grade": 2,
             "quote": "the love of a neighbour is a duty here"}]}
        self.assertEqual(lint.leaks(ordinary, {}), [])

    def test_fell_away(self):
        self.assertTrue(lint.same_word("fell", "fall"))
        self.assertTrue(lint.same_word("fallen", "fall"))
        quoted = {"query": "I fell away after I believed.", "relevant": [
            {"passage_id": "fa", "sermon_id": "wesley-086", "sermon_title": "A Call to Backsliders", "grade": 2,
             "quote": "if they fall away there is still hope"}]}
        self.assertIn('quote phrase "fell away" (fa)', lint.leaks(quoted, {}))
        # The backsliders sermon is known by the phrase even when the quote does not say it.
        signed = {"query": "I fell away and I want to come back.", "relevant": [
            {"passage_id": "b", "sermon_id": "wesley-086", "sermon_title": "A Call to Backsliders", "grade": 2,
             "quote": "hope for those backsliders who are still uneasy"}]}
        self.assertIn('signature "fell away" (wesley-086)', lint.leaks(signed, {}))

    def test_stopwords_and_short_words_are_ignored(self):
        q = {"query": "What did he say upon the Mount of God?", "relevant": [
            {"sermon_id": "x", "sermon_title": "Upon our Lord's Sermon on the Mount, Discourse 6"}]}
        self.assertEqual(lint.leaks(q), ['title word "mount" (Upon our Lord\'s Sermon on the Mount, Discourse 6) ~ "mount"'])


if __name__ == "__main__":
    unittest.main()
