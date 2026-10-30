"""Fetch and chunk Wesley's Sermons on Several Occasions.

The text is the public-domain CCEL edition (Jackson 1872 numbering, sermons
1-141). Those numbers are the same ones LibriVox uses:

- sermonsfirstseries_1307_librivox: sermons 1-53 (plus a preface, not a sermon)
- sermonssecondseries_1503_librivox: sermons 54-108
- sermons3to5series_1511_librivox: sermons 109-141

Sermon ids are ``wesley-001`` ... ``wesley-141`` so a later transcript pass
can join on the sermon number without renaming chunks.

Chunk records always have ``start_s`` and ``end_s``. Text-derived chunks
leave them null. A transcript chunk fills them with seconds and needs no
schema change.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.request
from pathlib import Path

from preached.paths import (
    CCEL_INDEX_URL,
    CCEL_PAGE,
    CCEL_TEXT_URL,
    CHUNKS_JSONL,
    CORPUS_DIR,
    NUMBER_INDEX_HTML,
    SERMONS_JSONL,
    SERMONS_TEXT,
    catalog_path,
    chunk_config_path,
)

USER_AGENT = "preached-corpus-fetch/0.1 (public-domain sermon text; educational)"

SERMON_SPLIT = re.compile(r"(?m)^Sermon (\d+)(?:\s+\[[^\]]*\])*\s*$")
SEPARATOR = re.compile(r"\n[ \t]*_{10,}[ \t]*\n")
INDEX_ROW = re.compile(
    r'<p style="text-align:right"[^>]*>\s*(\d+)\.\s*</p>\s*</td>\s*<td[^>]*>\s*'
    r'<p[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
    r'(?:—<a[^>]*>(.*?)</a>)?',
    re.S,
)
FOOTNOTE_MARK = re.compile(r"\s*\[\d+\]\s*")

# Periods that do not end a sentence in this edition.
ABBREV = {
    "mr", "mrs", "ms", "dr", "st", "sr", "jr", "prof", "gen", "gov", "hon",
    "no", "nos", "vol", "ch", "chap", "vs", "vss", "viz", "cf", "al", "etc",
    "rev", "mt", "mk", "lk", "jn", "joh", "rom", "eph", "cor", "gal", "phil",
    "col", "thess", "tim", "tit", "phlm", "heb", "jas", "pet", "jude",
    "matt", "acts", "gen", "exod", "ex", "lev", "num", "deut", "josh",
    "judg", "sam", "kgs", "chr", "ezra", "neh", "esth", "job", "ps", "prov",
    "eccl", "isa", "jer", "lam", "ezek", "dan", "hos", "joel", "amos",
    "obad", "mic", "nah", "hab", "zeph", "hag", "zech", "mal", "song",
}


MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024  # the CCEL text is ~4 MB


def download(url: str, dest: Path, max_bytes: int = MAX_DOWNLOAD_BYTES) -> None:
    """Stream to a temp file, refuse anything over max_bytes, then rename."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    partial = dest.with_suffix(dest.suffix + ".part")
    total = 0
    with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as out:
        for block in iter(lambda: response.read(1 << 16), b""):
            total += len(block)
            if total > max_bytes:
                out.close()
                partial.unlink(missing_ok=True)
                raise RuntimeError(f"{url} is over {max_bytes} bytes; refusing it")
            out.write(block)
    partial.replace(dest)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def series_for(number: int) -> int:
    if number <= 53:
        return 1
    if number <= 108:
        return 2
    if number <= 126:
        return 3
    if number <= 133:
        return 4
    return 5


def librivox_id(number: int) -> str:
    if number <= 53:
        return "sermonsfirstseries_1307_librivox"
    if number <= 108:
        return "sermonssecondseries_1503_librivox"
    return "sermons3to5series_1511_librivox"


def parse_number_index(raw_html: str) -> dict[int, dict]:
    found: dict[int, dict] = {}
    for number, href, title, scripture in INDEX_ROW.findall(raw_html):
        n = int(number)
        page = href.split("#", 1)[0]
        found[n] = {
            "index_title": strip_tags(title),
            "scripture": strip_tags(scripture or ""),
            "source_url": CCEL_PAGE.format(href=page),
        }
    if len(found) != 141:
        raise RuntimeError(f"expected 141 sermons in the CCEL number index, found {len(found)}")
    return found


def unwrap(raw: str) -> str:
    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        lines = [line for line in lines if not re.fullmatch(r"_+", line)]
        if not lines:
            continue
        joined = lines[0]
        for line in lines[1:]:
            if joined.endswith("-") and line[:1].islower():
                joined = joined[:-1] + line
            else:
                joined += " " + line
        joined = re.sub(r"\s+", " ", joined).strip()
        if joined:
            paragraphs.append(joined)
    return "\n\n".join(paragraphs)


