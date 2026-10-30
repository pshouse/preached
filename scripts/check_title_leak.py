"""Lint: a "plain" eval question must not borrow words from its sermon's title.

A question in group "plain" fails when it shares a content word with the
title of any sermon in its ``relevant`` list. Content words are lowercase
alphabetic tokens longer than 3 letters that are not stopwords. Two words
match when their stems are equal, or one stem is a prefix of the other and
the shorter stem has at least 5 letters ("justified" / "justification").
The stemmer is a few suffix rules, deliberately loose: a false alarm costs a
rewrite, a miss lets title lookup back into the eval.

It also checks each plain question against ``SIGNATURE``: the doctrinal term
or scripture phrase a sermon is known by, which is not always in its title.

Usage: python scripts/check_title_leak.py   (exit 1 on any leak)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

QUESTIONS = Path(__file__).resolve().parents[1] / "eval" / "questions.jsonl"

STOPWORDS = frozenset(
    """
    about above after again against also because been before being below between both could does doing down
    during each even every from further have having here hers herself himself into itself just more most myself
    once only other ought ours ourselves over same shall should some such than that their theirs them themselves
    then there these they this those through under until upon very were what when where which while whom whose
    will with would your yours yourself yourselves
    """.split()
)

# Phrases a sermon is known by that its title does not carry (or carries
# only in part). Matched as lowercase substrings of the question. Keyed by
# sermon_id; applies to plain questions that list that sermon as relevant.
SIGNATURE = {
    "wesley-087": ["riches", "rich "],
    "wesley-108": ["riches", "rich "],
    "wesley-040": ["perfect", "sinless"],
    "wesley-076": ["perfect", "sinless"],
    "wesley-135": ["mourn"],
    "wesley-042": ["satan", "devil", "device", "devise"],
    "wesley-082": ["tempt", "way to escape", "way of escape", "able to bear"],
    "wesley-016": ["means of grace", "ordinance"],
    "wesley-001": ["salvation", "by faith", "saved", "grace"],
    "wesley-018": ["new birth", "born again", "regenerat"],
    "wesley-045": ["new birth", "born again", "regenerat"],
    "wesley-013": ["sin in believers", "sin remain", "indwelling sin"],
    "wesley-044": ["original sin", "total depravity", "fall of man"],
    "wesley-039": ["catholic", "ecumen"],
    "wesley-048": ["self-denial", "deny", "denial", "take up", "cross"],
    "wesley-041": ["wander"],
    "wesley-046": ["wilderness", "dark night"],
    "wesley-049": ["evil-speaking", "evil speaking", "speak evil", "backbit", "tale-bear", "talebear"],
    "wesley-047": ["heaviness", "manifold"],
    "wesley-101": ["communion", "lord's supper", "sacrament", "eucharist", "remembrance of me"],
    "wesley-086": ["backslid"],
    "wesley-050": ["use of money", "gain all you can"],
    "wesley-005": ["justif", "ungodly"],
}

_SUFFIXES = ("ations", "ation", "ings", "ing", "ness", "ments", "ment", "ies", "ers", "er", "ed", "es", "ly", "s")


def stem(word: str) -> str:
    word = word.lower()
    if word.endswith("'s"):
        word = word[:-2]
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    if word.endswith("i") or word.endswith("y"):
        word = word[:-1]
    if word.endswith("e"):
        word = word[:-1]
    return word


def content_words(text: str) -> set[str]:
    words = re.findall(r"[a-z]+(?:'s)?", text.lower())
    return {w for w in words if len(w.removesuffix("'s")) > 3 and w.removesuffix("'s") not in STOPWORDS}


def same_word(a: str, b: str) -> bool:
    sa, sb = stem(a), stem(b)
    if sa == sb:
        return True
    short, long = sorted((sa, sb), key=len)
    return len(short) >= 5 and long.startswith(short)


def leaks(question: dict) -> list[str]:
    """Each title word and signature phrase the question shares with its sermons."""
    query = question["query"]
    found = []
    titles = {p["sermon_id"]: p["sermon_title"] for p in question["relevant"]}
    for sermon_id, title in sorted(titles.items()):
        for qw in sorted(content_words(query)):
            for tw in sorted(content_words(title)):
                if same_word(qw, tw):
                    found.append(f'title word "{tw}" ({title}) ~ "{qw}"')
        lowered = query.lower()
        for phrase in SIGNATURE.get(sermon_id, []):
            if phrase in lowered:
                found.append(f'signature "{phrase.strip()}" ({sermon_id})')
    return list(dict.fromkeys(found))


def check(questions: list[dict], group: str = "plain") -> dict[str, list[str]]:
    return {q["id"]: hits for q in questions if q.get("group") == group and (hits := leaks(q))}


def main() -> int:
    questions = [json.loads(line) for line in QUESTIONS.read_text().splitlines() if line.strip()]
    groups: dict[str, int] = {}
    for q in questions:
        groups[q.get("group", "<missing>")] = groups.get(q.get("group", "<missing>"), 0) + 1
    print(f"{QUESTIONS.name}: {len(questions)} questions; groups {json.dumps(groups, sort_keys=True)}")
    missing = [q["id"] for q in questions if "group" not in q]
    bad = check(questions)
    plain = sum(q.get("group") == "plain" for q in questions)
    for qid, hits in bad.items():
        for hit in hits:
            print(f"LEAK {qid}: {hit}")
    if missing:
        print(f"MISSING group: {', '.join(missing)}")
    print(f"plain questions checked: {plain}; leaking: {len(bad)}")
    return 1 if bad or missing else 0


if __name__ == "__main__":
    sys.exit(main())
