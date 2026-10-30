"""Timed chunks straight from a Whisper transcript (``text_source: "asr"``).

For sermons with no published text (church recordings), the searchable
words are Whisper's. Same record and the same chunk params as the canonical
path (``corpus/chunk_config.json``, W1-B's ``chunk_text``), so the index
treats both alike and the page can say "Wording follows the recording."

Input is a W1-A-style transcript: ``segments[].words = [[start, end, word]]``,
optional ``searchable_start`` / ``searchable_end`` and ``meta``. A pause of
``--pause`` seconds starts a new paragraph, so unpunctuated stretches still
break near a natural boundary instead of only at ``max_words``.

    python3 align/asr_chunks.py /cache/transcripts/wesley/wesley-s1-01.json --library wesley --out /tmp/asr.jsonl

``--library`` is required. ``wesley`` (LibriVox, public domain) is never
redacted and its output is byte-identical to before. The other public-domain
libraries (``preached.libraries``: spurgeon, edwards) are refused here; they
are built by ``search/build_library.py``, and their files are served without
the publish gate, so church words must never be written under their slugs.
Every other library fails closed:

- it refuses to run without a privacy config (``--privacy <toml>`` or
  ``$PREACHED_PRIVACY``), and always redacts words and titles;
- each sermon gets a private review file (title, then ``review()`` items) in
  ``<index dir>/<library>/review/``, never inside the repo;
- each chunk carries ``video_id`` (the sermon id: the publish-gate key) and,
  when flagged, ``flag_end_s`` for the flagged-audio policy. ``store`` refuses
  to load gate-keyed chunks into an ungated index, so the only way to serve
  them is ``--index <library>.sqlite``, which lands every sermon unpublished
  until ``import/youtube.py --library <slug> --ack-review <sermon id>``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from preached.corpus import chunk_text, load_chunk_config, word_tokens, write_jsonl  # noqa: E402
from preached.libraries import PUBLIC_DOMAIN  # noqa: E402
from preached.privacy import (  # noqa: E402
    CONFIG_ENV,
    Config,
    apply_drops,
    config_sha256,
    load_config,
    redact,
    redact_metadata,
    review,
)

PUBLIC_LIBRARY = "wesley"

PAUSE_S = 1.5
# ASR chunk ids live in their own namespace. Canonical (CCEL) ids are
# "{sermon_id}-cNNNN" with no colon, so a church sermon whose id reuses a CCEL
# sermon id can never hit chunks.chunk_id UNIQUE and fail the rebuild.
ASR_ID_PREFIX = "asr:"


def asr_chunk_id(sermon_id: str, index: int) -> str:
    return f"{ASR_ID_PREFIX}{sermon_id}-c{index:04d}"


def transcript_words(transcript: dict) -> list[tuple[float, float, str]]:
    lo = transcript.get("searchable_start", float("-inf"))
    hi = transcript.get("searchable_end", float("inf"))
    words = [
        (start, end, word.strip())
        for segment in transcript["segments"]
        if not segment.get("boilerplate")
        for start, end, word in segment["words"]
        if lo <= start < hi and word.strip()
    ]
    words.sort(key=lambda item: item[0])
    return words


def asr_chunks(
    transcript: dict,
    config: dict,
    sermon_id: str | None = None,
    sermon_title: str | None = None,
    pause_s: float = PAUSE_S,
    privacy: Config | None = None,
    items: list | None = None,
) -> list[dict]:
    """``privacy`` None leaves the words alone (Wesley only). A Config redacts
    them and the title, keys each chunk to the publish gate (``video_id``)
    and sets ``flag_end_s`` from ``[name]`` words and ``items`` (the sermon's
    ``review()`` list, see ``sermon_review``)."""
    meta = transcript.get("meta", {})
    sermon_id = sermon_id or meta["id"]
    words = transcript_words(transcript)
    if privacy is not None:
        words = redact(words, config=privacy, source=sermon_id)
    # Token index -> Whisper word index. Tokens never cross a space, so the
    # tokens of the joined text are the tokens of each word in order.
    owner: list[int] = []
    pieces: list[str] = []
    for index, (start, _, word) in enumerate(words):
        if index and start - words[index - 1][1] >= pause_s:
            pieces.append("\n\n")
        elif index:
            pieces.append(" ")
        pieces.append(word)
        owner.extend([index] * len(word_tokens(word)))
    text = "".join(pieces)
    if len(owner) != len(word_tokens(text)):
        raise RuntimeError("token map does not match the transcript text")
    records = []
    for index, piece in enumerate(chunk_text(text, config)):
        first = words[owner[piece["word_start"]]]
        last = words[owner[piece["word_end"] - 1]]
        title = sermon_title or meta.get("title") or sermon_id
        if privacy is not None:
            title = redact_metadata(title, config=privacy)[0]
        records.append({
            "chunk_id": asr_chunk_id(sermon_id, index),
            "sermon_id": sermon_id,
            "sermon_title": title,
            "text": piece["text"],
            "start_s": first[0],
            "end_s": last[1],
            "audio_url": meta.get("audio_url"),
            "reader": meta.get("reader") or meta.get("preacher"),
            "text_source": "asr",
            "sermon_number": meta.get("sermon_number"),
            "scripture": meta.get("scripture"),
            "source_url": meta.get("source_url") or meta.get("ia_url"),
            "word_count": piece["word_count"],
            "word_start": piece["word_start"],
            "word_end": piece["word_end"],
            "librivox_id": None,
        })
        if privacy is not None:
            ends = [w[1] for w in words[owner[piece["word_start"]] : owner[piece["word_end"] - 1] + 1] if privacy.token in w[2]]
            ends += [i["end"] for i in items or () if i["start"] < last[1] and i["end"] > first[0]]
            records[-1]["video_id"] = sermon_id
            records[-1]["flag_end_s"] = max(ends) if ends else None
    return records


def sermon_review(transcript: dict, privacy: Config, sermon_id: str | None = None):
    """The sermon's ``review()`` items (real names: keep private)."""
    sermon_id = sermon_id or transcript.get("meta", {})["id"]
    return review(apply_drops(transcript_words(transcript), privacy, sermon_id), config=privacy)