def _split_header(raw: str) -> tuple[list[str], str, str, str]:
    lines = raw.splitlines()
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    header: list[str] = []
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith('"') or stripped.startswith("\u201c"):
            break
        if stripped:
            header.append(stripped)
        index += 1
    quote_lines: list[str] = []
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped and quote_lines:
            break
        if stripped:
            quote_lines.append(stripped)
            if stripped.endswith('"') or stripped.endswith("\u201d"):
                index += 1
                break
        index += 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    reference = ""
    if index < len(lines):
        reference = lines[index].strip()
        index += 1
    body = unwrap("\n".join(lines[index:]))
    quote = re.sub(r"\s+", " ", " ".join(quote_lines)).strip()
    return header, quote, reference, body


def display_title(header: list[str], index_title: str) -> str:
    cleaned: list[str] = []
    for line in header:
        line = FOOTNOTE_MARK.sub(" ", line)
        line = re.sub(r"\s+", " ", line).strip(" -")
        if not line or line.lower() == "advertisement":
            continue
        cleaned.append(line)
    if len(cleaned) >= 2 and cleaned[1].lower().startswith("discourse"):
        return f"{cleaned[0]}, {cleaned[1]}"
    if cleaned:
        return cleaned[0]
    inverted = re.match(r"^(.*), (The|A|An)$", index_title)
    if inverted:
        return f"{inverted.group(2)} {inverted.group(1)}"
    return index_title


def parse_sermons(text: str, index: dict[int, dict]) -> list[dict]:
    parts = SERMON_SPLIT.split(text)
    sermons: list[dict] = []
    # parts[0] is the preface and indexes. Then number, body, number, body...
    for offset in range(1, len(parts), 2):
        number = int(parts[offset])
        raw = parts[offset + 1]
        before_notes = SEPARATOR.split(raw, maxsplit=1)[0]
        header, quote, reference, body = _split_header(before_notes)
        meta = index.get(number)
        if meta is None:
            raise RuntimeError(f"sermon {number} is in the text but not in the CCEL number index")
        pieces = [piece for piece in (quote, reference, body) if piece]
        sermon_text = "\n\n".join(pieces).strip()
        title = display_title(header, meta["index_title"])
        sermons.append(
            {
                "sermon_id": f"wesley-{number:03d}",
                "sermon_number": number,
                "series": series_for(number),
                "librivox_id": librivox_id(number),
                "title": title,
                "index_title": meta["index_title"],
                "scripture": meta["scripture"] or reference.rstrip("."),
                "scripture_line": reference,
                "opening_quote": quote,
                "source_url": meta["source_url"],
                "text": sermon_text,
                "word_count": len(word_tokens(sermon_text)),
            }
        )
    sermons.sort(key=lambda item: item["sermon_number"])
    numbers = [item["sermon_number"] for item in sermons]
    if numbers != list(range(1, 142)):
        raise RuntimeError(f"sermon numbers are not 1..141: got {numbers[:5]}...{numbers[-5:]}")
    return sermons


def word_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?", text)


def split_sentences(paragraph: str) -> list[str]:
    """Split on . ! ? that follow a real sentence, not Mr. / Rom. / J."""

    def protect(match: re.Match[str]) -> str:
        token = match.group(1)
        key = token.lower().replace(".", "")
        if key in ABBREV:
            return token + "\u0001"
        # Initials ("J. Wesley"), but not the s in "Mary's."
        if len(token) == 1 and token.isupper():
            start = match.start(1)
            if start > 0 and paragraph[start - 1] in "'\u2019":
                return match.group(0)
            return token + "\u0001"
        return match.group(0)

    protected = re.sub(r"\b((?:[A-Za-z]\.){1,3}[A-Za-z]?|[A-Za-z]{1,6})\.(?=\s)", protect, paragraph)
    protected = re.sub(
        r"\b([Ii]\.[Ee]|[Ee]\.[Gg])\.",
        lambda match: match.group(1).replace(".", "\u0001") + "\u0001",
        protected,
    )
    # A period after a digit is a verse number or a "1." heading, not a sentence end.
    parts = re.split(r'(?<!\d)(?<=[.!?])\s+(?=["\u201cA-Z])', protected)
    sentences = []
    for part in parts:
        sentence = part.replace("\u0001", ".").strip()
        if sentence:
            sentences.append(sentence)
    return sentences


