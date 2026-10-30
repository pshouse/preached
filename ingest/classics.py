"""Build manifests (and provenance) for the hand-picked classic preachers beyond Wesley.

Sources are fixed below on purpose: never bulk-import by archive.org tag.
Each library gets ingest/manifest/<slug>.jsonl in the same row schema as
wesley.jsonl, so ingest/run.py --library <slug> transcribes it unchanged.

    uv run ingest/classics.py                   # manifests for all three
    uv run ingest/classics.py --provenance      # + sha256 of downloaded audio (needs the audio in /cache)
"""

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest  # noqa: E402
from preached.corpus import download  # noqa: E402
from preached.paths import CACHE_ROOT  # noqa: E402

META_CACHE = CACHE_ROOT / "meta" / "classics"
MANIFEST_DIR = Path(__file__).resolve().parent / "manifest"

LIBRIVOX_NOTE = (
    "LibriVox recording, dedicated to the public domain (US); text by {author} ({died}) "
    "is public domain. Read by a volunteer LibriVox reader, NOT {author}'s voice."
)

# slug -> source description. `librivox` is the LibriVox catalog title prefix used
# to join per-section titles and readers; None for the Talmage disc.
SOURCES = {
    "talmage": {
        "ia": "SermonOnTheMountByT.DeWittTalmage1898",
        "author": "T. De Witt Talmage",
        "work": "Sermon on the Mount (1898 recording)",
        "audio_format": "VBR MP3",  # the original upload; the 64 kbps copy is lossier
        "librivox": None,
        "license_note": (
            "Historical recording made in 1898 (Talmage died 1902), uploaded to archive.org "
            "in the 78rpm collection with no licence field. Public domain in the US: it was "
            "fixed before 1923, and Talmage's spoken words are not under copyright. "
            "This is Talmage's own voice."
        ),
        "voice_note": "Historical 1898 recording; Talmage's own voice. Poor audio, ASR is approximate.",
    },
    "spurgeon": {
        "ia": "spurgeons_sermons_librivox",
        "author": "Charles Haddon Spurgeon",
        "work": "Spurgeon's Sermons May 1858",
        "audio_format": "64Kbps MP3",
        "librivox": "^Spurgeon",
        "librivox_title": "Spurgeon's Sermons May 1858",
        "license_note": LIBRIVOX_NOTE.format(author="Charles Haddon Spurgeon", died="d. 1892"),
    },
    "edwards": {
        "ia": "select_sermons_edwards_0911_librivox",
        "author": "Jonathan Edwards",
        "work": "Select Sermons of Jonathan Edwards",
        "audio_format": "64Kbps MP3",
        "librivox": "^Select Sermons",
        "librivox_title": "Select Sermons",
        "license_note": LIBRIVOX_NOTE.format(author="Jonathan Edwards", died="d. 1758"),
    },
}


def fetch_json(url: str, name: str) -> dict:
    cache = META_CACHE / name
    if not cache.exists():
        download(url, cache, max_bytes=manifest.META_MAX_BYTES)
    return json.loads(cache.read_text())


def ia_files(slug: str) -> tuple[dict, list[dict]]:
    src = SOURCES[slug]
    meta = fetch_json(f"https://archive.org/metadata/{src['ia']}", f"{src['ia']}.json")
    files = [f for f in meta["files"] if f.get("format") == src["audio_format"]]
    return meta, files


def librivox_sections(slug: str) -> tuple[dict, dict]:
    src = SOURCES[slug]
    q = urllib.parse.quote(src["librivox"])
    data = fetch_json(
        f"https://librivox.org/api/feed/audiobooks/?title={q}&extended=1&format=json",
        f"lv_{slug}.json",
    )
    book = next(b for b in data["books"] if b["title"].startswith(src["librivox_title"])
                and b["url_iarchive"].rstrip("/").endswith(src["ia"]))
    return book, {s["listen_url"].rsplit("/", 1)[1]: s for s in book["sections"]}


def clean_title(raw: str) -> str:
    title = re.sub(r"^\s*\d+\s*[-:]\s*", "", raw).strip()
    return re.sub(r"\bpt\.? ?(\d)", r"pt \1", title)


