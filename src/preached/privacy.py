"""Replace congregants' names in ASR words with ``[name]``.

``redact(words) -> words`` is the W2-YT hook (``preached.youtube.privacy``).
A word is any record that carries ``start``, ``end`` and text: the W2-YT
``Word`` dataclass, a W1-C ``(start, end, word)`` tuple or list, or a dict with
``"text"`` or ``"word"``. The result has the same records in the same order
with the same times; only a name's letters change ("Jane's," -> "[name]'s,").
Words inside a configured drop window are removed. When nothing changes the
input list itself is returned.

Rules, no model. Whisper capitalizes names, so the evidence is the casing and
a few lists built by ``scripts/build_privacy_lists.py`` (SSA given names, KJV
and WEB proper nouns, an English word list) plus three hand-written lists
(major Bible figures, public and historical people, capitalized non-names).

- A listed public phrase ("John Wesley", "C. S. Lewis") is kept.
- A run of capitalized name words is a span. A span of two or more words is
  a person's full name, and is redacted unless every word is a Bible name
  ("Simon Peter").
- A title ("Sister", "Mr.", "Pastor"), "my/our <relative>", "named", or a
  prayer or announcement verb ("pray for", "welcome", "thanks to") before a
  span marks it private, even when it is a Bible name ("my son Daniel").
- A lone given name is redacted. A lone major Bible figure who shares a
  given name (John, Mary, Daniel), or a public surname that is also a given
  name (Lewis, Graham), is kept unless the sentence reads more like a prayer
  request or a personal story than like scripture or history.
- A capitalized word on no list and not an English word is treated as a
  surname and redacted.

Per-library settings come from a TOML file (see ``privacy.example.toml``),
passed as ``config=`` or named by the ``PREACHED_PRIVACY`` environment
variable. Lists load once per process (about 50 ms) and redaction runs at
roughly 200k words a second on one core.
"""

from __future__ import annotations

import dataclasses
import gzip
import os
import re
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

DATA = Path(__file__).with_name("privacy_data")
TOKEN = "[name]"
CONFIG_ENV = "PREACHED_PRIVACY"

