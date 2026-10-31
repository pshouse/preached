"""Lint: a "plain" eval question must not borrow words from its sermon's title.

A question in group "plain" fails when it shares a content word with the
title of any sermon in its ``relevant`` list. Content words are lowercase
alphabetic tokens of 3 or more letters that are not stopwords. Two words
match when their stems are equal, or one stem is a prefix of the other and
the shorter stem has at least 5 letters ("justified" / "justification").
The stemmer is a few suffix rules, deliberately loose: a false alarm costs a
rewrite, a miss lets title lookup back into the eval.

It also checks each plain question against ``SIGNATURE``: the doctrinal term
or scripture phrase a sermon is known by, which is not always in its title,
and against ``SYNONYMS``: a short hand-picked list of words that mean the
title's key term ("devil" for Satan's Devices, "grief" for mourning).
Three-letter title words count ("sin"), and "-ial"/"-ied" inflections stem
together ("denied" ~ "Self-denial").

Phrase overlap (EVAL-GRADE): a plain question also fails when it shares two
consecutive content words (stopwords skipped, stems compared as above) with
a grade-2 quote of its own labels or with the key scripture of a grade-2
sermon (``eval/key_scripture.json``). "taking thought" ~ "Take [therefore
no] thought" and "child of God" are the cases this was written for. A pair
made only of very common religious words ("God", "Lord", "Jesus") does not
count.

Modern verse wording counts in that same pair check: "anxious" / "worry"
stand in for "thought", and "tomorrow" stands in for "morrow", so "anxious
about tomorrow" overlaps Matt 6:34 ("Take no thought for the morrow").
A single distinctive word also counts: a content word whose stem is 8
letters or longer, shared with a grade-2 quote or that sermon's key
scripture ("sanctification"). "fell" stems with "fall", and "fell away" is
a signature of the backsliders sermon.

Groups checked: ``plain`` fails the lint. ``plain-blind`` questions were
written blind to the corpus and their wording is frozen, so leaks there are
printed as notes and do not fail.

Usage: python scripts/check_title_leak.py [questions.jsonl]   (exit 1 on any plain leak)
       python scripts/check_title_leak.py --write-scripture   (rebuild eval/key_scripture.json
                                                               from /cache/corpus/wesley/sermons.jsonl)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "eval" / "questions.jsonl"
KEY_SCRIPTURE = ROOT / "eval" / "key_scripture.json"
SERMONS = Path("/cache/corpus/wesley/sermons.jsonl")

STOPWORDS = frozenset(
    """
    about above after again against also because been before being below between both could does doing down
    during each even every from further have having here hers herself himself into itself just more most myself
    once only other ought ours ourselves over same shall should some such than that their theirs them themselves
    then there these they this those through under until upon very were what when where which while whom whose
    will with would your yours yourself yourselves
    all and any are but can did for had has her him his how its may nor not now one our out own she the
    too two was way who why yes yet you therefore unto thee thou thy thine shall hath doth
    """.split()
)

# Words so common in any Christian question that a shared pair made only of
# them is not a leak ("love God", "Jesus Christ").
GENERIC = frozenset("god lord jesus christ christian wesley say said teach taught".split())

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
    "wesley-086": ["backslid", "fell away", "fallen away", "fall away"],
    "wesley-050": ["use of money", "gain all you can"],
    "wesley-005": ["justif", "ungodly"],
}

# Words that mean a title's key term, by sermon_id. Matched like title words
# (stemmed). Deliberately short: paraphrases ("weighed down", "drifting")
# are what a plain question is for; these are the term under another name.
SYNONYMS = {
    "wesley-050": ["cash", "wealth", "mammon"],
    "wesley-087": ["wealth", "wealthy", "rich", "affluent", "mammon"],
    "wesley-108": ["wealth", "wealthy", "rich", "affluent", "mammon"],
    "wesley-040": ["perfect", "sinless", "flawless"],
    "wesley-076": ["perfect", "sinless", "flawless"],
    "wesley-135": ["grief", "grieve", "bereaved", "bereavement"],
    "wesley-042": ["devil", "demon", "tempter", "wiles", "schemes", "enemy", "trick", "deceive", "deception"],
    "wesley-082": ["tempted", "enticed", "enticement"],
    "wesley-016": ["sacrament", "ordinance"],
    "wesley-101": ["eucharist", "sacrament", "supper", "mass"],
    "wesley-001": ["saved", "rescue"],
    "wesley-005": ["righteous", "acquitted", "pardoned"],
    "wesley-018": ["reborn", "regeneration"],
    "wesley-045": ["reborn", "regeneration"],
    "wesley-044": ["depravity", "corruption", "fallen"],
    "wesley-039": ["ecumenical", "universal"],
    "wesley-048": ["sacrifice", "renounce", "renunciation"],
    "wesley-041": ["distraction", "distracted", "straying"],
    "wesley-046": ["desert", "desolation", "dryness"],
    "wesley-049": ["gossip", "slander", "backbiting"],
    "wesley-047": ["sorrow", "depression", "depressed"],
    "wesley-086": ["relapse", "lapsed", "apostate"],
    "wesley-010": ["testimony", "assurance"],
    "wesley-011": ["testimony", "assurance"],
}

_SUFFIXES = ("ations", "ation", "ings", "ing", "ness", "ments", "ment", "ials", "ial", "ied", "ies", "ers", "er",
             "ed", "es", "ly", "s")

# Irregular verbs the suffix rules miss. "fell away" ~ "fall away".
_IRREGULAR = {"fell": "fall", "fallen": "fall"}

# A modern word and the KJV word it paraphrases, for quote and scripture
# pairs only. "anxious about tomorrow" ~ Matt 6:34 "thought for the morrow".
MODERN = {
    "anxious": "thought",
    "anxiety": "thought",
    "worry": "thought",
    "worried": "thought",
    "worrying": "thought",
    "tomorrow": "morrow",
}

# A single shared word this long (after stemming) is distinctive enough to
# be a leak on its own. "sanctification" stems to 9 letters.
DISTINCTIVE_STEM = 8


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
    if len(word) >= 4 and word[-1] == word[-2] and word[-1] not in "aeiouls":
        word = word[:-1]  # sinning -> sinn -> sin
    return _IRREGULAR.get(word, word)


def tokens(text: str) -> list[str]:
    """Content words in order: 3+ letters, not stopwords."""
    words = re.findall(r"[a-z]+(?:'s)?", text.lower().replace("\u2019", "'"))
    return [w for w in words if len(w.removesuffix("'s")) >= 3 and w.removesuffix("'s") not in STOPWORDS]


def content_words(text: str) -> set[str]:
    return set(tokens(text))


def same_word(a: str, b: str) -> bool:
    sa, sb = stem(a), stem(b)
    if sa == sb:
        return True
    short, long = sorted((sa, sb), key=len)
    return len(short) >= 5 and long.startswith(short)


def _forms(word: str) -> list[str]:
    """``word`` plus its KJV paraphrase, when it has one."""
    bare = word.lower().removesuffix("'s")
    mapped = MODERN.get(bare)
    return [word, mapped] if mapped else [word]


def same_or_modern(a: str, b: str) -> bool:
    """``same_word``, or either word is the modern wording of the other."""
    return any(same_word(x, y) for x in _forms(a) for y in _forms(b))


def _load_key_scripture() -> dict[str, dict]:
    return json.loads(KEY_SCRIPTURE.read_text()) if KEY_SCRIPTURE.exists() else {}


def shared_pairs(query: str, text: str) -> list[str]:
    """Consecutive content-word pairs of ``query`` that also occur consecutively in ``text``."""
    q, t = tokens(query), tokens(text)
    t_pairs = list(zip(t, t[1:]))
    found = []
    for a, b in zip(q, q[1:]):
        if a in GENERIC and b in GENERIC:
            continue
        for x, y in t_pairs:
            if same_or_modern(a, x) and same_or_modern(b, y):
                found.append(f"{a} {b}")
                break
    return found


def shared_distinctive(query: str, text: str) -> list[tuple[str, str]]:
    """Single distinctive words (stem length >= DISTINCTIVE_STEM) shared by both texts."""
    qwords = sorted(w for w in content_words(query)
                    if w not in GENERIC and stem(w) not in GENERIC and len(stem(w)) >= DISTINCTIVE_STEM)
    twords = sorted(content_words(text))
    found = []
    for qw in qwords:
        for tw in twords:
            if tw in GENERIC or stem(tw) in GENERIC:
                continue
            if same_word(qw, tw):
                found.append((tw, qw))
                break
    return found


def leaks(question: dict, key_scripture: dict[str, dict] | None = None) -> list[str]:
    """Each title word, synonym, signature phrase, and quote/scripture phrase the question shares."""
    query = question["query"]
    found = []
    # Proposed grade-1 labels (wider grading) come from many sermons; a title
    # leak is about the sermons the question was written for.
    expected = [p for p in question["relevant"] if p.get("status") != "proposed" or int(p.get("grade", 0)) == 2]
    titles = {p["sermon_id"]: p["sermon_title"] for p in expected}
    for sermon_id, title in sorted(titles.items()):
        for qw in sorted(content_words(query)):
            for tw in sorted(content_words(title)):
                if same_word(qw, tw):
                    found.append(f'title word "{tw}" ({title}) ~ "{qw}"')
            for syn in SYNONYMS.get(sermon_id, []):
                if same_word(qw, syn):
                    found.append(f'synonym "{syn}" ({title}) ~ "{qw}"')
        lowered = query.lower()
        for phrase in SIGNATURE.get(sermon_id, []):
            if phrase in lowered:
                found.append(f'signature "{phrase.strip()}" ({sermon_id})')
    key_scripture = _load_key_scripture() if key_scripture is None else key_scripture
    gold = [p for p in question["relevant"] if int(p.get("grade", 0)) == 2]
    for p in gold:
        where = p.get("passage_id", p["sermon_id"])
        for pair in shared_pairs(query, p["quote"]):
            found.append(f'quote phrase "{pair}" ({where})')
        for tw, qw in shared_distinctive(query, p["quote"]):
            found.append(f'distinctive word "{tw}" ({where}) ~ "{qw}"')
    for sermon_id in sorted({p["sermon_id"] for p in gold}):
        entry = key_scripture.get(sermon_id, {})
        text = entry.get("text", "")
        ref = entry.get("scripture", "")
        for pair in shared_pairs(query, text):
            found.append(f'scripture phrase "{pair}" ({sermon_id} {ref})')
        for tw, qw in shared_distinctive(query, text):
            found.append(f'distinctive word "{tw}" ({sermon_id} {ref}) ~ "{qw}"')
    return list(dict.fromkeys(found))


def check(questions: list[dict], group: str = "plain") -> dict[str, list[str]]:
    key_scripture = _load_key_scripture()
    return {q["id"]: hits for q in questions
            if q.get("group") == group and not q.get("excluded") and (hits := leaks(q, key_scripture))}


def write_key_scripture(sermons: Path = SERMONS, out: Path = KEY_SCRIPTURE) -> int:
    """Each sermon's text (the scripture printed above it), cut at its reference."""
    result = {}
    for line in sermons.read_text().splitlines():
        r = json.loads(line)
        m = re.search(r"(\d+):(\d+)", r.get("scripture") or "")
        cut = -1
        if m:
            ref = re.search(re.escape(m.group(1)) + r":\s?" + re.escape(m.group(2)), r["text"][:5000])
            cut = ref.start() if ref else -1
        if cut > 0:
            text = re.sub(r"\s+", " ", r["text"][:cut])
            text = re.sub(r"[\s.,;]*[A-Z1-3][A-Za-z. ]*$", "", text).strip()
        else:
            text = r["opening_quote"]
        result[r["sermon_id"]] = {"scripture": r["scripture"], "text": text}
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    return len(result)


