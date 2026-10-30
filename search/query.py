"""Search Wesley's sermons and print his words, not a paraphrase.

Examples:
  uv run search/query.py "what did Wesley say about worry" --mode hybrid -k 5
  uv run search/query.py "Romans 8:16" --mode bm25 -k 5
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))

from preached import env  # noqa: F401, E402
from preached.abstain import compute_signals, decide, floor_for  # noqa: E402
from preached.backends import DEFAULT_EMBED_BACKEND, load_embedder  # noqa: E402
from preached.libraries import PUBLIC_DOMAIN, classic_index_problem, is_public_domain  # noqa: E402
from preached.models import DEFAULT_MODEL, MODELS  # noqa: E402
from preached.paths import INDEX_DIR, INDEX_PATH  # noqa: E402
from preached.search import PREROLL_S, Searcher, play_start  # noqa: E402
from preached.store import EmbeddingMismatch, check_query_variant, open_readonly  # noqa: E402
from preached.youtube.listing import youtube_watch_url  # noqa: E402
from manifest import check_audio_url  # noqa: E402

# C0 (incl. ESC, newline), DEL and C1 controls: none belong in one terminal line.
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]+")
UNSAFE_URL = "n/a (unsafe URL hidden)"


def clean(value: object) -> str:
    """Printable text for the terminal: control characters become one space."""
    return CONTROL_RE.sub(" ", str(value))


def is_library_file(path: Path) -> bool:
    """A per-library index (YouTube import or build_library.py), not Wesley's.

    Both writers create a ``videos`` table; build_library.py also records
    ``library`` in meta. Read-only, so checking never changes the file.
    """
    if not path.is_file():
        return False
    connection = open_readonly(path)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "videos" in tables:
            return True
        return "meta" in tables and connection.execute(
            "SELECT 1 FROM meta WHERE key = 'library'"
        ).fetchone() is not None
    finally:
        connection.close()


def open_index(index: Path | None, library: str | None):
    """Open the index to search, read-only (sqlite ``mode=ro``, ``query_only``).

    --library takes an allow-listed public-domain slug and opens only its
    canonical /cache/index/<slug>.sqlite as built
    (``libraries.classic_index_problem``: no symlinks, realpath equality,
    owner and mode checks). The Wesley index (INDEX_PATH, the default) and
    any other --index path are searched as they are: nothing is synced, so
    a text-only chunks.jsonl never nulls the aligned timestamps and audio.
    --index must not be a library file: search those with --library.
    """
    if library is not None:
        if not is_public_domain(library):
            raise SystemExit(
                f"error: --library {library!r} refused: only public-domain libraries ({', '.join(PUBLIC_DOMAIN)})"
            )
        problem = classic_index_problem(library, INDEX_DIR / f"{library}.sqlite", INDEX_DIR)
        if problem is not None:
            raise SystemExit(f"error: {problem}")
        return open_target(INDEX_DIR / f"{library}.sqlite")
    path = index if index is not None else INDEX_PATH
    if is_library_file(path):
        raise SystemExit(
            f"error: {path} is a library index, not the Wesley index. "
            f"Search it with --library {path.stem}."
        )
    return open_target(path)


def open_target(path: Path):
    """Open read-only (``mode=ro``, ``query_only``). A missing file is refused, not created."""
    try:
        connection = open_readonly(path)
    except FileNotFoundError as exc:
        raise SystemExit(f"error: {exc}") from exc
    try:
        has_chunks = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'chunks'"
        ).fetchone() is not None
    except sqlite3.DatabaseError as exc:
        connection.close()
        raise SystemExit(f"error: {path} is not a SQLite index ({exc})") from exc
    if not has_chunks:
        connection.close()
        raise SystemExit(f"error: {path} is not a search index (no chunks table)")
    return connection


def fmt_time(value) -> str:
    """h:mm:ss, the same as the page's formatTime (whole seconds, floored)."""
    if value is None:
        return "n/a"
    total = int(float(value))
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"


def play_url(audio_url, start_s) -> str:
    """Where to play this hit.

    A validated YouTube watch URL is rebuilt as
    ``https://www.youtube.com/watch?v=<id>`` plus ``&t=<int>s`` when that
    seek is one whole number of seconds. Extra parameters are not printed.
    Nothing here adds ``#t=``. An archive.org URL still gets ``#t=<seek>``
    where seek is max(0, start_s - PREROLL_S). Anything else is hidden,
    including a URL whose parser raises. Control characters are stripped
    after a URL passes validation.
    """
    if not audio_url:
        return "n/a"
    youtube = youtube_watch_url(audio_url)
    if youtube is not None:
        return clean(youtube)
    try:
        # Same rule as the manifest: https on archive.org, no credentials,
        # no control characters. Every refusal is UnsafeRow, a ValueError
        # (check_audio_url also wraps urlsplit's own ValueError).
        check_audio_url(audio_url)
    except ValueError:
        return UNSAFE_URL
    audio_url = clean(audio_url)
    seek = play_start(start_s)
    if seek is None:
        return audio_url
    return f"{audio_url.split('#')[0]}#t={seek:g}"