# Before a name, these mark a person in the congregation, not a Bible figure.
TITLES = {
    "brother", "sister", "bro", "sis", "mr", "mrs", "ms", "miss", "dr", "pastor", "deacon",
    "elder", "coach", "aunt", "auntie", "uncle", "granny", "grandma", "grandpa", "nana",
    "papaw", "pawpaw", "mamaw", "meemaw", "officer", "sergeant", "sgt", "captain",
    "professor", "preacher", "reverend", "rev", "minister", "nurse", "judge",
}
# Titles that are titles even when Whisper writes them in lowercase.
LOWER_TITLES = {"mr", "mrs", "ms", "miss", "dr", "pastor", "deacon", "coach", "granny", "papaw", "mamaw", "meemaw"}
RELATIONS = {
    "friend", "friends", "buddy", "wife", "husband", "son", "sons", "daughter", "daughters",
    "mom", "mother", "mama", "momma", "mommy", "dad", "daddy", "father", "brother", "sister",
    "grandson", "granddaughter", "grandmother", "grandfather", "granddaddy", "grandaddy",
    "grandma", "grandpa", "granny", "grandbaby", "nephew", "niece", "cousin", "uncle",
    "aunt", "neighbor", "neighbors", "boss", "coworker", "roommate", "girlfriend",
    "boyfriend", "fiance", "fiancee", "kids", "boy", "girl", "baby", "teacher", "student",
    "partners", "partner", "member", "members", "missionary", "missionaries", "deacon",
    "pastor", "stepson", "stepdaughter", "sweetheart", "classmate",
}
POSSESSORS = {"my", "our", "me"}
FILLERS = {
    "sweet", "little", "dear", "precious", "beloved", "good", "old", "own", "best", "oldest",
    "youngest", "late", "baby", "big", "new", "first", "dear", "sweet", "two", "wife's",
    "husband's", "pastor's", "mom's", "dad's", "mother's", "father's", "sister's",
    "brother's", "friend's", "grown", "adopted", "dearest", "lifelong", "missionary",
}
# Lowercase word sequences that, right before a name, mark a living person.
CUES = [
    ("pray", "for"), ("praying", "for"), ("prayers", "for"), ("prayer", "for"), ("pray", "with"),
    ("lift", "up"), ("lifting", "up"), ("remember",), ("remembering",), ("welcome",),
    ("welcoming",), ("congratulations", "to"), ("congratulations",), ("congrats", "to"),
    ("birthday", "to"), ("birthday",), ("anniversary", "to"), ("anniversary",),
    ("thank", "you", "to"), ("thanks", "to"), ("thank",), ("out", "to"), ("talk", "to"),
    ("talk", "with"), ("talked", "to"), ("talked", "with"), ("see",), ("call",), ("text",),
    ("email",), ("contact",), ("meet",), ("named",), ("name", "is"), ("name", "was"),
    ("sitting", "with"), ("hand",), ("baptized",), ("visit",), ("visiting",), ("hug",),
    ("me", "and"), ("with", "my"),
]
PRIVATE_CONTEXT = {
    "hospital", "surgery", "chemo", "cancer", "doctor", "doctors", "biopsy", "diagnosis",
    "diagnosed", "rehab", "icu", "sick", "flu", "visitation", "funeral", "passed", "birthday",
    "anniversary", "pregnant", "expecting", "baby", "grandbaby", "born", "kids", "grandson",
    "granddaughter", "grandkids", "husband", "wife", "mom", "mama", "momma", "dad", "daddy",
    "deployed", "job", "office", "choir", "youth", "deacon", "deacons", "nursery", "kitchen",
    "team", "sign", "signup", "welcome", "thank", "thanks", "congratulations", "call", "text",
    "email", "visit", "visitors", "meals", "cards", "prayers", "praying", "y'all", "tonight",
    "today", "yesterday", "week", "weekend", "camp", "class", "school", "college", "nursing",
    "truck", "car", "wreck", "phone", "married", "wedding", "retiring", "retired", "friend",
    "buddy", "neighbor", "boss", "our",
    "service", "lobby", "potluck", "fellowship", "small", "group", "volunteer", "signups",
    "cookout", "breakfast", "recovery", "rehab", "addicted", "overdosed", "transplant",
    "results", "scan", "therapy", "treatment", "health", "gym", "work", "coworker",
    "grandma", "granny", "grandpa", "mamaw", "papaw", "grandmother", "grandfather",
}
BIBLE_CONTEXT = {
    "apostle", "apostles", "prophet", "prophets", "prophetess", "disciple", "disciples", "king",
    "queen", "lord", "jesus", "christ", "god", "scripture", "scriptures", "verse", "verses",
    "chapter", "book", "gospel", "epistle", "letter", "letters", "temple", "israel",
    "israelites", "egypt", "jerusalem", "galilee", "pharaoh", "priest", "priests", "angel",
    "angels", "tomb", "cross", "crucified", "pharisees", "unto", "thee", "thou", "thy", "ye",
    "begat", "tribe", "wilderness", "mountain", "bible", "testament", "psalm", "prophecy",
    "miracle", "parable", "ark", "sea", "sword", "preached", "sermon", "sermons", "century",
    "revival", "hymn", "hymns", "reformer", "reformation", "wrote", "writes", "written",
    "quote", "puritan", "spirit", "heaven", "messiah", "brothers", "son", "sons", "father",
    "baptist", "mother", "gentiles", "jews", "synagogue", "crowd", "multitude", "pharisee",
    "said", "says", "says,", "prison", "jail", "ancient", "greek", "hebrew", "law", "covenant",
    "sacrifice", "altar", "lamb", "ram", "sheep", "shepherd", "fishermen", "boat", "net",
    "nets", "well", "manger", "stable", "wise", "magi", "herod", "pilate", "rome", "roman",
    "empire", "theologian", "preacher", "missionary", "martyr", "martyred", "hymn", "author",
    "book", "books", "wrote,", "commented", "taught", "put", "famous", "famously",
}
NUMBER_WORDS = {
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
    "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
    "chapter", "chapters", "verse", "verses",
}
JOINERS = {"and", "&"}
# After a sentence-initial word that is both a name and an English word
# ("Crystal", "Will", "Mark"), these make it the subject of a story.
SUBJECT_VERBS = {
    "told", "said", "says", "came", "comes", "asked", "asks", "wanted", "called", "calls",
    "gave", "went", "texted", "prayed", "shared", "brought", "walked", "sang", "cried",
    "looked", "stood", "leads", "led", "laughed", "got", "was", "is", "has", "had", "and",
    "just", "and", "will", "wants", "needs", "loves", "lost", "passed", "started", "starts",
    "turned", "turns", "made", "makes", "drove", "works", "worked", "left", "used",
}
# Same, for place names that are also given names ("Austin", "Charlotte").
PLACE_SUBJECT_VERBS = SUBJECT_VERBS - {"was", "is", "has", "had", "and", "just", "will", "used"}
# A lone unknown capitalized word after these is a place or thing ("at Flossenburg").
LOCATIVES = {"at", "in", "from", "near", "into", "across", "outside", "through", "of", "to", "toward", "towards", "around"}
FAMILY_WORDS = {"family", "families", "household", "kids", "clan", "house", "home", "boys", "girls"}
NEVER_NAMES = {
    "the", "a", "an", "my", "our", "his", "her", "their", "your", "and", "but", "so", "as",
    "at", "in", "on", "to", "for", "of", "if", "or", "said", "son", "sir", "baby", "boy",
    "male", "lady", "pa", "om", "we", "he", "she", "they", "it", "i", "you",
}
SENTENCE_END = re.compile(r"[.?!][\"'”’)\]]*$")
WORD = re.compile(r"^(?P<lead>[^A-Za-z]*)(?P<core>[A-Za-z](?:[A-Za-z'’.-]*[A-Za-z])?)(?P<tail>(?:['’]s|s['’]|['’])?[^A-Za-z]*)$")
ABBREVIATION = re.compile(r"^(?:mr|mrs|ms|dr|st|jr|sr|rev|sgt|capt|prof|[a-z])\.$|^(?:[a-z]\.)+$", re.I)
INITIALS = re.compile(r"^(?:[A-Z]\.)+$|^[A-Z]$")
CONTEXT_SPAN = 12