def main() -> int:
    if sys.argv[1:] == ["--write-scripture"]:
        print(f"wrote {KEY_SCRIPTURE}: {write_key_scripture()} sermons")
        return 0
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else QUESTIONS
    questions = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    groups: dict[str, int] = {}
    for q in questions:
        groups[q.get("group", "<missing>")] = groups.get(q.get("group", "<missing>"), 0) + 1
    print(f"{path.name}: {len(questions)} questions; groups {json.dumps(groups, sort_keys=True)}")
    missing = [q["id"] for q in questions if "group" not in q]
    bad = check(questions)
    plain = sum(q.get("group") == "plain" for q in questions)
    for qid, hits in bad.items():
        for hit in hits:
            print(f"LEAK {qid}: {hit}")
    blind = check(questions, "plain-blind")
    for qid, hits in blind.items():
        for hit in hits:
            print(f"note {qid} (plain-blind, wording frozen): {hit}")
    if missing:
        print(f"MISSING group: {', '.join(missing)}")
    print(f"plain questions checked: {plain}; leaking: {len(bad)}")
    n_blind = sum(q.get("group") == "plain-blind" and not q.get("excluded") for q in questions)
    if n_blind:
        print(f"plain-blind questions checked: {n_blind}; overlapping (note only): {len(blind)}")
    return 1 if bad or missing else 0


if __name__ == "__main__":
    sys.exit(main())
