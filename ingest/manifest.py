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


def build() -> list[dict]:
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
            rows.append({
                "id": f"wesley-{series}-{num:02d}",
                "author": "John Wesley",
                "work": meta["metadata"]["title"],
                "series": series,
                "sermon_number": num,  # number within this LibriVox series (0 = Preface)
                "kind": "preface" if title.lower() == "preface" else "sermon",
                "title": title,
                "scripture": None,  # not present in archive.org/LibriVox metadata
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
                "text_source_url": book["url_text_source"],
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
