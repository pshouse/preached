"""Build the hand-curated Wesley manifest from archive.org + LibriVox metadata.

Sources are fixed below on purpose: never bulk-import by archive.org tag
(the "sermons" tag includes extremist preachers). Add items by hand only.

    uv run ingest/manifest.py            # writes ingest/manifest/wesley.jsonl
"""

import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "manifest" / "wesley.jsonl"
META_CACHE = Path("/cache/meta/wesley")

# archive.org identifier -> (series key, LibriVox catalog title)
SOURCES = {
    "sermonsfirstseries_1307_librivox": ("s1", "Sermons on Several Occasions, First Series"),
    "sermonssecondseries_1503_librivox": ("s2", "Sermons on Several Occasions, Second Series"),
    "sermons3to5series_1511_librivox": ("s3to5", "Sermons on Several Occasions, Third-Fifth Series"),
}

# The 64 kbps MP3 derivative is the one file format present for every track in
# all three items, it is what LibriVox itself links as listen_url, and it is
# half the size of the 128 kbps/VBR files. Whisper resamples to 16 kHz mono,
# so the extra bitrate buys nothing for transcription.
AUDIO_FORMAT = "64Kbps MP3"

LICENSE_NOTE = (
    "LibriVox recording, dedicated to the public domain (US); text by John Wesley "
    "(d. 1791) is public domain. Read by a volunteer LibriVox reader, NOT Wesley's voice."
)


def fetch_json(url: str, cache: Path) -> dict:
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "preached-ingest/0.1"})
        with urllib.request.urlopen(req, timeout=60) as r:
            cache.write_bytes(r.read())
    return json.loads(cache.read_text())


def librivox_book(title: str) -> dict:
    # One prefix search returns all three Wesley volumes (with per-section readers).
    q = urllib.parse.quote("^Sermons on Several Occasions")
    url = f"https://librivox.org/api/feed/audiobooks/?title={q}&extended=1&format=json"
    data = fetch_json(url, META_CACHE / "lv_search.json")
    return next(b for b in data["books"] if b["title"] == title)


# LibriVox series number -> Wesley's standard sermon number (1771 edition / CCEL).
# s1 reads "Christian Perfection" (40) in two parts, so later tracks shift by one.
def wesley_number(series: str, num: int) -> int | None:
    if series == "s1":
        return None if num == 0 else (num if num <= 40 else num - 1)
    return {"s2": 53, "s3to5": 108}[series] + num


CCEL_TXT_URL = "https://www.ccel.org/ccel/w/wesley/sermons/cache/sermons.txt"
CCEL_URL = "https://www.ccel.org/ccel/wesley/sermons"

# Hand-checked fixes where parsing the CCEL text fails or the text is wrong:
# 4 has an Ezek 33:4 title-page epigraph before the real text; 52 has no body
# heading; 64/120/128 lack quote/ref formatting; 134 is a CCEL typo (Isa 1:21).
SCRIPTURE_OVERRIDES = {
    4: ("Acts 4:31", "And they were all filled with the Holy Ghost."),
    52: ("Ps. 94:16", "Who will rise up with me against the wicked?"),
    64: ("Rev. 21:5", "Behold, I make all things new."),
    120: ("Matt. 22:12", "How camest thou in hither not having a wedding garment?"),
    128: ("Rom. 8:32", "He that spared not his own Son, but delivered him up for us all, "
                       "how shall he not with him also freely give us all things?"),
    134: ("Isa. 1:21", "How is the faithful city become an harlot!"),
}


