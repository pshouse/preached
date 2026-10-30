"""Name redaction: the W2-YT hook interface, the rules, config, and the eval bar.

All names here are invented or public. No network, no model.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval" / "privacy"))

from preached import privacy  # noqa: E402
from preached.privacy import Config, decide, load_config, redact, redact_text  # noqa: E402


@dataclass(frozen=True)
class Word:
    """Same shape as preached.youtube.words.Word on feat/w2-youtube."""

    start: float
    end: float
    text: str


def words(text: str, step: float = 0.4) -> list[Word]:
    return [Word(i * step, i * step + 0.3, token) for i, token in enumerate(text.split())]


def masked(text: str, config: Config | None = None) -> str:
    return redact_text(text, config or Config())


class HookInterfaceTests(unittest.TestCase):
    def test_word_dataclass_keeps_type_order_and_times(self) -> None:
        source = words("Please pray for Sister Jane, she is in the hospital.")
        out = redact(source, config=Config())
        self.assertEqual(len(out), len(source))
        self.assertTrue(all(isinstance(w, Word) for w in out))
        self.assertEqual([(w.start, w.end) for w in out], [(w.start, w.end) for w in source])
        self.assertEqual(" ".join(w.text for w in out), "Please pray for Sister [name], she is in the hospital.")

    def test_nothing_to_redact_returns_the_same_list(self) -> None:
        source = words("The apostle Paul wrote to Timothy from Rome.")
        self.assertIs(redact(source, config=Config()), source)

    def test_w1c_tuples_lists_and_dicts(self) -> None:
        tuples = [(0.0, 0.2, "Pray"), (0.2, 0.4, "for"), (0.4, 0.8, "Brenda.")]
        self.assertEqual(redact(tuples, config=Config())[2], (0.4, 0.8, "[name]."))
        lists_ = [[0.0, 0.2, "Pray"], [0.2, 0.4, "for"], [0.4, 0.8, "Brenda."]]
        self.assertEqual(redact(lists_, config=Config())[2], [0.4, 0.8, "[name]."])
        dicts = [{"start": 0.0, "end": 0.2, "word": "Thanks"}, {"start": 0.2, "end": 0.4, "word": "to"},
                 {"start": 0.4, "end": 0.8, "word": "Gary", "probability": 0.9}]
        self.assertEqual(redact(dicts, config=Config())[2], {"start": 0.4, "end": 0.8, "word": "[name]", "probability": 0.9})

    def test_input_is_not_mutated(self) -> None:
        source = [{"start": 0.0, "end": 0.2, "text": "Pray"}, {"start": 0.2, "end": 0.4, "text": "for"},
                  {"start": 0.4, "end": 0.8, "text": "Brenda"}]
        redact(source, config=Config())
        self.assertEqual(source[2]["text"], "Brenda")

    def test_punctuation_and_possessive_survive(self) -> None:
        self.assertEqual(masked("Thank you, Brenda! It was Dwayne's idea."), "Thank you, [name]! It was [name]'s idea.")
        self.assertEqual(masked('He said "Kevin, come here."'), 'He said "[name], come here."')

    def test_empty_input(self) -> None:
        self.assertEqual(redact([], config=Config()), [])


class RuleTests(unittest.TestCase):
    def assertMasked(self, text: str, expected: str) -> None:
        self.assertEqual(masked(text), expected)

    def assertKept(self, text: str) -> None:
        self.assertEqual(masked(text), text)

    def test_prayer_requests(self) -> None:
        self.assertMasked("Pray for Tom and Debbie Reynolds.", "Pray for [name] and [name] [name].")
        self.assertMasked("Brother Earl fell and broke his hip.", "Brother [name] fell and broke his hip.")
        self.assertMasked("Mr. and Mrs. Whitfield are sick.", "Mr. and Mrs. [name] are sick.")
        self.assertMasked("be praying for the Hendersons tonight", "be praying for the [name] tonight")

    def test_bible_names_shared_with_congregants(self) -> None:
        self.assertMasked("Please remember John in the hospital.", "Please remember [name] in the hospital.")
        self.assertMasked("Our son David was born early.", "Our son [name] was born early.")
        self.assertMasked("We're baptizing Peter and Linda next Sunday.", "We're baptizing [name] and [name] next Sunday.")
        self.assertKept("John the Baptist said, He must increase.")
        self.assertKept("Peter and his brother Andrew were casting a net into the sea.")
        self.assertKept("Turn with me to John chapter three.")
        self.assertKept("Pray for Israel and Jerusalem.")

    def test_historical_and_public_names(self) -> None:
        self.assertKept("John Wesley felt his heart strangely warmed.")
        self.assertKept("C. S. Lewis said pain is God's megaphone.")
        self.assertKept("Charles Wesley wrote the hymns, John preached and Charles wrote the songs.")
        self.assertKept("George Müller prayed and the milk truck broke down.")
        self.assertKept("Thomas à Kempis wrote The Imitation of Christ.")
        self.assertKept("Spurgeon struggled with depression.")
        self.assertMasked("Charles Wesley Hendricks joined the choir.", "[name] [name] [name] joined the choir.")

    def test_words_that_are_also_names(self) -> None:
        self.assertKept("Grace is not something you earn.")
        self.assertKept("Mark my words, the Lord will provide.")
        self.assertKept("Will you trust him?")
        self.assertKept("Faith comes by hearing.")
        self.assertMasked("Crystal was addicted for twelve years.", "[name] was addicted for twelve years.")
        self.assertMasked("Sister Faith asked for prayer.", "Sister [name] asked for prayer.")
        self.assertMasked("pray for Grace as she recovers", "pray for [name] as she recovers")

    def test_unknown_surnames_and_places(self) -> None:
        self.assertMasked("Lift up Nguyen and his family.", "Lift up [name] and his family.")
        self.assertKept("Bonhoeffer was hanged at Flossenburg.")
        self.assertKept("They are deploying out of Fort Liberty next month.")

    def test_lowercase_after_a_cue(self) -> None:
        self.assertMasked("pray for brenda and her boy tyler", "pray for [name] and her boy [name]")
        self.assertKept("pray for peace and for wisdom")

    def test_decide_matches_words(self) -> None:
        self.assertEqual(decide(["Pray", "for", "Ashley."]), [False, False, True])


class ConfigTests(unittest.TestCase):
    def test_allow_block_token(self) -> None:
        config = Config.from_dict({"allow": ["Pastor Mike", "Mike Ellis"], "block": ["Moses"], "token": "[redacted]"})
        self.assertEqual(masked("Pastor Mike will preach.", config), "Pastor Mike will preach.")
        self.assertEqual(masked("Mike Ellis will preach.", config), "Mike Ellis will preach.")
        self.assertEqual(masked("Moses Tate is in the choir.", config), "[redacted] [redacted] is in the choir.")
        self.assertEqual(masked("Pastor Steve will preach.", config), "Pastor [redacted] will preach.")

    def test_drop_windows(self) -> None:
        config = Config.from_dict({"drop": [{"start": 0.0, "end": 1.0}, {"source": "abc", "start": 2.0, "end": 3.0}]})
        source = words("one two three four five six seven eight", step=0.5)
        other = redact(source, config=config, source="xyz")
        self.assertEqual([w.text for w in other], ["three", "four", "five", "six", "seven", "eight"])
        mine = redact(source, config=config, source="abc")
        self.assertEqual([w.text for w in mine], ["three", "four", "seven", "eight"])
        self.assertEqual([(w.start, w.end) for w in mine], [(1.0, 1.3), (1.5, 1.8), (3.0, 3.3), (3.5, 3.8)])

    def test_toml_and_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "privacy.toml"
            path.write_text('allow = ["Pastor Mike"]\nblock = ["Moses"]\n[[drop]]\nstart = 0\nend = 0.5\n')
            config = load_config(path)
            self.assertIn(("pastor", "mike"), config.allow)
            with mock.patch.dict(os.environ, {privacy.CONFIG_ENV: str(path)}):
                out = redact(words("Hello Pastor Mike and Moses"))
            self.assertEqual([w.text for w in out], ["Pastor", "Mike", "and", "[name]"])

    def test_example_file_loads(self) -> None:
        config = load_config(ROOT / "privacy.example.toml")
        self.assertTrue(config.allow)

    def test_bad_settings(self) -> None:
        with self.assertRaises(ValueError):
            Config.from_dict({"alow": ["typo"]})
        with self.assertRaises(ValueError):
            Config.from_dict({"drop": [{"start": 5, "end": 1}]})


class EvalBarTests(unittest.TestCase):
    """Regression guard on the sets the rules were tuned on (see reports/W3-PRIV.md)."""

    def test_tuning_sets_meet_the_bar(self) -> None:
        import evaluate

        for name in ("dev.jsonl", "blind1.jsonl"):
            result = evaluate.score(ROOT / "eval" / "privacy" / name, Config(), show=False)
            self.assertGreaterEqual(result["recall"], 0.95, name)
            self.assertLessEqual(result["false_redaction_rate"], 0.02, name)

    def test_cheap_on_cpu(self) -> None:
        privacy.lists()
        text = ("Please pray for Sister Jane and the apostle Paul wrote to Timothy about John Wesley. " * 100).split()
        started = time.perf_counter()
        decide(text)
        self.assertLess(time.perf_counter() - started, 2.0)


if __name__ == "__main__":
    unittest.main()
