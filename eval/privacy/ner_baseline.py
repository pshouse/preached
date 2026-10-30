"""Baseline: spaCy PERSON entities instead of the rules. Not shipped.

Measures whether an off-the-shelf NER model would beat ``preached.privacy``
on the same sets. spaCy (Explosion AI, Berlin) is not a project dependency;
install it in a throwaway venv under /cache:

    uv venv --python 3.12 /cache/venvs/w3-priv-ner
    VIRTUAL_ENV=/cache/venvs/w3-priv-ner uv pip install "spacy==3.8.*" \\
      "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
    /cache/venvs/w3-priv-ner/bin/python eval/privacy/ner_baseline.py en_core_web_sm eval/privacy/*.jsonl

Three modes per model: ``ner`` redacts every PERSON word; ``ner+lists`` keeps
a PERSON entity when every word is on the Bible or public-name lists the
rules use, or the entity is a listed public phrase; ``rules|ner`` redacts a
word when either the rules or ``ner+lists`` would.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import spacy  # noqa: E402

from evaluate import parse  # noqa: E402
from preached.privacy import _phrase, decide, fold, lists  # noqa: E402


def person_flags(nlp, words: list[str], use_lists: bool) -> list[bool]:
    text = " ".join(words)
    offsets = []
    position = 0
    for word in words:
        offsets.append((position, position + len(word)))
        position += len(word) + 1
    flags = [False] * len(words)
    L = lists()
    for ent in nlp(text).ents:
        if ent.label_ != "PERSON":
            continue
        if use_lists:
            parts = _phrase(ent.text)
            names = [fold(w.strip(".,;:!?'\"")).removesuffix("'s") for w in ent.text.split()]
            known = all(n in L.bible or n in L.bible_major or n in L.public_single for n in names if n)
            if parts in L.public_phrases or known:
                continue
        for index, (start, end) in enumerate(offsets):
            if start < ent.end_char and end > ent.start_char:
                flags[index] = True
    return flags


def main() -> None:
    model, *paths = sys.argv[1:]
    started = time.perf_counter()
    nlp = spacy.load(model, disable=["lemmatizer"])
    load_s = time.perf_counter() - started
    for path in paths:
        for mode in ("ner", "ner+lists", "rules|ner"):
            counts: Counter = Counter()
            words_seen = 0
            started = time.perf_counter()
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                labelled = parse(json.loads(line)["text"])
                words = [w for w, _ in labelled]
                words_seen += len(words)
                flags = person_flags(nlp, words, mode != "ner")
                if mode == "rules|ner":
                    flags = [a or b for a, b in zip(flags, decide(words))]
                for (_, label), hidden in zip(labelled, flags):
                    counts[label, hidden] += 1
            elapsed = time.perf_counter() - started

            def rate(label: str) -> str:
                total = counts[label, True] + counts[label, False]
                return f"{counts[label, True]}/{total} = {counts[label, True] / total:.4f}" if total else "n/a"

            print(
                f"{model} {mode:9s} {Path(path).name}: recall {rate('private')}  "
                f"false-redaction {rate('public')}  other {rate('other')}  "
                f"{words_seen / elapsed:,.0f} words/s"
            )
    print(f"{model} load {load_s:.2f} s")


if __name__ == "__main__":
    main()