def ccel_scripture() -> dict[int, tuple[str | None, str | None]]:
    """Wesley number -> (reference, quoted text), parsed from each sermon's heading."""
    path = META_CACHE / "ccel" / "sermons.txt"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(CCEL_TXT_URL, headers={"User-Agent": "preached-ingest/0.1"})
        with urllib.request.urlopen(req, timeout=120) as r:
            path.write_bytes(r.read())
    body = path.read_text().split("First Series\n     ___", 1)[1]
    out: dict[int, tuple[str | None, str | None]] = {}
    for part in re.split(r"\n(?=Sermon \d+(?: \[\d+\])?\n)", body):
        m = re.match(r"Sermon (\d+)", part)
        if not m:
            continue
        head = part.split("\n   1.")[0]
        lines = [ln.strip() for ln in head.splitlines()[1:] if ln.strip()]
        quote = ref = None
        for i, ln in enumerate(lines[1:8], 1):
            if ln.startswith('"'):
                j, q = i, [ln]
                while not q[-1].endswith('"') and j + 1 < len(lines):
                    j += 1
                    q.append(lines[j])
                quote = " ".join(q).strip('"')
                if j + 1 < len(lines) and re.match(r"[1-3]?\s?[A-Z][a-z]+\.? ?\d+[:.]", lines[j + 1]):
                    ref = lines[j + 1].rstrip(".")
                break
        out[int(m.group(1))] = (ref, quote)
    for n, v in SCRIPTURE_OVERRIDES.items():
        out[n] = v
    return out


def build() -> list[dict]:
    scripture = ccel_scripture()
    rows = []
    for ident, (series, lv_title) in SOURCES.items():
        meta = fetch_json(f"https://archive.org/metadata/{ident}", META_CACHE / f"{ident}.json")
        book = librivox_book(lv_title)
        assert book["url_iarchive"].rstrip("/").endswith(ident), (ident, book["url_iarchive"])
        by_file = {s["listen_url"].rsplit("/", 1)[1]: s for s in book["sections"]}
        files = sorted(
            (f for f in meta["files"] if f.get("format") == AUDIO_FORMAT),
            key=lambda f: int(f["track"]),
        )
        assert len(files) == len(book["sections"]), (ident, len(files), len(book["sections"]))
        for f in files:
            sec = by_file[f["name"]]
            m = re.match(r"\s*(\d+)\s*-\s*(.+)", f["title"])
            num, title = int(m.group(1)), m.group(2).strip()
            readers = [r["display_name"] for r in sec["readers"]]
            wn = wesley_number(series, num)
            ref, quote = scripture.get(wn, (None, None)) if wn else (None, None)
            rows.append({
                "id": f"wesley-{series}-{num:02d}",
                "author": "John Wesley",
                "work": meta["metadata"]["title"],
                "series": series,
                "sermon_number": num,  # number within this LibriVox series (0 = Preface)
                "wesley_sermon_number": wn,  # standard numbering (1-141), as on CCEL
                "kind": "preface" if title.lower() == "preface" else "sermon",
                "title": title,
                # Not in archive.org/LibriVox metadata; from the CCEL text heading.
                "scripture": ref,
                "scripture_text": quote,
                "reader": ", ".join(readers),
                "reader_ids": [r["reader_id"] for r in sec["readers"]],
                "duration_s": int(sec["playtime"]),
                "audio_url": f"https://archive.org/download/{ident}/{urllib.parse.quote(f['name'])}",
                "audio_format": AUDIO_FORMAT,
                "file_name": f["name"],
                "size": int(f["size"]),
                "md5": f["md5"],
                "ia_identifier": ident,
                "ia_url": f"https://archive.org/details/{ident}",
                "librivox_url": book["url_librivox"],
                "librivox_section_id": sec["id"],
                "text_source_url": CCEL_URL,
                "license_url": meta["metadata"].get("licenseurl"),
                "license_note": LICENSE_NOTE,
            })
    return rows


def load() -> list[dict]:
    return [json.loads(line) for line in MANIFEST.read_text().splitlines() if line.strip()]


def main() -> None:
    rows = build()
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    hours = sum(r["duration_s"] for r in rows) / 3600
    print(f"wrote {len(rows)} rows, {hours:.1f} h audio -> {MANIFEST}", file=sys.stderr)


if __name__ == "__main__":
    main()
