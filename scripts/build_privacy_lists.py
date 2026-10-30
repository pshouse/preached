"""Build the word lists ``preached.privacy`` loads. Run once; output is committed.

Sources (all public domain, downloaded to /cache/privacy/raw, never committed):

- SSA baby names 1880-2017 via the ``babynames`` R package
  (https://github.com/hadley/babynames, data/babynames.rda), converted to
  ``ssa_totals.csv`` (births per name, all years) and ``ssa_since1990.csv``.
  ssa.gov blocks scripted downloads, so the R package copy is used.
- KJV, Project Gutenberg #10 (``kjv.txt``).
- World English Bible, ebible.org ``engwebp_vpl.txt``.
- 12dicts 6.0.2 ``American/2of12inf.txt`` (Alan Beale, public domain).

    python3 scripts/build_privacy_lists.py /cache/privacy/raw

Writes ``src/preached/privacy_data/``:

- ``given_names.txt``: first names given to at least 1,000 US babies since
  1880 or 500 since 1990.
- ``bible_names.txt``: ``word<TAB>count`` for words the KJV or WEB capitalizes
  in the middle of a clause at least twice (people and places), minus
  English words that are not also given names ("The LORD", "Most High"). Words after a comma, colon or
  quote are skipped, because the KJV capitalizes the first word of speech.
- ``lexicon.txt.gz``: lowercase English words (2of12inf plus every lowercase
  word in either Bible). A capitalized token found here is a word unless
  another list says it is a name.
"""

from __future__ import annotations

import csv
import gzip
import re
import sys
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "preached" / "privacy_data"
TOKEN = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?|[^\sA-Za-z]+")
BREAK = set(".?!:;,\"'“”‘’()[]-—")


def ssa_names(raw: Path) -> set[str]:
    names = set()
    for file, floor in (("ssa_totals.csv", 1000), ("ssa_since1990.csv", 500)):
        with open(raw / file, newline="") as handle:
            reader = csv.reader(handle)
            next(reader)
            for name, count in reader:
                if int(count) >= floor:
                    names.add(name)
    return names


def kjv_verses(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    start = text.index("The Old Testament of the King James Version")
    end = text.index("*** END OF THE PROJECT GUTENBERG")
    body = re.sub(r"\b\d+:\d+\b", " . ", text[start:end])
    return body.split("\n\n")


def web_verses(path: Path) -> list[str]:
    return [line.split(" ", 2)[2] for line in path.read_text(encoding="utf-8").splitlines() if line.count(" ") >= 2]


def bible_words(paragraphs: list[str], capitalized: Counter, lower: set[str]) -> None:
    for paragraph in paragraphs:
        tokens = TOKEN.findall(paragraph)
        previous = "."
        for token in tokens:
            if token[0].isalpha():
                word = re.sub(r"['’]s$", "", token)
                if word.islower():
                    lower.add(word)
                elif word[0].isupper() and word[1:].islower() and previous[-1].isalpha():
                    capitalized[word] += 1
            previous = token


def main() -> None:
    raw = Path(sys.argv[1] if len(sys.argv) > 1 else "/cache/privacy/raw")
    OUT.mkdir(parents=True, exist_ok=True)

    given = ssa_names(raw)
    capitalized: Counter = Counter()
    bible_lower: set[str] = set()
    bible_words(kjv_verses(raw / "kjv.txt"), capitalized, bible_lower)
    bible_words(web_verses(raw / "web" / "engwebp_vpl.txt"), capitalized, bible_lower)
    english = {line.strip() for line in open(raw / "12dicts" / "American" / "2of12inf.txt", encoding="latin-1")}
    english = {word.rstrip("%!&+") for word in english if word}
    # "The LORD", "Most Highest": a capitalized English word is a Bible name
    # only if people are also given it (Mark, Job).
    bible = {
        word
        for word, count in capitalized.items()
        if count >= 2 and (word.lower() not in english or word in given)
    }
    lexicon = english | bible_lower

    (OUT / "given_names.txt").write_text("\n".join(sorted(given)) + "\n")
    (OUT / "bible_names.txt").write_text("".join(f"{word}\t{capitalized[word]}\n" for word in sorted(bible)))
    with gzip.open(OUT / "lexicon.txt.gz", "wt", encoding="utf-8", compresslevel=9) as handle:
        handle.write("\n".join(sorted(lexicon)) + "\n")
    print(f"given_names {len(given)}  bible_names {len(bible)}  lexicon {len(lexicon)}")


if __name__ == "__main__":
    main()
