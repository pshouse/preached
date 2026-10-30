"""Propose the stretches of a church recording that are never indexed.

Patrick's decision (2026-10-30): for church libraries, announcements, prayer
requests and prayer lists, and testimonies are excluded. They are where
congregants' names, illnesses and family news are said aloud. The sermon is
public teaching; these stretches are not.

**This proposes; a person decides.** The stretches go into the sermon's
private review file, where the approving human confirms, widens or adds
stretches (``preached.exclusions``). Measured only on a small synthetic set
that an LLM (Claude) wrote, transcripts and gold labels alike (see
``eval/skip`` and ``reports/W3-PRIV-SKIP.md``); it is not measured on real
services. Word recall there was 0.870, so the cues are not enough alone: the
reviewer must listen through the whole recording before approving. That
human check is the real control.

Deterministic rules, no model. The words are split into units (sentences,
or 30-word pieces when Whisper gave no punctuation), and each unit is
scored against cue phrases (``CUES``):

1. A **strong** cue seeds a stretch ("announcements", "potluck", "prayer
   requests", "please be praying for", "let's pray", "my testimony", "I want
   to share what God did"). So do two different **weak** cues in one unit
   ("Wednesday" and "6:30"; "surgery" and "pray for").
2. A stretch grows over neighbouring units while a cue of any category turns
   up at most ``GAP`` cue-less units away, then takes ``PAD`` more units on
   each side. It never grows across a "sermon starts here" marker ("open
   your Bibles", "turn with me to", "our text this morning").
3. A testimony has few cue words once the story starts, so it runs at least
   ``TESTIMONY_UNITS`` units, or to an end marker ("thank you for sharing").
   A prayer opened by "let's pray" or "bow your heads" runs to its "amen"
   (at most ``PRAYER_UNITS`` units).
4. Position: before the first sermon marker (in the first half), if that
   part holds any cue, everything from the start up to the marker is
   excluded. Everything after the last benediction ("the Lord bless you and
   keep you", "go in peace", in the last quarter) is excluded.
5. Overlapping or nearly touching stretches merge.

Each stretch is ``[start, end)`` word indexes plus the cues that matched
(the cue phrase and the word index where it starts), so a reviewer can see
why.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

ANNOUNCEMENTS = "announcements"
PRAYER = "prayer"
TESTIMONY = "testimony"
CATEGORIES = (ANNOUNCEMENTS, PRAYER, TESTIMONY)

UNIT_WORDS = 30
GAP = 2
PAD = 1
TESTIMONY_UNITS = 12
PRAYER_UNITS = 25
MERGE_GAP_UNITS = 1
SERMON_START_SHARE = 0.5
BENEDICTION_SHARE = 0.75

# "TIME" stands for a clock time ("6:30", "7pm", "p.m.", "o'clock") and
# "[name]" for a redacted name. "*" matches one to three words.
CUES: dict[str, dict[str, tuple[str, ...]]] = {
    ANNOUNCEMENTS: {
        "strong": (
            "announcements", "announcement", "potluck", "pot luck", "signup", "sign up", "signups",
            "covered dish", "fellowship meal", "fellowship dinner", "fellowship hall", "bulletin",
            "save the date", "registration", "register online", "connection card", "connect card",
            "first time guest", "first time guests", "firsttime guests", "guests with us", "nursery",
            "vacation bible school", "vbs", "youth group", "business meeting", "bake sale",
            "church office", "welcome center", "info table", "information table", "church app",
            "on our website", "volunteers needed", "need volunteers", "mission trip", "missions trip",
            "give online", "online giving", "offering envelopes", "men's breakfast", "ladies tea",
            "women's retreat", "men's retreat", "small groups", "life groups", "sign the card",
            "wednesday night supper", "trunk or treat", "church picnic", "church family",
        ),
        "weak": (
            "this week", "next week", "this coming", "coming up", "tonight", "this evening",
            "tomorrow", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
            "next sunday", "this sunday", "sunday night", "sunday evening", "TIME", "don't forget",
            "remember to", "reminder", "remind you", "starting at", "meet at", "meets at", "join us",
            "bring a", "volunteer", "volunteers", "deadline", "register", "calendar", "schedule",
            "retreat", "camp", "picnic", "lobby", "foyer", "sheet", "website", "email", "text",
            "parking", "after the service", "after service", "see me after", "welcome", "visitors",
            "visiting with us", "kids", "students", "class", "classes", "breakfast", "lunch",
            "supper", "dinner", "meeting", "event", "tickets", "rsvp", "office", "childcare",
        ),
    },
    PRAYER: {
        "strong": (
            "prayer requests", "prayer request", "prayer list", "prayer chain", "prayer concerns",
            "please be praying", "please pray for", "be praying for", "keep praying for",
            "continue to pray for", "continue praying for", "pray for [name]", "praying for [name]",
            "keep * in your prayers", "keep * in prayer", "in your prayers", "let's pray", "lets pray",
            "let us pray", "bow your heads", "bow with me", "pray with me", "unspoken request",
            "unspoken requests", "unspoken", "praise report", "praise reports", "passed away",
            "home to be with the lord", "traveling mercies", "lift them up", "lift * up in prayer",
        ),
        "weak": (
            "pray for", "praying for", "pray", "praying", "prayers", "hospital", "surgery",
            "diagnosed", "diagnosis", "cancer", "chemo", "chemotherapy", "treatment", "recovery",
            "recovering", "healing", "family of", "loss of", "funeral", "memorial", "grieving",
            "condolences", "lift up", "deployed", "sick", "doctors", "test results", "biopsy",
            "rehab", "icu", "hospice", "her mother", "his mother", "her father",
            "his father", "their son", "their daughter", "her husband", "his wife",
        ),
    },
    TESTIMONY: {
        "strong": (
            "testimony", "testimonies", "testify", "share what god did", "share what god has done",
            "what god did in my life", "what god has done in my life", "come up and share",
            "come and share", "going to share with us", "share with us", "i want to share",
            "share my story", "share her story", "share his story", "share their story",
        ),
        "weak": (
            "my life", "i was", "i had", "i got saved", "got saved", "i was saved", "baptized",
            "god showed up", "god delivered me", "praise god", "addiction", "my husband", "my wife",
            "my kids", "my family", "my mom", "my dad", "my job", "lost my", "i didn't know",
            "years ago", "i remember", "i felt",
        ),
    },
}

# Phrases of a strong cue that do not count ("the testimony of Scripture").
NOT_CUES = ("testimony of", "testimony to the", "testify to the", "testify of")

SERMON_START = (
    "open your bibles", "open your bible", "turn with me", "turn in your bibles", "turn in your bible",
    "if you have your bible", "if you have your bibles", "if you've got your bible", "our text",
    "our passage", "today's text", "today's passage", "this morning's text", "our scripture",
    "the scripture reading", "read with me", "stand for the reading", "reading of god's word",
)
BENEDICTION = (
    "the lord bless you and keep you", "benediction", "go in peace", "now unto him that is able",
    "now to him who is able", "may the grace of our lord", "you are dismissed", "you're dismissed",
)
TESTIMONY_END = (
    "thank you for sharing", "thanks for sharing", "thank you for that", "let's thank",
    "give him a hand", "give her a hand", "give them a hand", "let's give god",
)
PRAYER_OPENERS = ("let's pray", "lets pray", "let us pray", "bow your heads", "bow with me", "pray with me")
PRAYER_END = ("amen",)

_TIME = re.compile(r"^\d{1,2}(?::\d\d)?(?:am|pm)$|^\d{1,2}:\d\d$|^o'clock$|^noon$")
_DOTTED_TIME = re.compile(r"^[ap]\.m\.?$")
_SENTENCE_END = re.compile(r"[.!?…][\"'”’)\]]*$")


def normalize(text: str) -> str:
    """The form cues are written in: lowercase, no punctuation, ``TIME``, ``[name]``."""
    if "[name]" in text:
        return "[name]"
    raw = text.strip().lower().replace("’", "'").replace("‘", "'")
    if _DOTTED_TIME.match(raw.strip("\"“”()[],;:!?")):
        return "TIME"
    token = re.sub(r"[^\w':]", "", raw).strip("':")
    if _TIME.match(token):
        return "TIME"
    return token


def _phrase(text: str) -> tuple[str, ...]:
    return tuple(word if word in ("*", "TIME", "[name]") else normalize(word) for word in text.split())


def _match_at(tokens: Sequence[str], start: int, phrase: tuple[str, ...]) -> int:
    """Length matched by ``phrase`` at ``start`` (0 for none). ``*`` takes 1-3 words."""
    if not phrase:
        return 0
    def walk(i: int, p: int) -> int:
        if p == len(phrase):
            return i
        if phrase[p] == "*":
            for take in (1, 2, 3):
                end = walk(i + take, p + 1) if i + take <= len(tokens) else -1
                if end >= 0:
                    return end
            return -1
        if i < len(tokens) and tokens[i] == phrase[p]:
            return walk(i + 1, p + 1)
        return -1
    end = walk(start, 0)
    return end - start if end > start else 0


@dataclass
class _Matcher:
    phrases: list[tuple[str, tuple[str, ...]]]

    @classmethod
    def of(cls, texts: Sequence[str]) -> "_Matcher":
        return cls([(text, _phrase(text)) for text in texts])

    def find(self, tokens: Sequence[str], lo: int = 0, hi: int | None = None) -> list[tuple[str, int, int]]:
        """``(phrase, start, length)`` for every match starting in ``[lo, hi)``, longest first."""
        hi = len(tokens) if hi is None else hi
        found = []
        for i in range(lo, hi):
            for text, phrase in self.phrases:
                length = _match_at(tokens, i, phrase)
                if length:
                    found.append((text, i, length))
        return found


@dataclass
class Stretch:
    """Words ``[start, end)`` proposed for exclusion, and why."""

    start: int
    end: int
    category: str
    cues: list[tuple[str, int]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "start_word": self.start,
            "end_word": self.end,
            "category": self.category,
            "cues": [{"cue": cue, "word": word} for cue, word in self.cues],
            "reasons": list(self.reasons),
        }


_STRONG = {category: _Matcher.of(CUES[category]["strong"]) for category in CATEGORIES}
_WEAK = {category: _Matcher.of(CUES[category]["weak"]) for category in CATEGORIES}
_NOT = _Matcher.of(NOT_CUES)
_SERMON_START = _Matcher.of(SERMON_START)
_BENEDICTION = _Matcher.of(BENEDICTION)
_TESTIMONY_END = _Matcher.of(TESTIMONY_END)
_PRAYER_OPENERS = _Matcher.of(PRAYER_OPENERS)
_PRAYER_END = _Matcher.of(PRAYER_END)


def units(texts: Sequence[str], max_words: int = UNIT_WORDS) -> list[tuple[int, int]]:
    """Sentences as ``[start, end)`` word indexes; a long one splits every ``max_words``."""
    spans = []
    start = 0
    for index, text in enumerate(texts):
        if _SENTENCE_END.search(text.strip()) or index + 1 - start >= max_words:
            spans.append((start, index + 1))
            start = index + 1
    if start < len(texts):
        spans.append((start, len(texts)))
    return spans


@dataclass
class _Unit:
    start: int
    end: int
    strong: dict[str, list[tuple[str, int]]]
    weak: dict[str, list[tuple[str, int]]]
    sermon_start: bool
    benediction: bool
    testimony_end: bool
    prayer_opener: bool
    prayer_end: bool

    @property
    def has_cue(self) -> bool:
        return any(self.strong.values()) or any(self.weak.values())

    def seed(self) -> str | None:
        """The category this unit starts a stretch for, if any (strong first)."""
        for category in CATEGORIES:
            if self.strong[category]:
                return category
        best = max(CATEGORIES, key=lambda c: len({cue for cue, _ in self.weak[c]}))
        return best if len({cue for cue, _ in self.weak[best]}) >= 2 else None

    def cues(self) -> list[tuple[str, int]]:
        return sorted({hit for c in CATEGORIES for hit in self.strong[c] + self.weak[c]}, key=lambda h: (h[1], h[0]))


def _score(tokens: list[str], start: int, end: int) -> _Unit:
    blocked = {i for _, s, n in _NOT.find(tokens, start, end) for i in range(s, s + n)}
    strong, weak = {}, {}
    for category in CATEGORIES:
        strong[category] = [(t, s) for t, s, _ in _STRONG[category].find(tokens, start, end) if s not in blocked]
        weak[category] = [(t, s) for t, s, _ in _WEAK[category].find(tokens, start, end)]
    return _Unit(
        start, end, strong, weak,
        sermon_start=bool(_SERMON_START.find(tokens, start, end)),
        benediction=bool(_BENEDICTION.find(tokens, start, end)),
        testimony_end=bool(_TESTIMONY_END.find(tokens, start, end)),
        prayer_opener=bool(_PRAYER_OPENERS.find(tokens, start, end)),
        prayer_end=bool(_PRAYER_END.find(tokens, start, end)),
    )


def _grow(scored: list[_Unit], seed: int, category: str) -> tuple[int, int]:
    """Unit range ``[lo, hi]`` (inclusive) of the stretch seeded at ``seed``."""
    last = seed
    j = seed + 1
    while j < len(scored) and j - last <= GAP + 1 and not scored[j].sermon_start:
        if scored[j].has_cue:
            last = j
        j += 1
    hi = last
    first = seed
    j = seed - 1
    while j >= 0 and first - j <= GAP + 1 and not scored[j].sermon_start:
        if scored[j].has_cue:
            first = j
        j -= 1
    lo = first

    def until(limit: int, stop) -> int | None:
        for k in range(seed, min(len(scored), seed + limit + 1)):
            if k > seed and scored[k].sermon_start:
                return k - 1
            if stop(scored[k]):
                return k
        return None

    if category == TESTIMONY:
        end = until(3 * TESTIMONY_UNITS, lambda u: u.testimony_end)
        if end is None:
            end = until(TESTIMONY_UNITS, lambda u: False)
            end = min(len(scored) - 1, seed + TESTIMONY_UNITS) if end is None else end
        hi = max(hi, end)
    if scored[seed].prayer_opener:
        end = until(PRAYER_UNITS, lambda u: u.prayer_end)
        if end is not None:
            hi = max(hi, end)
    # Pad, but never into the sermon marker.
    for _ in range(PAD):
        if hi + 1 < len(scored) and not scored[hi + 1].sermon_start:
            hi += 1
        if lo - 1 >= 0 and not scored[lo - 1].sermon_start:
            lo -= 1
    return lo, hi


def propose(texts: Sequence[str]) -> list[Stretch]:
    """Stretches of ``texts`` (one entry per ASR word) to exclude, in order."""
    tokens = [normalize(text) for text in texts]
    spans = units(texts)
    if not spans:
        return []
    scored = [_score(tokens, a, b) for a, b in spans]
    found: list[tuple[int, int, str, list[str]]] = []  # unit lo, unit hi, category, reasons
    for index, unit in enumerate(scored):
        category = unit.seed()
        if category is not None:
            lo, hi = _grow(scored, index, category)
            found.append((lo, hi, category, ["cue"]))
    count = len(scored)
    starts = [i for i, u in enumerate(scored) if u.sermon_start and i < count * SERMON_START_SHARE]
    if starts and any(u.has_cue for u in scored[: starts[0]]):
        found.append((0, starts[0] - 1, _dominant(scored[: starts[0]]), ["before the sermon proper"]))
    ends = [i for i, u in enumerate(scored) if u.benediction and i >= count * BENEDICTION_SHARE]
    if ends and ends[-1] + 1 < count:
        found.append((ends[-1] + 1, count - 1, _dominant(scored[ends[-1] + 1 :]), ["after the benediction"]))
    found.sort()
    merged: list[list] = []
    for lo, hi, category, reasons in found:
        if merged and lo <= merged[-1][1] + 1 + MERGE_GAP_UNITS:
            merged[-1][1] = max(merged[-1][1], hi)
            merged[-1][3] = merged[-1][3] + [r for r in reasons if r not in merged[-1][3]]
        else:
            merged.append([lo, hi, category, list(reasons)])
    out = []
    for lo, hi, _category, reasons in merged:
        cues = [hit for u in scored[lo : hi + 1] for hit in u.cues()]
        out.append(Stretch(spans[lo][0], spans[hi][1], _dominant(scored[lo : hi + 1]), cues, reasons))
    return out


def _dominant(scored: list[_Unit]) -> str:
    weights = {c: sum(2 * len(u.strong[c]) + len(u.weak[c]) for u in scored) for c in CATEGORIES}
    return max(CATEGORIES, key=lambda c: weights[c])