def load_chunk_config(path: Path | None = None) -> dict:
    config_path = path or chunk_config_path()
    config = json.loads(config_path.read_text())
    required = ("target_words", "min_words", "max_words", "overlap", "wpm")
    missing = [key for key in required if key not in config]
    if missing:
        raise RuntimeError(f"chunk config missing {missing}")
    if not 0 <= config["overlap"] < 1:
        raise RuntimeError("overlap must be in [0, 1)")
    if not (config["min_words"] <= config["target_words"] <= config["max_words"]):
        raise RuntimeError("need min_words <= target_words <= max_words")
    return config


def _sentence_units(text: str, max_words: int) -> list[str]:
    units: list[str] = []
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
    for paragraph in paragraphs:
        for sentence in split_sentences(paragraph):
            tokens = word_tokens(sentence)
            if len(tokens) <= max_words:
                units.append(sentence)
                continue
            # A single sentence longer than the window is split on word
            # boundaries so every chunk stays near a minute of speech.
            start = 0
            while start < len(tokens):
                units.append(" ".join(tokens[start : start + max_words]))
                start += max_words
    return units


def chunk_text(text: str, config: dict) -> list[dict]:
    """Pack sentences into overlapping windows of about 30-60 seconds.

    At ``wpm`` words per minute, ``min_words``..``max_words`` is the window.
    Overlap is a fraction of the chunk just emitted. The next window starts
    that many words back, on a sentence boundary. Returns word spans into
    ``word_tokens(text)`` so a quote can be tied back to a place in the sermon.
    """
    target = int(config["target_words"])
    minimum = int(config["min_words"])
    maximum = int(config["max_words"])
    overlap = float(config["overlap"])
    units = _sentence_units(text, maximum)
    if not units:
        return []
    lengths = [len(word_tokens(unit)) for unit in units]
    chunks: list[dict] = []
    start = 0
    count = len(units)
    while start < count:
        words = 0
        end = start
        while end < count:
            next_words = words + lengths[end]
            # Do not run past the minute mark once the chunk has any text.
            # A short tail is better than a two-minute chunk.
            if words > 0 and next_words > maximum:
                break
            if words >= target and words >= minimum:
                break
            words = next_words
            end += 1
            if words >= maximum:
                break
        if end == start:
            end = start + 1
            words = lengths[start]
        piece = " ".join(units[start:end])
        word_start = sum(lengths[:start])
        chunks.append(
            {
                "text": piece,
                "word_count": len(word_tokens(piece)),
                "word_start": word_start,
                "word_end": word_start + words,
            }
        )
        if end >= count:
            break
        overlap_words = int(words * overlap)
        back = 0
        cursor = end
        while cursor > start + 1 and back < overlap_words:
            cursor -= 1
            back += lengths[cursor]
        if cursor <= start:
            cursor = start + 1
        start = cursor
    return _merge_short_chunks(chunks, minimum, maximum)


def _merge_short_chunks(chunks: list[dict], minimum: int, maximum: int, slack: int = 30) -> list[dict]:
    """Absorb a window that is only a heading or an overlap tail.

    A two-word sentence such as "3. First." must not stand alone when the
    next sentence is the rest of the point. Merged windows may run
    ``slack`` words past ``maximum``.
    """
    if len(chunks) < 2:
        return chunks
    merged: list[dict] = []
    for chunk in chunks:
        if merged and chunk["word_end"] <= merged[-1]["word_end"]:
            continue
        if (
            merged
            and merged[-1]["word_count"] < minimum
            and chunk["word_start"] >= merged[-1]["word_end"]
            and merged[-1]["word_count"] + chunk["word_count"] <= maximum + slack
        ):
            previous = merged[-1]
            previous["text"] = previous["text"] + " " + chunk["text"]
            previous["word_end"] = chunk["word_end"]
            previous["word_count"] = len(word_tokens(previous["text"]))
            continue
        merged.append(dict(chunk))
    if len(merged) >= 2 and merged[-1]["word_count"] < minimum:
        previous, last = merged[-2], merged[-1]
        if (
            last["word_start"] >= previous["word_end"]
            and previous["word_count"] + last["word_count"] <= maximum + slack
        ):
            previous["text"] = previous["text"] + " " + last["text"]
            previous["word_end"] = last["word_end"]
            previous["word_count"] = len(word_tokens(previous["text"]))
            merged.pop()
    return merged