def privacy_for(library: str, path: Path | None) -> Config | None:
    """The config for ``library``: None for wesley; else ``--privacy`` or
    ``$PREACHED_PRIVACY``, and no config at all is refused (exit 2)."""
    if library == PUBLIC_LIBRARY:
        if path is not None:
            raise SystemExit("library wesley is public domain and is never redacted; drop --privacy")
        return None
    if library in PUBLIC_DOMAIN:
        print(f"library {library} is a public-domain classic: build it with search/build_library.py", file=sys.stderr)
        raise SystemExit(2)
    if path is None and os.environ.get(CONFIG_ENV):
        path = Path(os.environ[CONFIG_ENV])
    if path is None:
        print(
            f"library {library} needs a privacy config: --privacy <toml> or ${CONFIG_ENV} "
            "(see privacy.example.toml); refusing to write unredacted church words",
            file=sys.stderr,
        )
        raise SystemExit(2)
    try:
        return load_config(path)
    except (OSError, ValueError) as exc:
        print(f"privacy: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def private_sermon(transcript: dict, chunk_config: dict, privacy: Config, review_root: Path, pause_s: float = PAUSE_S):
    """Chunks for one church sermon, plus its private review file.

    Returns ``(records, review_sha256)``. The review file holds the stored
    (redacted) title with the title's ``review()`` items, then the sermon's.
    """
    from preached.privacy import review_metadata
    from preached.youtube.pipeline import SAFE_ID, write_private_review

    meta = transcript.get("meta", {})
    sermon_id = meta["id"]
    if not SAFE_ID.fullmatch(str(sermon_id)):
        raise SystemExit(f"sermon id {str(sermon_id)[:20]!r} is not usable as a file name")
    items = sermon_review(transcript, privacy, sermon_id)
    records = asr_chunks(transcript, chunk_config, pause_s=pause_s, privacy=privacy, items=items)
    original_title = meta.get("title") or sermon_id
    header = {
        "field": "title",
        "stored": redact_metadata(original_title, config=privacy)[0],
        "review": [dict(i) for i in review_metadata(original_title, config=privacy)],
    }
    count, digest = write_private_review([header, *items], review_root / f"{sermon_id}.review.jsonl")
    return records, digest


def index_library(index_path: Path, sermons: list[tuple[list[dict], str]], privacy: Config, embedder=None) -> None:
    """Load church sermons into a library file, each UNPUBLISHED until approved."""
    from preached.youtube.library import index_video, open_library
    from preached.youtube.pipeline import _embed_on_cpu

    embed = embedder or _embed_on_cpu
    connection = open_library(index_path)
    try:
        for records, review_sha in sermons:
            if not records:
                continue
            title = records[0]["sermon_title"]
            matrix = embed([title] * len(records), [r["text"] for r in records])
            index_video(
                connection,
                video_id=records[0]["video_id"],
                title=title,
                published=None,
                duration_s=None,
                license_text=None,
                uploader=None,
                chunks=records,
                matrix=matrix,
                review_sha256=review_sha,
                privacy_sha256=config_sha256(privacy),
            )
    finally:
        connection.close()


def main(argv: list[str] | None = None, *, embedder=None) -> None:
    from preached.paths import INDEX_DIR

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("transcripts", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pause", type=float, default=PAUSE_S, help="seconds of silence that start a paragraph")
    parser.add_argument("--library", required=True, help="library slug. wesley is never redacted; any other library must have a privacy config")
    parser.add_argument("--privacy", type=Path, default=None, help="privacy TOML; defaults to $PREACHED_PRIVACY (not for wesley; required otherwise)")
    parser.add_argument("--index", type=Path, default=None, help="church library SQLite to load the sermons into, unpublished until --ack-review (not for wesley)")
    args = parser.parse_args(argv)
    privacy = privacy_for(args.library, args.privacy)
    config = load_chunk_config(ROOT / "corpus" / "chunk_config.json")
    rows = []
    if privacy is None:
        if args.index is not None:
            raise SystemExit("--index is for church libraries; wesley is built by search/build_index.py")
        for path in args.transcripts:
            rows.extend(asr_chunks(json.loads(path.read_text()), config, pause_s=args.pause))
        write_jsonl(args.out, rows)
        print(f"wrote {len(rows)} asr chunks from {len(args.transcripts)} transcripts to {args.out}")
        return
    review_root = (args.index.with_suffix("") if args.index else INDEX_DIR / args.library) / "review"
    sermons = []
    for path in args.transcripts:
        records, digest = private_sermon(json.loads(path.read_text()), config, privacy, review_root, args.pause)
        sermons.append((records, digest))
        rows.extend(records)
    write_jsonl(args.out, rows)
    flagged = sum(1 for row in rows if row["flag_end_s"] is not None)
    print(f"wrote {len(rows)} redacted asr chunks ({flagged} flagged) from {len(args.transcripts)} transcripts to {args.out}")
    if args.index is not None:
        index_library(args.index, sermons, privacy, embedder)
        print(f"loaded {len(sermons)} sermons into {args.index}; UNPUBLISHED until each review file is acknowledged")
    else:
        print("UNPUBLISHED: these chunks can only be served through --index <library>.sqlite and --ack-review")


if __name__ == "__main__":
    main()