def build(slug: str) -> list[dict]:
    src = SOURCES[slug]
    meta, files = ia_files(slug)
    ident = src["ia"]
    common = {
        "author": src["author"],
        "work": src["work"],
        "series": slug,
        "wesley_sermon_number": None,
        "scripture": None,
        "scripture_text": None,
        "audio_format": src["audio_format"],
        "ia_identifier": ident,
        "ia_url": f"https://archive.org/details/{ident}",
        "text_source_url": None,
        "license_url": meta["metadata"].get("licenseurl"),
        "license_note": src["license_note"],
        **({"voice_note": src["voice_note"]} if "voice_note" in src else {}),
    }

    def url(f: dict) -> str:
        return f"https://archive.org/download/{ident}/{urllib.parse.quote(f['name'])}"

    rows = []
    if slug == "talmage":
        for n, f in enumerate(sorted(files, key=lambda f: f["name"]), 1):
            rows.append({
                "id": f"talmage-1898-{n:02d}", "sermon_number": n, "kind": "sermon",
                "title": "Sermon on the Mount (1898)", "reader": "T. De Witt Talmage",
                "reader_ids": [], "duration_s": round(float(f["length"])),
                "audio_url": url(f), "file_name": f["name"], "size": int(f["size"]), "md5": f["md5"],
                "librivox_url": None, "librivox_section_id": None, **common,
            })
        return rows

    book, sections = librivox_sections(slug)
    files.sort(key=lambda f: int(sections[f["name"]]["section_number"]))
    assert len(files) == len(book["sections"]), (slug, len(files), len(book["sections"]))
    for f in files:
        sec = sections[f["name"]]
        title = clean_title(sec["title"])
        num = int(sec["section_number"])
        m = re.match(r"\s*(\d+)\s*:\s*(.+)", sec["title"])  # Spurgeon: "191: Title"
        sermon_no = int(m.group(1)) if (m and slug == "spurgeon") else num
        rows.append({
            "id": f"{slug}-{sermon_no:0{3 if slug == 'spurgeon' else 2}d}",
            "sermon_number": sermon_no,
            "kind": "preface" if re.search(r"advertisement", title, re.I) else "sermon",
            "title": m.group(2).strip() if (m and slug == "spurgeon") else title,
            "reader": ", ".join(r["display_name"] for r in sec["readers"]),
            "reader_ids": [r["reader_id"] for r in sec["readers"]],
            "duration_s": int(sec["playtime"]),
            "audio_url": url(f), "file_name": f["name"], "size": int(f["size"]), "md5": f["md5"],
            "librivox_url": book["url_librivox"], "librivox_section_id": sec["id"], **common,
        })
    return rows


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def provenance(slug: str, rows: list[dict]) -> dict:
    """Identifier, licence and per-file name/size/md5/sha256 of the audio actually used."""
    meta, _ = ia_files(slug)
    audio_dir = CACHE_ROOT / "audio" / slug
    files = []
    for r in rows:
        path = manifest.safe_child(audio_dir, r["file_name"])
        files.append({
            "id": r["id"], "file_name": r["file_name"], "size": r["size"], "md5": r["md5"],
            "sha256": sha256_file(path) if path.exists() else None,
        })
    return {
        "slug": slug,
        "ia_identifier": SOURCES[slug]["ia"],
        "ia_url": f"https://archive.org/details/{SOURCES[slug]['ia']}",
        "title": meta["metadata"].get("title"),
        "creator": meta["metadata"].get("creator"),
        "licenseurl": meta["metadata"].get("licenseurl"),
        "ia_collections": meta["metadata"].get("collection"),
        "license_note": SOURCES[slug]["license_note"],
        "audio_format": SOURCES[slug]["audio_format"],
        "audio_files": files,
        "ia_file_list": sorted(f["name"] for f in meta["files"]),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provenance", action="store_true", help="also write <slug>.provenance.json")
    ap.add_argument("--only", choices=sorted(SOURCES))
    args = ap.parse_args()
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    for slug in ([args.only] if args.only else SOURCES):
        rows = [manifest.validate_row(r) for r in build(slug)]
        (MANIFEST_DIR / f"{slug}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        print(f"{slug}: {len(rows)} rows, {sum(r['duration_s'] for r in rows) / 3600:.2f} h", file=sys.stderr)
        if args.provenance:
            (MANIFEST_DIR / f"{slug}.provenance.json").write_text(
                json.dumps(provenance(slug, rows), indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
