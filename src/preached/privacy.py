"""Replace congregants' names in ASR words with ``[name]``.

``redact(words) -> words`` is the W2-YT hook (``preached.youtube.privacy``).
A word is any record that carries ``start``, ``end`` and text: the W2-YT
``Word`` dataclass, a W1-C ``(start, end, word)`` tuple or list, or a dict with
``"text"`` or ``"word"``. The result has the same records in the same order
with the same times; only a name's letters change ("Jane's," -> "[name]'s,").
Words inside a configured drop window are removed. When nothing changes the
input list itself is returned.

Rules, no model. Whisper capitalizes names, so the evidence is the casing,
the words around a name, and lists built by ``scripts/build_privacy_lists.py``
(SSA given names, KJV and WEB proper nouns, an English word list) plus four
hand-written lists in ``privacy_data/`` (major Bible figures, public and
historical people, places, capitalized non-names).

1. A listed public phrase ("John Wesley", "C. S. Lewis") is kept, and its
   first name is kept when it comes back alone nearby ("John preached").
2. Capitalized name words next to each other form a span. Two or more words
   are a full name and are redacted unless every word is a Bible name
   ("Simon Peter") or a public name.
3. A strong cue before a span makes it private even if it is a Bible name:
   a title ("Sister", "Mr.", "Pastor"), "my/our <relative>", a prayer or
   announcement verb ("pray for", "welcome", "thanks to", "baptizing"), or
   "a young lady <name>". "pray for Israel" stays.
4. A weak cue ("a man named", "his wife") makes it private unless public or
   Bible names are nearby ("Moody's teacher, a man named Edward Kimball").
5. A lone name: a given name is redacted. A major Bible figure (John, Mary)
   or a public surname (Lewis, Graham) is kept, unless a private event
   follows ("John's surgery") or it is joined by "and" to a private name
   ("Peter and Brenda"). A rarer Bible name that is also a given name
   (Jason, Chloe) is kept only when the sentence reads as scripture.
6. A capitalized word on no list and not an English word is a surname and
   is redacted, unless it reads as a place ("at Flossenburg").

Lowercase names ("pray for brenda") are caught only right after a strong cue.

Per-library settings come from a TOML file (``privacy.example.toml``), passed
as ``config=`` or named by the ``PREACHED_PRIVACY`` environment variable.
"""

from __future__ import annotations

