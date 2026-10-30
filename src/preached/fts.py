"""Turn a church member's question into an FTS5 MATCH query.

Wesley cites scripture with short names ("Rom. 8:16"). A question that says
"Romans 8:16" would miss that unless the book name is expanded to the
abbreviation he actually printed. Natural-language questions are OR of the
content words, because AND-ing "what should a christian do when..." matches
nothing. Short keyword queries stay AND so "witness" and "spirit" must both
hit.
"""

from __future__ import annotations

import re

# Stopwords that show up in questions and not in the doctrine.
STOP = {
    "a", "an", "the", "of", "to", "and", "or", "in", "on", "for", "with",
    "from", "by", "at", "as", "is", "are", "was", "were", "be", "been",
    "being", "it", "its", "this", "that", "these", "those", "i", "me", "my",
    "we", "our", "you", "your", "he", "she", "they", "them", "their", "his",
    "her", "do", "does", "did", "doing", "what", "whats", "which", "who",
    "whom", "whose", "when", "where", "why", "how", "should", "would",
    "could", "can", "will", "shall", "may", "might", "must", "about",
    "into", "over", "than", "then", "there", "here", "if", "but", "not",
    "no", "nor", "so", "too", "very", "just", "wesley", "wesleys", "john",
    "say", "says", "said", "preach", "preached", "preaching", "sermon",
    "sermons", "teach", "taught", "teaching", "tell", "told",
}

# Query book name -> tokens that appear in this edition.
BOOKS: dict[str, list[str]] = {
    "genesis": ["genesis", "gen"],
    "exodus": ["exodus", "exod", "ex"],
    "leviticus": ["leviticus", "lev"],
    "numbers": ["numbers", "num"],
    "deuteronomy": ["deuteronomy", "deut"],
    "joshua": ["joshua", "josh"],
    "judges": ["judges", "judg"],
    "ruth": ["ruth"],
    "1 samuel": ["samuel", "sam"],
    "2 samuel": ["samuel", "sam"],
    "1 kings": ["kings", "kgs"],
    "2 kings": ["kings", "kgs"],
    "1 chronicles": ["chronicles", "chr"],
    "2 chronicles": ["chronicles", "chr"],
    "ezra": ["ezra"],
    "nehemiah": ["nehemiah", "neh"],
    "esther": ["esther", "esth"],
    "job": ["job"],
    "psalm": ["psalm", "psalms", "ps"],
    "psalms": ["psalm", "psalms", "ps"],
    "proverbs": ["proverbs", "prov"],
    "ecclesiastes": ["ecclesiastes", "eccl"],
    "isaiah": ["isaiah", "isa"],
    "jeremiah": ["jeremiah", "jer"],
    "lamentations": ["lamentations", "lam"],
    "ezekiel": ["ezekiel", "ezek"],
    "daniel": ["daniel", "dan"],
    "hosea": ["hosea", "hos"],
    "joel": ["joel"],
    "amos": ["amos"],
    "obadiah": ["obadiah", "obad"],
    "jonah": ["jonah"],
    "micah": ["micah", "mic"],
    "nahum": ["nahum", "nah"],
    "habakkuk": ["habakkuk", "hab"],
    "zephaniah": ["zephaniah", "zeph"],
    "haggai": ["haggai", "hag"],
    "zechariah": ["zechariah", "zech"],
    "malachi": ["malachi", "mal"],
    "matthew": ["matthew", "matt"],
    "mark": ["mark"],
    "luke": ["luke"],
    "john": ["john"],
    "acts": ["acts"],
    "romans": ["romans", "rom"],
    "1 corinthians": ["corinthians", "cor"],
    "2 corinthians": ["corinthians", "cor"],
    "galatians": ["galatians", "gal"],
    "ephesians": ["ephesians", "eph"],
    "philippians": ["philippians", "phil"],
    "colossians": ["colossians", "col"],
    "1 thessalonians": ["thessalonians", "thess"],
    "2 thessalonians": ["thessalonians", "thess"],
    "1 timothy": ["timothy", "tim"],
    "2 timothy": ["timothy", "tim"],
    "titus": ["titus"],
    "philemon": ["philemon"],
    "hebrews": ["hebrews", "heb"],
    "james": ["james", "jas"],
    "1 peter": ["peter", "pet"],
    "2 peter": ["peter", "pet"],
    "1 john": ["john"],
    "2 john": ["john"],
    "3 john": ["john"],
    "jude": ["jude"],
    "revelation": ["revelation", "rev"],
}

SCRIPTURE_RE = re.compile(
    r"^\s*(?:(?P<num>[1-3])\s+)?(?P<book>[A-Za-z]+)\s+(?P<chap>\d+)\s*:\s*(?P<verse>\d+)\s*$"
)
TOKEN_RE = re.compile(r"[A-Za-z0-9']+")


def _quote(token: str) -> str:
    return '"' + token.replace('"', "") + '"'


def scripture_match(query: str) -> str | None:
    match = SCRIPTURE_RE.match(query.strip())
    if not match:
        return None
    number = match.group("num")
    book = match.group("book").lower()
    key = f"{number} {book}" if number else book
    aliases = BOOKS.get(key) or BOOKS.get(book)
    if not aliases:
        return None
    book_or = " OR ".join(_quote(alias) for alias in aliases)
    chapter = _quote(match.group("chap"))
    verse = _quote(match.group("verse"))
    # "Rom. 8:16" tokenizes as rom, 8, 16 within a few tokens of each other.
    return f"({book_or}) NEAR/4 {chapter} NEAR/4 {verse}"


def content_terms(query: str) -> list[str]:
    terms = []
    for token in TOKEN_RE.findall(query):
        if token.lower() in STOP:
            continue
        if token.isdigit():
            continue
        terms.append(token)
    return terms


def to_fts_query(query: str) -> str:
    """FTS5 MATCH string. Higher bm25 rank is computed by the caller (negate)."""
    scripture = scripture_match(query)
    if scripture:
        return scripture
    terms = content_terms(query)
    if not terms:
        terms = TOKEN_RE.findall(query) or ["wesley"]
    joiner = " AND " if len(terms) <= 4 else " OR "
    return joiner.join(_quote(term) for term in terms)
