"""Normalize canonical text and Whisper words to comparable tokens.

Both sides go through the same rules so that "favour" (CCEL) meets "favor"
(Whisper), "Eph. 2:8" meets "Ephesians 2, 8", "to-day" meets "today" and
"19th" meets "nineteenth". Rules that merge two spellings are applied to both
sides, so an over-eager rule only creates a harmless collision.

Canonical tokens are W1-B's ``word_tokens`` (``preached.corpus``), so a
canonical token index is the same index ``chunks.jsonl`` uses in
``word_start`` / ``word_end``. One canonical token may become several
normalized tokens (a number), and two canonical tokens may become one
("to-day", "Lord's" split by a curly apostrophe).
"""

from __future__ import annotations

import re

TOKEN = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?")  # same as preached.corpus.word_tokens

_ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen"
).split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_ORDINAL = {
    "one": "first", "two": "second", "three": "third", "five": "fifth",
    "eight": "eighth", "nine": "ninth", "twelve": "twelfth",
}

# Archaic or British spellings in the 1872 text -> the form Whisper writes.
SPELLING = {
    "shew": "show", "shewed": "showed", "shewn": "shown", "shews": "shows",
    "shewing": "showing", "connexion": "connection", "connexions": "connections",
    "publick": "public", "musick": "music", "chuse": "choose", "chusing": "choosing",
    "stedfast": "steadfast", "stedfastly": "steadfastly", "stedfastness": "steadfastness",
    "gaol": "jail", "enquire": "inquire", "enquiry": "inquiry", "enquired": "inquired",
    "intreat": "entreat", "intreated": "entreated", "burthen": "burden",
    "burthens": "burdens", "burthened": "burdened", "murther": "murder",
    "compleat": "complete", "compleatly": "completely", "ancle": "ankle",
    "controul": "control", "croud": "crowd", "skilful": "skillful",
    "wilful": "willful", "wilfully": "willfully", "fulfil": "fulfill",
    "fulfils": "fulfills", "instil": "instill", "inthrall": "enthrall",
    "phrenzy": "frenzy", "sceptic": "skeptic", "sceptics": "skeptics",
    "sceptical": "skeptical", "despatch": "dispatch", "grey": "gray",
    "plough": "plow", "mould": "mold", "smoak": "smoke", "cloathed": "clothed",
    "cloaths": "clothes", "o": "oh", "etc": "etcetera", "aught": "ought",
    "thro": "through", "tho": "though", "amongst": "among", "whilst": "while",
    "ay": "aye", "mr": "mister", "mrs": "missus", "dr": "doctor", "st": "saint",
    "viz": "namely",
}

# Abbreviated book names in Scripture references -> spoken name.
BOOKS = {
    "gen": "genesis", "exod": "exodus", "ex": "exodus", "lev": "leviticus",
    "num": "numbers", "deut": "deuteronomy", "josh": "joshua", "judg": "judges",
    "sam": "samuel", "kgs": "kings", "chron": "chronicles", "chr": "chronicles",
    "neh": "nehemiah", "esth": "esther", "psa": "psalm", "ps": "psalm",
    "psalms": "psalm", "prov": "proverbs", "eccles": "ecclesiastes",
    "eccl": "ecclesiastes", "isa": "isaiah", "jer": "jeremiah",
    "lam": "lamentations", "ezek": "ezekiel", "dan": "daniel", "hos": "hosea",
    "obad": "obadiah", "mic": "micah", "nah": "nahum", "hab": "habakkuk",
    "zeph": "zephaniah", "hag": "haggai", "zech": "zechariah", "mal": "malachi",
    "matt": "matthew", "mat": "matthew", "mk": "mark", "lk": "luke",
    "jn": "john", "joh": "john", "rom": "romans", "cor": "corinthians",
    "gal": "galatians", "eph": "ephesians", "phil": "philippians",
    "col": "colossians", "thess": "thessalonians", "thes": "thessalonians",
    "tim": "timothy", "tit": "titus", "philem": "philemon", "heb": "hebrews",
    "jas": "james", "pet": "peter", "rev": "revelation",
}

_OUR = re.compile(
    r"^(favo|hono|labo|savio|behavio|neighbo|colo|endeavo|vigo|rigo|humo|odo|"
    r"ardo|fervo|splendo|clamo|harbo|rumo|savo|cando|valo|parlo|armo|tumo|"
    r"demeano|succo|herbo|flavo|glamo|vapo)ur"
)
_ROMAN = re.compile(r"^(?=[IVXL]{2,}$)(XL|L?X{0,3})(IX|IV|V?I{0,3})$")
_ROMAN_VALUE = {"I": 1, "V": 5, "X": 10, "L": 50}