import dataclasses
import gzip
import os
import re
import tomllib
import unicodedata
from dataclasses import dataclass
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
    "pastor", "stepson", "stepdaughter", "sweetheart", "classmate", "foreman", "sister-in-law",
    "brother-in-law", "mother-in-law", "father-in-law", "son-in-law", "daughter-in-law",
}
# "a young lady Faith", "this fella Ronnie"
APPOSITIVES = {"lady", "man", "woman", "fella", "fellow", "guy", "gentleman", "kid", "teenager", "girl", "boy", "couple"}
STRONG_POSSESSORS = {"my", "our", "me"}
WEAK_POSSESSORS = {"his", "her", "their", "your"}
FILLERS = {
    "sweet", "little", "dear", "precious", "beloved", "good", "old", "own", "best", "oldest",
    "youngest", "late", "baby", "big", "new", "first", "two", "three", "grown", "adopted",
    "dearest", "lifelong", "missionary", "young", "older", "younger", "sweetest", "wife's",
    "husband's", "pastor's", "mom's", "dad's", "mother's", "father's", "sister's",
    "brother's", "friend's", "cousin's", "neighbor's", "son's", "daughter's",
}
# Lowercase word sequences that, right before a name, mark a living person.
CUES = [
    ("pray", "for"), ("praying", "for"), ("prayers", "for"), ("prayer", "for"), ("pray", "with"),
    ("lift", "up"), ("lifting", "up"), ("remember",), ("remembering",), ("welcome",),
    ("welcoming",), ("congratulations", "to"), ("congratulations",), ("congrats", "to"),
    ("birthday", "to"), ("birthday",), ("anniversary", "to"), ("anniversary",),
    ("thank", "you", "to"), ("thanks", "to"), ("thank",), ("thanking",), ("out", "to"),
    ("talk", "to"), ("talk", "with"), ("talked", "to"), ("talked", "with"), ("see",),
    ("call",), ("text",), ("email",), ("contact",), ("meet",), ("name", "is"),
    ("name", "was"), ("sitting", "with"), ("hand",), ("baptized",), ("baptizing",),
    ("baptize",), ("dedicating",), ("commissioning",), ("ordaining",), ("honoring",),
    ("recognizing",), ("celebrating",), ("visit",), ("visiting",), ("hug",), ("me", "and"),
    ("condolences", "to"), ("sympathy", "to"), ("check", "on"), ("checking", "on"),
    ("keep",), ("keeping",),
]
WEAK_CUES = [("named",), ("called",), ("by", "the", "name", "of")]
# After a name: "Peter's surgery", "John passed away".
PRIVATE_AFTER_POSSESSIVE = {
    "surgery", "funeral", "visitation", "diagnosis", "chemo", "biopsy", "treatment",
    "birthday", "anniversary", "wedding", "graduation", "retirement", "recovery", "rehab",
    "service", "obituary", "condition", "test", "scan", "results", "kids", "grandkids",
}
PRIVATE_PREDICATES = [
    ("passed", "away"), ("had", "surgery"), ("has", "surgery"), ("is", "in", "the", "hospital"),
    ("is", "in", "hospital"), ("asked", "us"), ("asked", "me"), ("called", "me"), ("texted",),
    ("emailed",), ("is", "having", "surgery"), ("starts", "chemo"), ("is", "home"),
    ("is", "doing"), ("got", "saved"), ("got", "baptized"), ("is", "recovering"),
]
SCRIPTURE_CONTEXT = {
    "apostle", "apostles", "prophet", "prophets", "prophetess", "disciple", "disciples", "king",
    "queen", "lord", "jesus", "christ", "god", "scripture", "scriptures", "verse", "verses",
    "chapter", "book", "gospel", "epistle", "letter", "letters", "temple", "israel",
    "israelites", "egypt", "jerusalem", "galilee", "pharaoh", "priest", "priests", "angel",
    "angels", "tomb", "cross", "crucified", "pharisees", "unto", "thee", "thou", "thy", "ye",
    "begat", "tribe", "wilderness", "bible", "testament", "psalm", "prophecy", "miracle",
    "parable", "ark", "preached", "sermon", "sermons", "century", "revival", "hymn", "hymns",
    "reformer", "reformation", "wrote", "writes", "written", "puritan", "messiah", "gentiles",
    "jews", "synagogue", "multitude", "pharisee", "ancient", "covenant", "sacrifice", "altar",
    "paul", "acts", "apostle's", "church", "churches", "macedonia", "rome", "corinth",
    "ephesus", "philippi", "thessalonica", "galatia", "colossae", "antioch", "athens",
}
PRIVATE_CONTEXT = {
    "hospital", "surgery", "chemo", "cancer", "doctor", "doctors", "biopsy", "diagnosis",
    "diagnosed", "rehab", "icu", "sick", "visitation", "funeral", "birthday", "anniversary",
    "pregnant", "expecting", "grandbaby", "grandkids", "deployed", "job", "office", "choir",
    "youth", "nursery", "kitchen", "signup", "welcome", "thanks", "congratulations", "text",
    "email", "meals", "cards", "praying", "y'all", "tonight", "yesterday", "camp", "school",
    "college", "nursing", "truck", "car", "wreck", "phone", "wedding", "retiring", "retired",
    "buddy", "neighbor", "boss", "potluck", "volunteer", "cookout", "breakfast", "overdosed",
}
NUMBER_WORDS = {
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
    "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
    "chapter", "chapters", "verse", "verses",
}
BOOK_OF = {("book", "of"), ("gospel", "of"), ("letter", "to"), ("epistle", "to"), ("epistle", "of"), ("prophet",), ("apostle",), ("king",), ("queen",)}
JOINERS = {"and", "&", "or"}
CONNECTORS = {"of", "the", "in", "an", "a", "for", "from"}
# After a name that is also an English word ("Crystal", "Will", "Joy"),
# these make it the subject of a story.
SUBJECT_VERBS = {
    "told", "said", "says", "came", "comes", "asked", "asks", "wanted", "called", "calls",
    "gave", "went", "texted", "prayed", "shared", "brought", "walked", "sang", "cried",
    "looked", "stood", "leads", "led", "laughed", "got", "was", "is", "has", "had", "and",
    "just", "wants", "needs", "loves", "lost", "passed", "started", "starts", "turned",
    "turns", "made", "makes", "drove", "works", "worked", "left", "used", "she", "he",
    "who", "who's", "she's", "he's", "texted", "emailed", "won't", "can't", "didn't",
}
# Same, for place names that are also given names ("Austin came up to me").
AGENT_VERBS = SUBJECT_VERBS - {"was", "is", "has", "had", "and", "just", "used", "who", "won't", "can't", "didn't"}
# Same, for virtue names ("Joy asked us", not "Faith comes by hearing").
HUMAN_VERBS = {"told", "asked", "texted", "emailed", "shared", "wanted", "laughed", "cried", "drove", "sang", "brought", "works", "worked"}
# Capitalized words for God that are also given names in the SSA list.
DIVINE = {"God", "Lord", "Jesus", "Christ", "Spirit", "Father", "Son", "Messiah", "Savior", "Saviour", "Emmanuel", "Immanuel", "Holy", "Trinity"}
# A lone unknown capitalized word after these is a place or thing ("at Flossenburg").
LOCATIVES = {"at", "in", "from", "near", "into", "across", "outside", "through", "of", "to", "toward", "towards", "around"}
FAMILY_WORDS = {"family", "families", "household", "kids", "clan", "boys", "girls", "crew"}
# Closed-class words: never names, and never the noun in "the Bedford jail".
FUNCTION_WORDS = {
    "the", "a", "an", "my", "our", "his", "her", "their", "your", "and", "but", "so", "as",
    "at", "in", "on", "to", "for", "of", "if", "or", "said", "son", "sir", "baby", "boy",
    "male", "lady", "pa", "om", "we", "he", "she", "they", "it", "i", "you", "is", "are",
    "was", "were", "be", "been", "have", "has", "had", "do", "did", "who", "that", "this",
    "these", "those", "with", "from", "by", "not", "no", "would", "can", "could",
    "just", "all", "when", "then", "there", "here", "what", "which", "about", "up", "out",
    "they're", "he's", "she's", "it's", "that's", "we're", "i'm",
}
PLACE_PREFIXES = {"Fort", "Ft", "Camp", "Lake", "Mount", "Mt", "Port", "Cape", "Saint", "St", "San", "Santa"}
PLACE_SUFFIXES = {
    "County", "Street", "Road", "Avenue", "Hospital", "Church", "School", "University",
    "College", "Elementary", "Academy", "Baptist", "Methodist", "Presbyterian", "Chapel",
    "Center", "Memorial", "Boulevard", "Highway", "Drive", "Funeral", "Lake", "River",
}
CONTEXT_SPAN = 12
NEARBY_SPAN = 20
BACKREF_SPAN = 80
SENTENCE_END = re.compile(r"[.?!][\"'”’)\]]*$")
ABBREVIATION = re.compile(r"^(?:mr|mrs|ms|dr|st|jr|sr|rev|sgt|capt|prof|[a-z])\.$|^(?:[a-z]\.)+$", re.I)
LETTER = r"[^\W\d_]"
WORD = re.compile(rf"^(?P<lead>[^\w]*)(?P<core>{LETTER}(?:(?:{LETTER}|['’.-])*{LETTER})?)(?P<tail>[^\w]*)$")
INITIALS = re.compile(r"^(?:[A-Z]\.)+$|^[A-Z]$")