# ---------------------------------------------------------------- lists


@dataclass(frozen=True)
class Lists:
    given: frozenset[str]
    bible: frozenset[str]
    bible_major: frozenset[str]
    public_single: frozenset[str]
    public_phrases: frozenset[tuple[str, ...]]
    places: frozenset[str]
    terms: frozenset[str]
    lexicon: frozenset[str]
    longest_phrase: int


def _words(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def _phrase(text: str) -> tuple[str, ...]:
    """'C. S. Lewis' and 'C.S. Lewis' -> ('c', 's', 'lewis')."""
    parts: list[str] = []
    for piece in text.replace("’", "'").split():
        if INITIALS.match(piece.rstrip(",;")):
            parts.extend(letter.lower() for letter in piece if letter.isalpha())
        else:
            parts.append(piece.strip(".,;:!?\"'()").lower())
    return tuple(part for part in parts if part)


@lru_cache(maxsize=1)
def lists() -> Lists:
    given = frozenset(_words(DATA / "given_names.txt"))
    bible = frozenset(line.split("\t", 1)[0] for line in _words(DATA / "bible_names.txt"))
    major = frozenset(word for line in _words(DATA / "bible_major.txt") for word in line.split())
    public_lines = _words(DATA / "public_names.txt")
    phrases = frozenset(_phrase(line) for line in public_lines if len(_phrase(line)) > 1)
    single = frozenset(line for line in public_lines if len(_phrase(line)) == 1)
    places = frozenset(word for line in _words(DATA / "places.txt") for word in line.split())
    terms = frozenset(word for line in _words(DATA / "terms.txt") for word in line.split())
    with gzip.open(DATA / "lexicon.txt.gz", "rt", encoding="utf-8") as handle:
        lexicon = frozenset(handle.read().split())
    return Lists(
        given=given,
        bible=bible,
        bible_major=major,
        public_single=single,
        public_phrases=phrases,
        places=places,
        terms=terms,
        lexicon=lexicon,
        longest_phrase=max((len(p) for p in phrases), default=1),
    )


# ---------------------------------------------------------------- config


@dataclass(frozen=True)
class Config:
    """Per-library settings. Names compare case-insensitively."""

    allow: frozenset[tuple[str, ...]] = frozenset()
    block: frozenset[str] = frozenset()
    drop: tuple[tuple[str | None, float, float], ...] = ()
    token: str = TOKEN

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        unknown = set(data) - {"allow", "block", "drop", "token"}
        if unknown:
            raise ValueError(f"unknown privacy settings: {', '.join(sorted(unknown))}")
        allow = frozenset(_phrase(name) for name in data.get("allow", []) if _phrase(name))
        block = frozenset(word for name in data.get("block", []) for word in _phrase(name))
        drop = []
        for window in data.get("drop", []):
            start, end = float(window["start"]), float(window["end"])
            if end <= start:
                raise ValueError(f"drop window ends before it starts: {window}")
            drop.append((window.get("source"), start, end))
        token = str(data.get("token", TOKEN))
        return cls(allow=allow, block=block, drop=tuple(drop), token=token)


def load_config(path: str | os.PathLike[str]) -> Config:
    with open(path, "rb") as handle:
        return Config.from_dict(tomllib.load(handle))


def default_config() -> Config:
    path = os.environ.get(CONFIG_ENV)
    return load_config(path) if path else Config()


# ---------------------------------------------------------------- word records


def _text(word: Any) -> str:
    if isinstance(word, dict):
        return word["text"] if "text" in word else word["word"]
    if isinstance(word, (tuple, list)):
        return word[2]
    return word.text


def _start(word: Any) -> float:
    if isinstance(word, dict):
        return float(word["start"])
    if isinstance(word, (tuple, list)):
        return float(word[0])
    return float(word.start)


def _end(word: Any) -> float:
    if isinstance(word, dict):
        return float(word["end"])
    if isinstance(word, (tuple, list)):
        return float(word[1])
    return float(word.end)


def _with_text(word: Any, text: str) -> Any:
    if isinstance(word, dict):
        return {**word, ("text" if "text" in word else "word"): text}
    if isinstance(word, tuple):
        return (*word[:2], text, *word[3:])
    if isinstance(word, list):
        return [*word[:2], text, *word[3:]]
    if dataclasses.is_dataclass(word):
        return dataclasses.replace(word, text=text)
    copy = word.__class__.__new__(word.__class__)
    copy.__dict__.update(word.__dict__, text=text)
    return copy


# ---------------------------------------------------------------- tokens


@dataclass
class Tok:
    lead: str
    core: str
    tail: str
    start_of_sentence: bool
    lower: str = ""
    cap: bool = False
    initials: bool = False
    keep: bool = False
    redact: bool = False
    seed: bool = False
    joinable: bool = False
    phrase_parts: tuple[str, ...] = field(default_factory=tuple)

    @property
    def breaks_after(self) -> bool:
        """Punctuation after the word ends a name (but not 'C.' or a possessive)."""
        if self.initials:
            return False
        rest = self.tail.lstrip("'’s")
        return any(ch in rest for ch in ",.;:!?()\"”")


def _tokens(texts: Sequence[str]) -> list[Tok]:
    toks = []
    previous = ""
    for index, text in enumerate(texts):
        match = WORD.match(text.strip())
        start = index == 0 or (
            bool(SENTENCE_END.search(previous)) and not ABBREVIATION.match(previous)
        )
        previous = text.strip()
        if not match:
            toks.append(Tok("", "", text, start))
            continue
        core, tail = match["core"], match["tail"]
        if re.search(r"['’]s$", core):
            core, tail = core[:-2], core[-2:] + tail
        tok = Tok(match["lead"], core, tail, start)
        tok.lower = core.lower().replace("’", "'")
        tok.cap = core[0].isupper()
        tok.initials = bool(INITIALS.match(core + ("." if match["tail"].startswith(".") else "")))
        tok.phrase_parts = _phrase(core)
        toks.append(tok)
    return toks


def _is_word(lexicon: frozenset[str], lower: str) -> bool:
    if lower in lexicon or lower in NEVER_NAMES:
        return True
    if "'" in lower:
        head = lower.split("'", 1)[0]
        return head in lexicon or head in NEVER_NAMES
    for suffix in ("'s", "s", "es"):
        if lower.endswith(suffix) and lower[: -len(suffix)] in lexicon:
            return True
    return False


# ---------------------------------------------------------------- redact


def redact(words: list, *, config: Config | None = None, source: str | None = None) -> list:
    """privacy.redact(words) -> words, with congregant names replaced.

    ``source`` is the video or sermon id that ``drop`` windows name; windows
    without a ``source`` apply to every input.
    """
    config = default_config() if config is None else config
    if config.drop:
        kept = [word for word in words if not _dropped(word, config, source)]
        dropped = len(kept) != len(words)
    else:
        kept, dropped = words, False
    texts = [_text(word) for word in kept]
    decisions = decide(texts, config)
    if not any(decisions):
        return kept if dropped else words
    out = []
    for word, text, hide in zip(kept, texts, decisions):
        out.append(_with_text(word, _mask(text, config.token)) if hide else word)
    return out


def _dropped(word: Any, config: Config, source: str | None) -> bool:
    middle = (_start(word) + _end(word)) / 2
    for window_source, start, end in config.drop:
        if window_source is not None and window_source != source:
            continue
        if start <= middle < end:
            return True
    return False


def _mask(text: str, token: str) -> str:
    match = WORD.match(text.strip())
    if not match:
        return token
    return f"{match['lead']}{token}{match['tail']}"


def redact_text(text: str, config: Config | None = None) -> str:
    """Convenience for plain text: split on spaces, redact, join."""
    texts = text.split()
    decisions = decide(texts, config or Config())
    token = (config or Config()).token
    return " ".join(_mask(t, token) if hide else t for t, hide in zip(texts, decisions))


def decide(texts: Sequence[str], config: Config | None = None) -> list[bool]:
    """One flag per word: True when the word is (part of) a private name."""
    config = config or Config()
    L = lists()
    toks = _tokens(texts)
    _mark_phrases(toks, L, config)
    _mark_candidates(toks, L, config)
    for start, end in _spans(toks):
        _decide_span(toks, start, end, L, config)
    _mark_lowercase(toks, L, config)
    return [tok.redact for tok in toks]


def _mark_phrases(toks: list[Tok], L: Lists, config: Config) -> None:
    """Keep listed public names and configured allowed names, longest first."""
    phrases = L.public_phrases | {p for p in config.allow if len(p) > 1}
    longest = max(L.longest_phrase, max((len(p) for p in config.allow), default=1))
    i = 0
    while i < len(toks):
        if not toks[i].cap:
            i += 1
            continue
        matched = 0
        for length in range(min(longest * 2, len(toks) - i), 1, -1):
            parts: list[str] = []
            for tok in toks[i : i + length]:
                parts.extend(tok.phrase_parts)
            if tuple(parts) in phrases and not any(t.breaks_after for t in toks[i : i + length - 1]):
                matched = length
                break
        if matched:
            after = toks[i + matched] if i + matched < len(toks) else None
            last = toks[i + matched - 1]
            followed = (
                after is not None
                and not last.breaks_after
                and after.cap
                and not after.initials
                and _seed_kind(after, L) in ("given", "unknown")
            )
            titled = i > 0 and _is_title(toks[i - 1]) and toks[i - 1].lower not in {"saint", "st"}
            blocked = any(part in config.block for t in toks[i : i + matched] for part in t.phrase_parts)
            if not followed and not titled and not blocked:
                for tok in toks[i : i + matched]:
                    tok.keep = True
                i += matched
                continue
        i += 1


def _seed_kind(tok: Tok, L: Lists) -> str | None:
    """What a capitalized word looks like on its own, before context."""
    core = tok.core
    if not tok.cap or tok.initials or not core:
        return None
    if tok.lower in NEVER_NAMES:
        return "word"
    if core in L.terms or core in L.places:
        return "term"
    if core in L.public_single:
        return "public"
    if core in L.bible_major:
        return "major"
    if core in L.bible and core not in L.given:
        return "bible"
    if core in L.given:
        return "given"
    if core in L.bible:
        return "bible"
    if _is_word(L.lexicon, tok.lower):
        return "word"
    if tok.lower.endswith("s") and (core[:-1] in L.given or core[:-1] in L.bible):
        return "given"
    if _derived(core, L):
        return "term"
    return "unknown"


def _derived(core: str, L: Lists) -> bool:
    """'Philippian', 'Methodism', 'Corinthian': built on a listed place or term."""
    for cut in range(len(core) - 1, 4, -1):
        stem = core[:cut]
        if stem in L.places or stem in L.terms or (stem in L.bible and stem not in L.given):
            return True
    return False


def _is_title(tok: Tok) -> bool:
    if tok.lower.rstrip(".") not in TITLES:
        return False
    return tok.cap or tok.lower.rstrip(".") in LOWER_TITLES


def _mark_candidates(toks: list[Tok], L: Lists, config: Config) -> None:
    for i, tok in enumerate(toks):
        if tok.keep or not tok.core:
            continue
        kind = _seed_kind(tok, L)
        if kind is None:
            if tok.initials and tok.cap:
                tok.joinable = True
            continue
        if _is_title(tok) and i + 1 < len(toks) and toks[i + 1].cap:
            continue
        given = tok.core in L.given
        cued = _cue_before(toks, i) is not None
        following = toks[i + 1].lower if i + 1 < len(toks) and not tok.breaks_after else ""
        if cued and kind in ("term", "word") and (given or kind == "word" and not _is_word(L.lexicon, tok.lower)):
            tok.seed = True
        elif cued and kind not in ("term", "word"):
            tok.seed = True
        elif kind == "term":
            place_subject = tok.core in L.places and given and following in PLACE_SUBJECT_VERBS
            tok.seed = place_subject
            tok.joinable = given and tok.core not in L.places
        elif kind == "word":
            tok.joinable = not tok.start_of_sentence
        elif tok.start_of_sentence and _is_word(L.lexicon, tok.lower):
            # "Will you...", "Mark my words", "Crystal was addicted...".
            tok.seed = following in SUBJECT_VERBS
            tok.joinable = True
        else:
            tok.seed = True
        if tok.lower in config.block:
            tok.seed = True


def _spans(toks: list[Tok]) -> Iterable[tuple[int, int]]:
    """Runs of name words around at least one seed, cut at punctuation."""
    i = 0
    n = len(toks)
    while i < n:
        if not (toks[i].seed or toks[i].joinable) or toks[i].keep:
            i += 1
            continue
        j = i
        while (
            j + 1 < n
            and not toks[j].breaks_after
            and (toks[j + 1].seed or toks[j + 1].joinable)
            and not toks[j + 1].keep
            and not toks[j + 1].start_of_sentence
        ):
            j += 1
        # A capitalized English word joins a name only beside a known name
        # ("Grace Miller"), not beside an unknown word ("Levine Children's").
        while i <= j and not toks[i].seed and not _beside_name(toks, i, i + 1, j):
            i += 1
        while j >= i and not toks[j].seed and not _beside_name(toks, j, j - 1, j):
            j -= 1
        if i <= j and any(t.seed for t in toks[i : j + 1]):
            yield i, j + 1
        i = max(i, j) + 1


def _beside_name(toks: list[Tok], index: int, neighbor: int, last: int) -> bool:
    if toks[index].initials:
        return True
    if neighbor < 0 or neighbor >= len(toks) or neighbor > last + 1:
        return False
    other = toks[neighbor]
    if not other.seed:
        return False
    if toks[index].core in lists().given:
        return True  # "Joy Patterson": a given name joins any name
    return _seed_kind(other, lists()) in ("given", "major", "bible", "public")


def _cue_before(toks: list[Tok], start: int) -> str | None:
    """'title', 'relation' or 'verb' when the words before the span mark a living person."""
    if start == 0:
        return None
    before = toks[start - 1]
    if _is_title(before) and not before.breaks_after:
        return "title"
    # my/our [fillers] <relation> [,] NAME
    j = start - 1
    if toks[j].lower in RELATIONS:
        k = j - 1
        steps = 0
        while k >= 0 and steps < 4 and _filler(toks[k]) and not toks[k].breaks_after:
            k -= 1
            steps += 1
        if k >= 0 and toks[k].lower in POSSESSORS and not toks[k].breaks_after:
            return "relation"
        if toks[j].lower in {"baby", "grandbaby"}:
            return "relation"
    lowers = [t.lower for t in toks[max(0, start - 3) : start]]
    for cue in CUES:
        if tuple(lowers[-len(cue) :]) == cue and not toks[start - 1].breaks_after:
            return "verb"
    # "the Morrison family", "the Hendersons" are handled by the seed itself.
    return None


def _filler(tok: Tok) -> bool:
    possessive = tok.tail[:2].replace("’", "'") == "'s"
    return tok.lower in FILLERS or (possessive and tok.lower + "'s" in FILLERS)


def _inherited_cue(toks: list[Tok], start: int) -> str | None:
    """'pray for Tom and Debbie': the cue reaches across 'and' and commas."""
    k = start - 1
    if k >= 0 and toks[k].lower in JOINERS:
        k -= 1
    elif k >= 0 and toks[k].breaks_after and toks[k].redact:
        pass
    else:
        return None
    if k >= 0 and toks[k].lower in {"mrs", "mr", "ms"} and _is_title(toks[k]):
        return "title"
    if k >= 0 and toks[k].redact and getattr(toks[k], "_cued", False):
        return "verb"
    return None


def _context(toks: list[Tok], start: int, end: int, L: Lists) -> tuple[int, int]:
    """(private, scripture) evidence counts in the sentence around the span."""
    lo = start
    while lo > 0 and start - lo < CONTEXT_SPAN and not toks[lo].start_of_sentence:
        lo -= 1
    hi = end
    while hi < len(toks) and hi - end < CONTEXT_SPAN and not toks[hi].start_of_sentence:
        hi += 1
    private = scripture = 0
    for index in list(range(lo, start)) + list(range(end, hi)):
        tok = toks[index]
        if tok.lower in PRIVATE_CONTEXT:
            private += 1
        if tok.lower in BIBLE_CONTEXT:
            scripture += 1
        elif tok.cap and not tok.start_of_sentence:
            kind = _seed_kind(tok, L)
            if tok.keep or kind in ("bible", "public") or (kind == "major" and tok.core not in L.given):
                scripture += 1
            elif kind == "major":
                scripture += 1
    if start > 0 and toks[start - 1].lower in {"like", "as"}:
        scripture += 2
    if end < len(toks) and (toks[end].lower in NUMBER_WORDS or toks[end].core == "" and toks[end].tail[:1].isdigit()):
        scripture += 3
    return private, scripture


def _decide_span(toks: list[Tok], start: int, end: int, L: Lists, config: Config) -> None:
    span = toks[start:end]
    parts = tuple(part for tok in span for part in tok.phrase_parts)
    if any(part in config.block for part in parts):
        _hide(span, cued=True)
        return
    titled = start > 0 and _is_title(toks[start - 1])
    title_parts = (toks[start - 1].lower.rstrip("."),) + parts if titled else parts
    if parts in config.allow or title_parts in config.allow:
        return
    cue = _cue_before(toks, start) or _inherited_cue(toks, start)
    kinds = [_seed_kind(tok, L) for tok in span if not tok.initials]
    names = [tok for tok in span if not tok.initials]
    if cue in ("title", "relation"):
        _hide(span, cued=True)
        return
    if cue == "verb":
        # "pray for Israel" stays; "pray for John" does not.
        if all(k in ("bible", "term") and tok.core not in L.given for k, tok in zip(kinds, names)):
            return
        _hide(span, cued=True)
        return
    seeds = [(k, tok) for k, tok in zip(kinds, names) if tok.seed]
    if kinds.count("word") >= 2:
        return  # "The Normal Christian Life", "Vacation Bible School"
    if len(names) >= 2:
        if all(k in ("bible", "major", "term") for k in kinds):
            if _leans_private(toks, start, end, L, margin=1):
                _hide(span)
            return
        if all(k == "public" for k in kinds):
            return
        _hide(span)
        return
    if not seeds:
        return
    kind, tok = seeds[0]
    if kind == "bible":
        if tok.core in L.given and not _leans_scripture(toks, start, end, L):
            _hide(span)
        return
    if kind in ("major", "public"):
        if tok.core in L.given and _leans_private(toks, start, end, L, margin=1):
            _hide(span)
        return
    if kind == "given" and tok.core in L.bible and _leans_scripture(toks, start, end, L):
        return
    if kind == "unknown" and len(names) == 1 and _place_like(toks, start, end):
        return
    if kind == "given" and len(names) == 1 and _the_noun(toks, start, end, L):
        return
    _hide(span)


def _the_noun(toks: list[Tok], start: int, end: int, L: Lists) -> bool:
    """'the Bedford jail', 'the Jordan river': a name used as a modifier."""
    if start == 0 or end >= len(toks) or toks[start - 1].lower != "the":
        return False
    after = toks[end]
    return (
        not toks[start].breaks_after
        and not toks[start].tail.startswith(("'", "’"))
        and not after.cap
        and after.lower not in FAMILY_WORDS
        and _is_word(L.lexicon, after.lower)
    )


def _place_like(toks: list[Tok], start: int, end: int) -> bool:
    """'at Flossenburg', 'the Waodani', 'the Bedford jail' (not 'the Hendersons')."""
    if start == 0:
        return False
    before = toks[start - 1].lower
    after = toks[end].lower if end < len(toks) else ""
    if after in FAMILY_WORDS or toks[start].tail.startswith(("'", "’")):
        return False
    if before in LOCATIVES:
        return True
    return before == "the" and not toks[start].lower.endswith("s")


def _leans_private(toks: list[Tok], start: int, end: int, L: Lists, margin: int) -> bool:
    private, scripture = _context(toks, start, end, L)
    return private >= scripture + margin


def _leans_scripture(toks: list[Tok], start: int, end: int, L: Lists) -> bool:
    private, scripture = _context(toks, start, end, L)
    return scripture >= 2 and scripture > private


def _hide(span: list[Tok], cued: bool = False) -> None:
    for tok in span:
        tok.redact = True
        tok._cued = cued  # type: ignore[attr-defined]


def _mark_lowercase(toks: list[Tok], L: Lists, config: Config) -> None:
    """'pray for brenda': a lowercase given name right after a strong cue."""
    for i, tok in enumerate(toks):
        if tok.redact or tok.keep or tok.cap or not tok.core:
            continue
        if tok.lower in config.block:
            tok.redact = True
            continue
        name = tok.core.capitalize()
        if name not in L.given or _is_word(L.lexicon, tok.lower):
            continue
        if _cue_before(toks, i) or _inherited_cue(toks, i):
            tok.redact = True