def print_hits(query: str, mode: str, model: str | None, hits) -> None:
    print(f"query: {query}")
    print(f"mode: {mode}" + (f"  model: {model}" if model else ""))
    if not hits:
        print("Nothing found in the indexed sermons.")
        return
    for rank, hit in enumerate(hits, start=1):
        print(
            f"\n[{rank}] {clean(hit.sermon_title)}  (score {hit.score:.4f}, {clean(hit.chunk_id)})\n"
            f"    at {fmt_time(hit.start_s)} (start_s={hit.start_s})  read by {clean(hit.reader or 'n/a')}\n"
            f"    play: {play_url(hit.audio_url, hit.start_s)}  ({PREROLL_S:g} s pre-roll)\n"
            f"    text: {clean(hit.source_url or '')}\n"
            f"    \"{clean(hit.text)}\""
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Search Wesley's sermons.")
    parser.add_argument("query")
    parser.add_argument("--mode", choices=("bm25", "dense", "hybrid"), default="hybrid")
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=sorted(MODELS))
    parser.add_argument("--fusion", choices=("rrf", "weighted"), default="rrf")
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--dense-weight", type=float, default=0.5)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--index", type=Path, default=None,
                        help=f"SQLite index (default {INDEX_PATH}); searched read-only as it is, "
                        "never synced; library files are refused")
    target.add_argument("--library", help="search /cache/index/<slug>.sqlite (e.g. spurgeon, edwards); "
                        "built by search/build_library.py; read-only")
    parser.add_argument("--device", default="cpu", help="device for the torch query embedding")
    parser.add_argument(
        "--embed-backend",
        choices=("onnx", "torch"),
        default=None,
        help=f"query embedder (default {DEFAULT_EMBED_BACKEND}, or PREACHED_EMBED_BACKEND)",
    )
    parser.add_argument("--onnx-variant", choices=("fp32",), default=None)
    parser.add_argument("--ort-threads", type=int, default=None, help="ONNX Runtime intra-op threads")
    parser.add_argument("--hide-low-confidence", action="store_true",
                        help="hide the passages when the (heuristic) abstain rule rates them low confidence")
    args = parser.parse_args()

    # Read-only, and it does not sync. A text-only chunks.jsonl matches the
    # aligned index on ids and text; syncing it would null every start_s,
    # end_s, audio_url, and reader.
    connection = open_index(args.index, args.library)
    model_name = None
    embedder = None
    vector = None
    try:
        if args.mode == "bm25":
            searcher = Searcher(connection)
            hits = searcher.bm25(args.query, args.k)
        else:
            model_name = args.model
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
            embedder = load_embedder(
                model_name,
                args.embed_backend,
                variant=args.onnx_variant,
                ort_threads=args.ort_threads,
                device=args.device,
                batch_size=1,
            )
            try:
                check_query_variant(connection, model_name, getattr(embedder, "variant", None))
            except EmbeddingMismatch as exc:
                message = " ".join(str(exc).split())
                print(f"error: {message}", file=sys.stderr)
                raise SystemExit(1) from exc
            vector = embedder.encode_queries([args.query])[0]
            try:
                searcher = Searcher(connection, model=model_name)
            except EmbeddingMismatch as exc:
                raise SystemExit(f"error: {exc}\nOr search without vectors: --mode bm25") from exc
            if args.mode == "dense":
                hits = searcher.dense(vector, args.k)
            else:
                hits = searcher.hybrid(
                    args.query,
                    vector,
                    args.k,
                    fusion=args.fusion,
                    rrf_k=args.rrf_k,
                    dense_weight=args.dense_weight,
                )
    finally:
        if embedder is not None and hasattr(embedder, "close"):
            embedder.close()
    # Same abstain rule and per-backend floor as GET /api/search (preached.abstain).
    # BM25 has no dense signal, so the floor stays off.
    floor = None
    if vector is not None:
        floor = floor_for(
            model_name,
            backend=getattr(embedder, "backend", "torch"),
            variant=getattr(embedder, "variant", None),
        )
    confidence = decide(compute_signals(searcher, args.query, vector, hits), floor, has_results=bool(hits))
    mode_label = args.mode if args.fusion == "rrf" or args.mode != "hybrid" else f"hybrid-{args.fusion}"
    if confidence.abstain and hits and args.hide_low_confidence:
        print_hits(args.query, mode_label, model_name, [])
        print(f"({len(hits)} low-confidence passages hidden by --hide-low-confidence.)")
        return
    print_hits(args.query, mode_label, model_name, hits)
    if confidence.note and hits:
        print(f"\nnote: {confidence.note}")


if __name__ == "__main__":
    main()