def fold(text: str) -> str:
    """'Müller' -> 'Muller', 'à' -> 'a', curly apostrophes -> straight."""
    text = unicodedata.normalize("NFKD", text.replace("’", "'"))
    return "".join(ch for ch in text if not unicodedata.combining(ch))


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


def _lines(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def _phrase(text: str) -> tuple[str, ...]:
    """'C. S. Lewis' and 'C.S. Lewis' -> ('c', 's', 'lewis')."""
    parts: list[str] = []
    for piece in fold(text).split():
        if INITIALS.match(piece.rstrip(",;")):
            parts.extend(letter.lower() for letter in piece if letter.isalpha())
        else:
            parts.append(piece.strip(".,;:!?\"'()").lower())
    return tuple(part for part in parts if part)


@lru_cache(maxsize=1)
def lists() -> Lists:
    """Load the name lists once per process (about 15 ms)."""
    public_lines = _lines(DATA / "public_names.txt")
    phrases = frozenset(_phrase(line) for line in public_lines if len(_phrase(line)) > 1)
    with gzip.open(DATA / "lexicon.txt.gz", "rt", encoding="utf-8") as handle:
        lexicon = frozenset(handle.read().split())
    return Lists(
        given=frozenset(_lines(DATA / "given_names.txt")),
        bible=frozenset(line.split("\t", 1)[0] for line in _lines(DATA / "bible_names.txt")),
        bible_major=frozenset(w for line in _lines(DATA / "bible_major.txt") for w in line.split()),
        public_single=frozenset(fold(line) for line in public_lines if len(_phrase(line)) == 1),
        public_phrases=phrases,
        places=frozenset(w for line in _lines(DATA / "places.txt") for w in line.split()),
        terms=frozenset(w for line in _lines(DATA / "terms.txt") for w in line.split()),
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
        return cls(allow=allow, block=block, drop=tuple(drop), token=str(data.get("token", TOKEN)))


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


def _time(word: Any, key: str, index: int) -> float:
    if isinstance(word, dict):
        return float(word[key])
    if isinstance(word, (tuple, list)):
        return float(word[index])
    return float(getattr(word, key))


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


# ---------------------------------------------------------------- redact


def redact(words: list, *, config: Config | None = None, source: str | None = None) -> list:
    """privacy.redact(words) -> words, with congregant names replaced.

    ``source`` is the video or sermon id that ``drop`` windows name; windows
    without a ``source`` apply to every input.
    """
    config = default_config() if config is None else config
    kept = [w for w in words if not _dropped(w, config, source)] if config.drop else words
    texts = [_text(word) for word in kept]
    hide = decide(texts, config)
    if not any(hide):
        return kept
    return [
        _with_text(word, _mask(text, config.token)) if flag else word
        for word, text, flag in zip(kept, texts, hide)
    ]


def redact_text(text: str, config: Config | None = None) -> str:
    """Plain-text convenience: split on spaces, redact, join."""
    config = config or Config()
    texts = text.split()
    return " ".join(_mask(t, config.token) if flag else t for t, flag in zip(texts, decide(texts, config)))


def _dropped(word: Any, config: Config, source: str | None) -> bool:
    middle = (_time(word, "start", 0) + _time(word, "end", 1)) / 2
    return any(
        (window is None or window == source) and start <= middle < end
        for window, start, end in config.drop
    )


def _mask(text: str, token: str) -> str:
    match = WORD.match(text.strip())
    if not match:
        return token
    core, tail = match["core"], match["tail"]
    if re.search(r"['’]s$", core):
        tail = core[-2:] + tail
    return f"{match['lead']}{token}{tail}"


def decide(texts: Sequence[str], config: Config | None = None) -> list[bool]:
    """One flag per word: True when the word is (part of) a private name."""
    return _Pass(texts, config or Config()).run()


@dataclass
class Tok:
    lead: str = ""
    core: str = ""  # as written, minus a possessive 's
    tail: str = ""
    name: str = ""  # accent-folded core, the form the lists use
    lower: str = ""
    start_of_sentence: bool = False
    cap: bool = False
    initials: bool = False
    parts: tuple[str, ...] = ()
    kind: str | None = None
    keep: bool = False  # part of a kept public phrase
    seed: bool = False  # starts a name span
    joinable: bool = False  # may extend a span
    redact: bool = False
    by_default: bool = False  # redacted as a plain given or unknown name

    @property
    def possessive(self) -> bool:
        return self.tail[:2] in ("'s", "’s") or self.tail[:1] in ("'", "’") and self.lower.endswith("s")

    @property
    def breaks_after(self) -> bool:
        """Punctuation after the word ends a name ('C.' and 'St.' do not)."""
        if self.initials or ABBREVIATION.match(self.core + self.tail[:1]):
            return False
        rest = self.tail[2:] if self.possessive else self.tail
        return any(ch in rest for ch in ",.;:!?()\"”")


class _Pass:
    def __init__(self, texts: Sequence[str], config: Config) -> None:
        self.L = lists()
        self.config = config
        self.toks = self._tokens(texts)
        self.backrefs: list[tuple[str, int]] = []

    # ------------------------------------------------------------ setup

    def _tokens(self, texts: Sequence[str]) -> list[Tok]:
        toks = []
        previous = ""
        for index, text in enumerate(texts):
            text = text.strip()
            start = index == 0 or (bool(SENTENCE_END.search(previous)) and not ABBREVIATION.match(previous))
            previous = text
            match = WORD.match(text)
            if not match:
                toks.append(Tok(tail=text, start_of_sentence=start))
                continue
            core, tail = match["core"], match["tail"]
            if re.search(r"['’]s$", core):
                core, tail = core[:-2], core[-2:] + tail
            name = fold(core)
            tok = Tok(match["lead"], core, tail, name, name.lower(), start, core[0].isupper())
            tok.initials = bool(INITIALS.match(name + ("." if tail.startswith(".") else "")))
            tok.parts = _phrase(name)
            tok.kind = self._kind(tok)
            toks.append(tok)
        return toks

    def _is_word(self, lower: str) -> bool:
        lexicon = self.L.lexicon
        if lower in lexicon or lower in FUNCTION_WORDS:
            return True
        if "'" in lower:
            head = lower.split("'", 1)[0]
            return head in lexicon or head in FUNCTION_WORDS
        return any(lower.endswith(s) and lower[: -len(s)] in lexicon for s in ("s", "es"))

    def _kind(self, tok: Tok) -> str | None:
        """What a capitalized word looks like on its own, before context."""
        L, name = self.L, tok.name
        if not tok.cap or tok.initials or not name:
            return None
        if tok.lower in FUNCTION_WORDS:
            return "word"
        if name in L.terms or name in L.places:
            return "term"
        if name in L.public_single:
            return "public"
        if name in L.bible_major:
            return "major"
        if name in L.bible and name not in L.given:
            return "bible"
        if name in L.given:
            return "given"
        if name in L.bible:
            return "bible"
        if self._is_word(tok.lower):
            return "word"
        singular = name[:-1] if name.endswith("s") else ""
        if singular and (singular in L.terms or singular in L.places or singular in L.public_single):
            return "term"
        if singular and (singular in L.given or singular in L.bible):
            return "given"
        if self._derived(name):
            return "term"
        return "unknown"

    def _derived(self, name: str) -> bool:
        """'Philippian', 'Corinthian': built on a listed place or Bible name."""
        L = self.L
        for cut in range(len(name) - 1, 4, -1):
            stem = name[:cut]
            if stem in L.places or stem in L.terms or (stem in L.bible and stem not in L.given):
                return True
        return False

    def _given(self, tok: Tok) -> bool:
        return tok.name in self.L.given or (tok.name.endswith("s") and tok.name[:-1] in self.L.given)

    def _is_title(self, tok: Tok) -> bool:
        lower = tok.lower.rstrip(".")
        return lower in TITLES and (tok.cap or lower in LOWER_TITLES)

    # ------------------------------------------------------------ run

    def run(self) -> list[bool]:
        self._mark_phrases()
        self._mark_candidates()
        for start, end in list(self._spans()):
            self._decide(start, end)
        self._coordinate()
        self._lowercase()
        return [tok.redact for tok in self.toks]

    def _mark_phrases(self) -> None:
        """Keep listed public names and configured allowed names, longest first."""
        toks, L, config = self.toks, self.L, self.config
        phrases = L.public_phrases | {p for p in config.allow if len(p) > 1}
        longest = max(L.longest_phrase, max((len(p) for p in config.allow), default=1))
        i = 0
        while i < len(toks):
            if not toks[i].cap:
                i += 1
                continue
            matched = 0
            for length in range(min(longest * 2, len(toks) - i), 1, -1):
                window = toks[i : i + length]
                parts = tuple(part for tok in window for part in tok.parts)
                if parts in phrases and not any(t.breaks_after for t in window[:-1]):
                    matched = length
                    break
            if matched:
                window = toks[i : i + matched]
                after = toks[i + matched] if i + matched < len(toks) else None
                followed = (
                    after is not None
                    and not window[-1].breaks_after
                    and not window[-1].possessive
                    and after.kind in ("given", "unknown")
                )
                titled = i > 0 and self._is_title(toks[i - 1]) and toks[i - 1].lower not in {"saint", "st"}
                blocked = any(part in config.block for t in window for part in t.parts)
                if not (followed or titled or blocked):
                    for tok in window:
                        tok.keep = True
                    first = next(
                        (t for t in window if not t.initials and not self._is_title(t) and t.lower not in {"st", "saint"}),
                        None,
                    )
                    if first is not None and (first is not window[-1] or window[0] is not first):
                        self.backrefs.append((first.name, i))
                    i += matched
                    continue
            i += 1

    def _mark_candidates(self) -> None:
        toks, L = self.toks, self.L
        for i, tok in enumerate(toks):
            if tok.keep or tok.kind is None:
                if tok.initials and tok.cap and not tok.keep:
                    tok.joinable = True
                continue
            if self._is_title(tok) and i + 1 < len(toks) and toks[i + 1].cap:
                continue
            kind, given = tok.kind, self._given(tok)
            cue = self._cue_before(i)
            following = toks[i + 1].lower if i + 1 < len(toks) and not tok.breaks_after else ""
            if cue in ("title", "relation", "verb", "appositive", "family") and tok.name not in DIVINE:
                tok.seed = kind not in ("term", "word") or given or kind == "word" and self._family(i)
                tok.joinable = True
            elif kind == "term":
                verbs = AGENT_VERBS if tok.name in L.places else HUMAN_VERBS
                tok.seed = given and tok.name not in DIVINE and following in verbs
                tok.joinable = given and tok.name not in L.places
            elif kind == "word":
                tok.seed = self._family(i)
                tok.joinable = not tok.start_of_sentence
            elif kind == "given" and self._is_word(tok.lower):
                # "Will you...", "Rose early" vs "Crystal was addicted", "Hunter and the youth".
                tok.seed = (not tok.start_of_sentence or following in SUBJECT_VERBS) and not self._title_case_run(i)
                tok.joinable = True
            elif kind == "major" and tok.start_of_sentence and self._is_word(tok.lower):
                tok.seed = following in SUBJECT_VERBS  # "Mark my words"
                tok.joinable = True
            else:
                tok.seed = True
            if tok.lower in self.config.block:
                tok.seed = True

    def _title_case_run(self, i: int) -> bool:
        """'The Normal Christian Life', 'Sinners in the Hands of an Angry God', 'Rock of Ages'."""
        toks = self.toks
        caps = 1
        joined = False
        for step in (-1, 1):
            j = i + step
            while 0 <= j < len(toks) and not toks[j - 1 if step == 1 else j].breaks_after:
                if toks[j].cap and toks[j].kind in ("word", "term"):
                    caps += 1
                elif toks[j].lower in CONNECTORS and not toks[j].cap:
                    joined = True
                else:
                    break
                j += step
        return caps >= 3 or (joined and caps >= 2)

    def _family(self, i: int) -> bool:
        """'the Hendersons', 'the Bakers', 'the Morrison family'."""
        toks = self.toks
        tok = toks[i]
        if i == 0 or toks[i - 1].lower != "the" or tok.kind == "term" or self._title_case_run(i):
            return False
        plural = tok.lower.endswith("s") and not tok.possessive
        after = toks[i + 1].lower if i + 1 < len(toks) and not tok.breaks_after else ""
        return plural or after in FAMILY_WORDS

    def _spans(self) -> Iterable[tuple[int, int]]:
        """Runs of name words around at least one seed, cut at punctuation."""
        toks = self.toks
        n = len(toks)
        i = 0
        while i < n:
            if toks[i].keep or not (toks[i].seed or toks[i].joinable):
                i += 1
                continue
            j = i
            while (
                j + 1 < n
                and not toks[j].breaks_after
                and not toks[j].possessive
                and (toks[j + 1].seed or toks[j + 1].joinable)
                and not toks[j + 1].keep
                and not toks[j + 1].start_of_sentence
                and toks[j + 1].cap
            ):
                j += 1
            # A capitalized English word joins a name only beside a known name
            # ("Grace Miller"), not beside an unknown word ("Levine Children's").
            while i <= j and not toks[i].seed and not self._beside_name(i, i + 1, j):
                i += 1
            while j >= i and not toks[j].seed and not self._beside_name(j, j - 1, j):
                j -= 1
            if i <= j and any(t.seed for t in toks[i : j + 1]):
                yield i, j + 1
            i = max(i, j) + 1

    def _beside_name(self, index: int, neighbor: int, last: int) -> bool:
        toks = self.toks
        if toks[index].initials:
            return True
        if neighbor < 0 or neighbor >= len(toks) or neighbor > last:
            return False
        other = toks[neighbor]
        if not other.seed:
            return False
        if self._given(toks[index]) or self._given(other):
            return True  # "Joy Patterson", "Faith Dobbins"
        return other.kind in ("major", "bible", "public")

    # ------------------------------------------------------------ cues

    def _cue_before(self, start: int, depth: int = 0) -> str | None:
        """Why the words before position ``start`` mark a living person, if they do."""
        toks = self.toks
        if start == 0:
            return None
        before = toks[start - 1]
        if before.breaks_after and not (before.lower in RELATIONS and before.tail.startswith(",")):
            return self._listed_cue(start, depth)
        if self._is_title(before):
            return "title"
        lowers = [t.lower for t in toks[max(0, start - 4) : start]]
        if lowers[-1:] == ["the"] and start >= 2:
            cue = self._cue_before(start - 1, depth + 1) if depth < 3 else None
            return "family" if cue in ("verb", "family") and self._family(start) else None
        if before.lower in RELATIONS:
            k = start - 2
            steps = 0
            while k >= 0 and steps < 4 and self._filler(toks[k]) and not toks[k].breaks_after:
                k -= 1
                steps += 1
            if k >= 0 and not toks[k].breaks_after:
                if toks[k].lower in STRONG_POSSESSORS:
                    return "relation"
                if toks[k].lower in WEAK_POSSESSORS:
                    return "weak"
            if before.lower in {"baby", "grandbaby"}:
                return "relation"
            if self._cue_before(start - 1, depth + 1) == "verb" if depth < 3 else False:
                return "relation"  # "pray for brother Daniel"
        if before.lower in APPOSITIVES and start >= 2:
            k = start - 2
            while k >= 0 and toks[k].lower in FILLERS:
                k -= 1
            if k >= 0 and toks[k].lower in {"a", "this", "that", "one"}:
                return "appositive"
        for cue in CUES:
            if tuple(lowers[-len(cue) :]) == cue:
                return "verb"
        for cue in WEAK_CUES:
            if tuple(lowers[-len(cue) :]) == cue:
                return "weak"
        if before.lower in JOINERS:
            return self._listed_cue(start, depth)
        return None

    def _listed_cue(self, start: int, depth: int) -> str | None:
        """'pray for Tom and Debbie', 'thanks to Linda, Gary, and Ron'."""
        toks = self.toks
        if depth >= 4:
            return None
        k = start - 1
        if toks[k].lower in JOINERS:
            k -= 1
        if k < 0 or not (toks[k].breaks_after or toks[k].lower not in JOINERS):
            return None
        if self._is_title(toks[k]) and toks[k].lower.rstrip(".") in {"mr", "mrs", "ms"}:
            return "title"  # "Mr. and Mrs. Whitfield"
        if not (toks[k].cap or toks[k].tail.startswith(",")):
            return None
        # walk back to the start of the previous name
        r = k
        while r > 0 and toks[r - 1].cap and not toks[r - 1].breaks_after:
            r -= 1
        if r == k and not toks[k].cap:
            return None
        cue = self._cue_before(r, depth + 1)
        return cue if cue in ("verb", "title", "relation", "weak") else None

    def _filler(self, tok: Tok) -> bool:
        return tok.lower in FILLERS or (tok.possessive and tok.lower + "'s" in FILLERS)

    def _private_after(self, end: int) -> bool:
        toks = self.toks
        last = toks[end - 1]
        if end >= len(toks):
            return False
        if last.possessive and toks[end].lower in PRIVATE_AFTER_POSSESSIVE:
            return True
        if last.breaks_after:
            return False
        lowers = tuple(t.lower for t in toks[end : end + 4])
        return any(lowers[: len(p)] == p for p in PRIVATE_PREDICATES)

    def _book_reference(self, start: int, end: int) -> bool:
        """'John 3:16', 'Daniel chapter six', 'the book of Ruth', 'the prophet Nathan'."""
        toks = self.toks
        if end < len(toks) and not toks[end - 1].breaks_after:
            after = toks[end]
            if after.lower in NUMBER_WORDS or (not after.core and after.tail[:1].isdigit()):
                return True
        lowers = tuple(t.lower for t in toks[max(0, start - 2) : start])
        return any(lowers[-len(p) :] == p for p in BOOK_OF)

    def _nearby_public(self, start: int, end: int) -> bool:
        """Public or Bible names within NEARBY_SPAN words: the story is history."""
        toks = self.toks
        lo, hi = max(0, start - NEARBY_SPAN), min(len(toks), end + NEARBY_SPAN)
        for index in list(range(lo, start)) + list(range(end, hi)):
            tok = toks[index]
            if tok.keep or (tok.kind in ("bible", "public", "major") and not tok.redact):
                if tok.kind == "major" and self._given(tok) and tok.lower not in {"jesus", "christ"}:
                    continue
                return True
        return False

    def _backref(self, tok: Tok, index: int) -> bool:
        return any(name == tok.name and abs(at - index) <= BACKREF_SPAN for name, at in self.backrefs)

    def _leans_scripture(self, start: int, end: int) -> bool:
        toks = self.toks
        lo = start
        while lo > 0 and start - lo < CONTEXT_SPAN and not toks[lo].start_of_sentence:
            lo -= 1
        hi = end
        while hi < len(toks) and hi - end < CONTEXT_SPAN and not toks[hi].start_of_sentence:
            hi += 1
        private = scripture = 0
        for index in list(range(lo, start)) + list(range(end, hi)):
            tok = toks[index]
            private += tok.lower in PRIVATE_CONTEXT
            scripture += tok.lower in SCRIPTURE_CONTEXT
            if tok.cap and not tok.start_of_sentence and (tok.keep or tok.kind in ("bible", "public", "major")):
                scripture += 1
        return scripture >= 2 and scripture > private

    # ------------------------------------------------------------ decide

    def _decide(self, start: int, end: int) -> None:
        toks, L, config = self.toks, self.L, self.config
        span = toks[start:end]
        names = [t for t in span if not t.initials]
        parts = tuple(part for tok in span for part in tok.parts)
        if any(part in config.block for part in parts):
            return self._hide(span)
        titled = start > 0 and self._is_title(toks[start - 1])
        if parts in config.allow or (titled and (toks[start - 1].lower.rstrip("."),) + parts in config.allow):
            return
        if not names:
            return
        if self._place_name(start, end):
            return
        cue = self._cue_before(start)
        kinds = [t.kind for t in names]
        if cue in ("title", "relation", "appositive", "family"):
            return self._hide(span)
        if cue == "verb":
            if all(k in ("bible", "term", "public") and not self._given(t) for k, t in zip(kinds, names)):
                return  # "pray for Israel"
            if self._book_reference(start, end):
                return
            return self._hide(span)
        if cue == "weak":
            if len(names) == 1 and kinds[0] in ("major", "bible", "public"):
                return  # "his brother Andrew", "his wife Elisabeth"
            if self._nearby_public(start, end):
                return  # "Moody's teacher was a man named Edward Kimball"
            return self._hide(span)
        if len(names) >= 2:
            if all(k in ("bible", "major", "term") or t.name in L.bible for k, t in zip(kinds, names)):
                return  # "Simon Peter", "Mary Magdalene"
            if all(k == "public" for k in kinds):
                return
            if kinds.count("word") + kinds.count("term") >= 2:
                return  # "Vacation Bible School"
            return self._hide(span, by_default=True)
        tok, kind = names[0], kinds[0]
        if not tok.seed:
            return
        if self._backref(tok, start) or self._book_reference(start, end):
            return
        given = self._given(tok)
        if kind == "term":
            return self._hide(span) if given else None  # seeded by "Austin came..."
        if kind in ("major", "public"):
            if given and self._private_after(end):
                return self._hide(span)
            return
        if kind == "bible":
            if given and not self._leans_scripture(start, end):
                return self._hide(span, by_default=True)
            return
        if kind == "given" and tok.name in L.bible and self._leans_scripture(start, end):
            return
        if kind == "given" and self._the_noun(start, end):
            return
        if kind == "unknown" and self._place_like(start, end):
            return
        if kind == "word" and not self._family(start):
            return
        self._hide(span, by_default=True)

    def _place_name(self, start: int, end: int) -> bool:
        """'Fort Liberty', 'Levine Children's Hospital', 'Lake Junaluska'."""
        toks = self.toks
        before = toks[start - 1] if start > 0 else None
        if before is not None and before.cap and before.name in PLACE_PREFIXES and not before.breaks_after:
            return True
        k = end
        while k < len(toks) and k < end + 2 and toks[k].cap and not toks[k - 1].breaks_after:
            if toks[k].name in PLACE_SUFFIXES:
                return True
            k += 1
        return False

    def _the_noun(self, start: int, end: int) -> bool:
        """'the Bedford jail', 'the Jordan river': a name used as a modifier."""
        toks = self.toks
        if start == 0 or end >= len(toks) or toks[start - 1].lower != "the":
            return False
        tok, after = toks[start], toks[end]
        return (
            not tok.breaks_after
            and not tok.possessive
            and not tok.lower.endswith("s")
            and not after.cap
            and after.lower not in FAMILY_WORDS
            and after.lower not in FUNCTION_WORDS
            and after.lower not in SUBJECT_VERBS
            and self._is_word(after.lower)
        )

    def _place_like(self, start: int, end: int) -> bool:
        """'at Flossenburg', 'the Waodani' (not 'the Hendersons')."""
        toks = self.toks
        if start == 0:
            return False
        tok = toks[start]
        after = toks[end].lower if end < len(toks) else ""
        if after in FAMILY_WORDS or tok.possessive or self._family(start):
            return False
        before = toks[start - 1].lower
        return before in LOCATIVES or before == "the"

    def _hide(self, span: list[Tok], by_default: bool = False) -> None:
        for tok in span:
            tok.redact = True
            tok.by_default = by_default

    def _coordinate(self) -> None:
        """'Peter and Brenda': a kept given-name span joined to a private one."""
        toks = self.toks
        for i, tok in enumerate(toks):
            if tok.redact or tok.keep or not tok.cap or tok.kind not in ("major", "public", "bible"):
                continue
            if not self._given(tok) or tok.breaks_after or self._book_reference(i, i + 1):
                continue
            for j in (i + 2, i - 2):
                if 0 <= j < len(toks) and toks[min(i, j) + 1].lower in JOINERS:
                    other = toks[j]
                    if other.redact and other.cap:
                        tok.redact = True

    def _lowercase(self) -> None:
        """'pray for brenda', 'her boy tyler': a lowercase given name after a cue."""
        toks, L = self.toks, self.L
        for i, tok in enumerate(toks):
            if tok.redact or tok.keep or tok.cap or not tok.core:
                continue
            if tok.lower in self.config.block:
                tok.redact = True
                continue
            name = tok.name.capitalize()
            if name not in L.given or name in L.places or name in L.terms or self._is_word(tok.lower):
                continue
            cue = self._cue_before(i)
            if cue in ("title", "relation", "verb", "appositive") or (cue == "weak" and name not in L.bible):
                tok.redact = True