def chunk_sermon(sermon: dict, config: dict) -> list[dict]:
    pieces = chunk_text(sermon["text"], config)
    records = []
    for index, piece in enumerate(pieces):
        records.append(
            {
                "chunk_id": f"{sermon['sermon_id']}-c{index:04d}",
                "sermon_id": sermon["sermon_id"],
                "sermon_title": sermon["title"],
                "text": piece["text"],
                "start_s": None,
                "end_s": None,
                "sermon_number": sermon["sermon_number"],
                "series": sermon["series"],
                "librivox_id": sermon["librivox_id"],
                "scripture": sermon["scripture"],
                "source_url": sermon["source_url"],
                "word_count": piece["word_count"],
                "word_start": piece["word_start"],
                "word_end": piece["word_end"],
            }
        )
    return records


def write_jsonl(path: Path, rows: list[dict]) -> None:
    from preached.privacy import ReviewItem, ReviewList

    if isinstance(rows, ReviewList) or any(isinstance(r, ReviewItem) for r in rows):
        raise ValueError("privacy review items hold real names and must never be written to the corpus")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def catalog_text_sha(catalog_file: Path) -> str:
    """The pinned sha256 of the CCEL text from corpus/catalog.json. A missing
    file or a missing/empty value is an error, never a silently skipped check."""
    if not catalog_file.exists():
        raise RuntimeError(f"{catalog_file} is missing, so the CCEL text cannot be verified")
    expected = json.loads(catalog_file.read_text()).get("sha256_text")
    if not isinstance(expected, str) or not expected.strip():
        raise RuntimeError(
            f"{catalog_file} has no sha256_text, so the CCEL text cannot be verified. "
            "Restore it, or rerun the fetch with --accept-new-text after re-validating eval quotes."
        )
    return expected.strip()


def fetch_corpus(force: bool = False, accept_new_text: bool = False) -> dict:
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    if force or not SERMONS_TEXT.exists():
        download(CCEL_TEXT_URL, SERMONS_TEXT)
    # The eval quotes were checked against this exact text. A changed upstream
    # file must be a deliberate decision, not a silent rebuild.
    if catalog_path().exists() and not accept_new_text:
        expected = catalog_text_sha(catalog_path())
        actual = sha256(SERMONS_TEXT)
        if actual != expected:
            raise RuntimeError(
                f"{SERMONS_TEXT} sha256 {actual} does not match corpus/catalog.json {expected}. "
                "Rerun with --accept-new-text only after re-validating eval quotes."
            )
    if force or not NUMBER_INDEX_HTML.exists():
        download(CCEL_INDEX_URL, NUMBER_INDEX_HTML)
    text = SERMONS_TEXT.read_text(encoding="utf-8")
    index = parse_number_index(NUMBER_INDEX_HTML.read_text(encoding="utf-8", errors="replace"))
    sermons = parse_sermons(text, index)
    write_jsonl(SERMONS_JSONL, sermons)
    catalog = {
        "work": "Sermons on Several Occasions",
        "author": "John Wesley",
        "rights": "Public Domain",
        "edition": "Jackson 1872 numbering, as published by CCEL",
        "text_url": CCEL_TEXT_URL,
        "index_url": CCEL_INDEX_URL,
        "sha256_text": sha256(SERMONS_TEXT),
        "sermon_id_scheme": "wesley-{number:03d}",
        "numbering_note": (
            "Sermon numbers 1-141 are Wesley's standard numbering in the 1872 edition. "
            "LibriVox sermonsfirstseries_1307_librivox is 1-53 (track 00 is the preface), "
            "sermonssecondseries_1503_librivox is 54-108, "
            "sermons3to5series_1511_librivox is 109-141."
        ),
        "sermon_count": len(sermons),
        "word_count": sum(item["word_count"] for item in sermons),
        "sermons": [
            {
                "sermon_id": item["sermon_id"],
                "sermon_number": item["sermon_number"],
                "series": item["series"],
                "librivox_id": item["librivox_id"],
                "title": item["title"],
                "index_title": item["index_title"],
                "scripture": item["scripture"],
                "source_url": item["source_url"],
                "word_count": item["word_count"],
            }
            for item in sermons
        ],
    }
    catalog_path().parent.mkdir(parents=True, exist_ok=True)
    catalog_path().write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
    (CORPUS_DIR / "catalog.json").write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
    return catalog


def build_chunks(config: dict | None = None) -> list[dict]:
    if not SERMONS_JSONL.exists():
        raise RuntimeError(f"missing {SERMONS_JSONL}; run corpus/fetch_wesley.py first")
    config = config or load_chunk_config()
    sermons = read_jsonl(SERMONS_JSONL)
    chunks: list[dict] = []
    for sermon in sermons:
        chunks.extend(chunk_sermon(sermon, config))
    write_jsonl(CHUNKS_JSONL, chunks)
    return chunks