def int_to_words(n: int) -> list[str]:
    if n < 20:
        return [_ONES[n]]
    if n < 100:
        tens, ones = divmod(n, 10)
        return [_TENS[tens]] + ([_ONES[ones]] if ones else [])
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return [_ONES[hundreds], "hundred"] + (int_to_words(rest) if rest else [])
    if 1100 <= n < 2000 and n % 100:
        # Years are read "seventeen ninety", not "one thousand seven hundred ninety".
        high, low = divmod(n, 100)
        return int_to_words(high) + (["oh"] + int_to_words(low) if low < 10 else int_to_words(low))
    if n < 1_000_000:
        thousands, rest = divmod(n, 1000)
        return int_to_words(thousands) + ["thousand"] + (int_to_words(rest) if rest else [])
    return list(str(n))


def ordinal_words(n: int) -> list[str]:
    words = int_to_words(n)
    last = words[-1]
    if last in _ORDINAL:
        words[-1] = _ORDINAL[last]
    elif last.endswith("y"):
        words[-1] = last[:-1] + "ieth"
    else:
        words[-1] = last + "th"
    return words


def roman_value(token: str) -> int | None:
    if not _ROMAN.match(token):
        return None
    total = 0
    for index, char in enumerate(token):
        value = _ROMAN_VALUE[char]
        following = _ROMAN_VALUE[token[index + 1]] if index + 1 < len(token) else 0
        total += -value if value < following else value
    return total


def norm_word(raw: str, books: bool = False, roman: bool = False) -> list[str]:
    """One raw word (no spaces) -> zero or more normalized tokens.

    ``books`` expands Scripture abbreviations ("Rom" -> "romans"); ``roman``
    reads multi-letter Roman numerals ("XII" -> "twelve").
    """
    if roman:
        bare = raw.strip(".,;:")
        # Lowercase numerals only in references ("Rom. viii. 16"), where
        # ``books`` is set because a period follows.
        value = roman_value(bare.upper() if books else bare)
        if value is not None:
            return int_to_words(value)
    word = raw.lower().replace("’", "'").replace("-", "")
    word = re.sub(r"[^a-z0-9']+", " ", word).replace("'", "").strip()
    out: list[str] = []
    for part in word.split():
        match = re.fullmatch(r"(\d+)(st|nd|rd|th|d)?", part)
        if match:
            number = int(match.group(1))
            out.extend(ordinal_words(number) if match.group(2) else int_to_words(number))
            continue
        if re.fullmatch(r"\d+[a-z]+|[a-z]+\d+", part):
            out.extend(re.findall(r"\d+|[a-z]+", part))
            continue
        out.extend(_spell(part, books).split())
    return out


def _spell(word: str, books: bool) -> str:
    if books and word in BOOKS:
        return BOOKS[word]
    if word in SPELLING:
        return SPELLING[word]
    word = _OUR.sub(r"\1r", word)
    word = re.sub(r"is(e|es|ed|ing|ation|ations)$", r"iz\1", word)
    word = re.sub(r"ll(ed|ing|er|ers)$", r"l\1", word)
    word = re.sub(r"([^aeiou])tre$", r"\1ter", word)
    word = re.sub(r"ick$", "ic", word) if len(word) > 5 else word
    return word


def canonical_tokens(text: str) -> list[tuple[str, list[int]]]:
    """Normalize canonical text.

    Returns ``(norm_token, [canonical token indices])``. Indices refer to
    ``TOKEN.findall(text)``, i.e. W1-B's ``word_tokens``.
    """
    spans = [(m.start(), m.end(), m.group(0)) for m in TOKEN.finditer(text)]
    out: list[tuple[str, list[int]]] = []
    index = 0
    while index < len(spans):
        group = [index]
        # "to-day", "Lord’s", "&c": tokens joined by a hyphen or apostrophe
        # with no space are one spoken word.
        while index + 1 < len(spans) and text[spans[index][1] : spans[index + 1][0]] in ("-", "’", "'"):
            index += 1
            group.append(index)
        raw = "".join(spans[i][2] for i in group)
        before = text[max(0, spans[group[0]][0] - 1) : spans[group[0]][0]]
        if before == "&" and raw.lower() == "c":
            pieces = ["etcetera"]
        else:
            # Book abbreviations only expand when written with a period
            # ("Rom. 8"), so the word "Num" or "Job" in prose is left alone.
            after = text[spans[group[-1]][1] : spans[group[-1]][1] + 1]
            pieces = norm_word(raw, books=after == ".", roman=True)
        for piece in pieces:
            out.append((piece, group))
        index += 1
    return out


_ASR_JOIN = {("et", "cetera"): "etcetera", ("to", "day"): "today", ("to", "morrow"): "tomorrow"}


def asr_tokens(words: list[str]) -> list[tuple[str, int]]:
    """Normalize Whisper words. Returns ``(norm_token, word index)``."""
    out: list[tuple[str, int]] = []
    for index, word in enumerate(words):
        for piece in norm_word(word.strip(), roman=True):
            if out and (out[-1][0], piece) in _ASR_JOIN:
                out[-1] = (_ASR_JOIN[(out[-1][0], piece)], out[-1][1])
                continue
            out.append((piece, index))
    return out
