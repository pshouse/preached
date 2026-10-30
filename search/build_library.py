"""Index a transcribed public-domain classic library (spurgeon, edwards) into its own SQLite file.

    uv run search/build_library.py spurgeon        # -> /cache/index/spurgeon.sqlite

Reads ingest/manifest/<slug>.jsonl and /cache/transcripts/<slug>/*.json (ingest/run.py output),
keeps the searchable word window, chunks with corpus/chunk_config.json, embeds with Granite on
CPU and writes through the same library writer as the YouTube import. Text is ASR (text_source
'asr'); the audio_url is the plain archive.org file, as in the Wesley index. A sermon already
imported is skipped unless --redo.

Only slugs on the allow-list in src/preached/libraries.py are accepted (never wesley, never a
church library): these files get no redaction and no review, so nothing else may be written here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ingest"))

import numpy as np  # noqa: E402

import manifest  # noqa: E402
from preached.corpus import load_chunk_config  # noqa: E402
from preached.libraries import PUBLIC_DOMAIN, is_public_domain  # noqa: E402
from preached.paths import CACHE_ROOT, INDEX_DIR  # noqa: E402
from preached.store import open_readonly  # noqa: E402
from preached.youtube.chunking import chunk_words  # noqa: E402
from preached.youtube.library import imported_ok, index_video, open_library  # noqa: E402
from preached.youtube.pipeline import _embed_on_cpu  # noqa: E402
from preached.youtube.words import Word  # noqa: E402


def transcript_words(doc: dict) -> list[Word]:
    lo, hi = doc["searchable_start"], doc["searchable_end"]
    out = []
    for seg in doc["segments"]:
        for start, end, text in seg["words"]:
            if lo <= start < hi and text.strip():
                out.append(Word(float(start), float(end), text))
    return out


def chunks_for(row: dict, words: list[Word], config: dict) -> list[dict]:
    return [
        {**piece, "chunk_id": f"{row['id']}-c{i:04d}", "audio_url": row["audio_url"], "source_url": row["ia_url"]}
        for i, piece in enumerate(chunk_words(words, config))
    ]


def check_slug(slug: str) -> str:
    """The slug, or SystemExit unless it is an allow-listed public-domain library."""
    if not is_public_domain(slug):
        raise SystemExit(
            f"error: {slug!r} is not a public-domain library (allowed: {', '.join(PUBLIC_DOMAIN)}). "
            "Wesley is built by search/build_index.py; church libraries go through redaction and review."
        )
    return slug


def check_target(path: Path, slug: str) -> None:
    """Refuse a file that is not this library's: another library's, or a Wesley-style index."""
    if not path.is_file():
        return
    connection = open_readonly(path)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        marker = connection.execute("SELECT value FROM meta WHERE key = 'library'").fetchone() if "meta" in tables else None
        has_chunks = "chunks" in tables and connection.execute("SELECT 1 FROM chunks LIMIT 1").fetchone() is not None
    finally:
        connection.close()
    if marker is not None and marker[0] != slug:
        raise SystemExit(f"error: {path} is the {marker[0]!r} library, not {slug!r}")
    if has_chunks and "videos" not in tables:
        raise SystemExit(f"error: {path} holds chunks but is not a library file (a Wesley-style index?)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--redo", action="store_true")
    args = ap.parse_args()
    slug = check_slug(args.slug)
    rows = manifest.load(manifest.MANIFEST.with_name(f"{slug}.jsonl"))
    tdir = CACHE_ROOT / "transcripts" / slug
    config = load_chunk_config()
    target = INDEX_DIR / f"{slug}.sqlite"
    check_target(target, slug)
    connection = open_library(target)
    # Marks the file as a library so search/query.py --index refuses it.
    connection.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('library', ?)", (slug,))
    connection.commit()
    done = set() if args.redo else imported_ok(connection)
    n = 0
    for row in rows:
        path = manifest.safe_child(tdir, f"{row['id']}.json")
        if row["id"] in done or not path.exists():
            if not path.exists():
                print(f"skip {row['id']}: no transcript yet", file=sys.stderr)
            continue
        words = transcript_words(json.loads(path.read_text()))
        records = chunks_for(row, words, config)
        if not records:
            print(f"skip {row['id']}: no words", file=sys.stderr)
            continue
        matrix = np.asarray(_embed_on_cpu([row["title"]] * len(records), [r["text"] for r in records]))
        index_video(
            connection, video_id=row["id"], title=row["title"], published=None,
            duration_s=row["duration_s"], license_text=row["license_note"], uploader=row["author"],
            chunks=records, matrix=matrix, reader=row["reader"] or None,
            sermon_number=row["sermon_number"], librivox_id=row.get("ia_identifier"),
        )
        n += 1
        print(f"indexed {row['id']}: {len(records)} chunks", file=sys.stderr, flush=True)
    total = connection.execute("SELECT count(*), count(DISTINCT sermon_id) FROM chunks").fetchone()
    print(f"{slug}: +{n} sermons; index has {total[0]} chunks in {total[1]} sermons", file=sys.stderr)
    connection.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
