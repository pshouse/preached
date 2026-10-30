"""Search Wesley's sermons and print his words, not a paraphrase.

Examples:
  uv run search/query.py "what did Wesley say about worry" --mode hybrid -k 5
  uv run search/query.py "Romans 8:16" --mode bm25 -k 5
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))

from preached import env  # noqa: F401, E402
from preached.abstain import compute_signals, decide, floor_for  # noqa: E402
from preached.embed import encode_query, load_model, unload  # noqa: E402
from preached.library import (  # noqa: E402
    CHURCH_EMPTY,
    classic_heading,
    church_heading,
    resolve_church_path,
)
from preached.models import DEFAULT_MODEL, MODELS  # noqa: E402
from preached.paths import INDEX_DIR, INDEX_PATH, StaleChunks, index_chunks_jsonl  # noqa: E402
from preached.search import PREROLL_S, Searcher, play_start  # noqa: E402
from preached.store import EmbeddingMismatch, connect, open_readonly, sync_chunks  # noqa: E402
from preached.youtube.listing import youtube_watch_url  # noqa: E402
from manifest import check_audio_url  # noqa: E402

# C0 (incl. ESC, newline), DEL and C1 controls: none belong in one terminal line.
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]+")
UNSAFE_URL = "n/a (unsafe URL hidden)"


def clean(value: object) -> str:
    """Printable text for the terminal: control characters become one space."""
    return CONTROL_RE.sub(" ", str(value))


def ensure_chunks(connection) -> None:
    try:
        chunks_path = index_chunks_jsonl()
    except StaleChunks as exc:
        raise SystemExit(f"error: {exc}") from exc
    if not chunks_path.exists():
        raise SystemExit(
            f"missing {chunks_path}. Run: uv run corpus/fetch_wesley.py && uv run corpus/chunk_sermons.py"
        )
    sync_chunks(connection, chunks_path)


def fmt_time(value) -> str:
    """h:mm:ss, the same as the page's formatTime (whole seconds, floored)."""
    if value is None:
        return "n/a"
    total = int(float(value))
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"


def play_url(audio_url, start_s) -> str:
    """Where to play this hit.

    A validated YouTube watch URL is printed as stored. Its ``&t=`` already
    includes the pre-roll, so this does not add ``#t=``. An archive.org URL
    still gets ``#t=<seek>`` where seek is max(0, start_s - PREROLL_S).
    Anything else is hidden, including a URL whose parser raises. Control
    characters are stripped after a URL passes validation.
    """
    if not audio_url:
        return "n/a"
    youtube = youtube_watch_url(audio_url)
    if youtube is not None:
        return clean(youtube)
    try:
        # Same rule as the manifest: https on archive.org, no credentials.
        # UnsafeRow is a ValueError (bad port, off-host, credentials).
        # urlsplit also raises ValueError for an invalid IPv6 netloc and
        # some NFKC hosts, before check_audio_url can wrap it.
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
        print(format_hit(rank, hit))


def format_hit(rank: int, hit) -> str:
    return (
        f"\n[{rank}] {clean(hit.sermon_title)}  (score {hit.score:.4f}, {clean(hit.chunk_id)})\n"
        f"    at {fmt_time(hit.start_s)} (start_s={hit.start_s})  read by {clean(hit.reader or 'n/a')}\n"
        f"    play: {play_url(hit.audio_url, hit.start_s)}  ({PREROLL_S:g} s pre-roll)\n"
        f"    text: {clean(hit.source_url or '')}\n"
        f"    \"{clean(hit.text)}\""
    )


def format_side_section(
    heading: str,
    hits,
    confidence,
    *,
    hide_low: bool,
    empty_message: str | None,
    mode_note: str | None = None,
) -> str:
    """One column of ``--side``, as text. No hits uses ``empty_message`` when set."""
    lines = [f"## {heading}"]
    if mode_note:
        lines.append(mode_note)
    shown = hits
    if confidence is not None and confidence.abstain and hits and hide_low:
        shown = []
    if confidence is not None:
        lines.append(f"confidence: {confidence.level}")
    if not shown:
        if confidence is not None and confidence.abstain and hits and hide_low:
            lines.append(f"({len(hits)} low-confidence passages hidden by --hide-low-confidence.)")
        elif empty_message:
            lines.append(empty_message)
        else:
            lines.append("Nothing found in the indexed sermons.")
    else:
        lines.extend(format_hit(rank, hit) for rank, hit in enumerate(shown, start=1))
        if confidence is not None and confidence.note:
            lines.append(f"note: {confidence.note}")
    return "\n".join(lines)


def search_index(connection, args, vector, model_name: str | None, *, fallback_bm25: bool):
    """Hits and confidence for one library file. Same rule as a single query.

    ``fallback_bm25`` is for the church file: a vector mismatch prints keyword
    hits instead of stopping the classic side.
    """
    used_vector = vector
    used_model = model_name
    used_mode = args.mode
    note = None
    try:
        if args.mode == "bm25":
            searcher = Searcher(connection)
            hits = searcher.bm25(args.query, args.k)
            used_vector = None
            used_model = None
        else:
            searcher = Searcher(connection, model=model_name)
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
    except EmbeddingMismatch:
        if not fallback_bm25:
            raise
        searcher = Searcher(connection)
        hits = searcher.bm25(args.query, args.k)
        used_vector = None
        used_model = None
        used_mode = "bm25"
        note = "Stored passage vectors do not match the configured model; results are BM25 only."
    floor = floor_for(used_model) if used_vector is not None else None
    confidence = decide(
        compute_signals(searcher, args.query, used_vector, hits),
        floor,
        has_results=bool(hits),
    )
    return hits, confidence, used_mode, used_model, note


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Search Wesley's sermons.")
    parser.add_argument("query")
    parser.add_argument("--mode", choices=("bm25", "dense", "hybrid"), default="hybrid")
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=sorted(MODELS))
    parser.add_argument("--fusion", choices=("rrf", "weighted"), default="rrf")
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--dense-weight", type=float, default=0.5)
    parser.add_argument("--index", type=Path, default=INDEX_PATH)
    parser.add_argument("--device", default="cpu", help="device for the query embedding")
    parser.add_argument("--hide-low-confidence", action="store_true",
                        help="hide the passages when the (heuristic) abstain rule rates them low confidence")
    parser.add_argument(
        "--side",
        action="store_true",
        help="Print the classic library and your church, one section each",
    )
    parser.add_argument(
        "--church-index",
        type=Path,
        default=None,
        help="Church library SQLite. Default: the single index marked role=church",
    )
    parser.add_argument(
        "--church-library",
        default=None,
        help="Church library slug under the index directory, when --church-index is omitted",
    )
    args = parser.parse_args(argv)

    connection = connect(args.index)
    ensure_chunks(connection)
    model_name = None
    loaded = None
    vector = None
    try:
        if args.mode != "bm25":
            model_name = args.model
            spec = MODELS[model_name]
            loaded = load_model(spec, device=args.device, batch_size=1)
            vector = encode_query(loaded, args.query)
        try:
            hits, confidence, _used_mode, _used_model, _note = search_index(
                connection, args, vector, model_name, fallback_bm25=False
            )
        except EmbeddingMismatch as exc:
            raise SystemExit(f"error: {exc}\nOr search without vectors: --mode bm25") from exc
        mode_label = args.mode if args.fusion == "rrf" or args.mode != "hybrid" else f"hybrid-{args.fusion}"
        if args.side:
            print_side(args, connection, hits, confidence, mode_label, model_name, vector)
            return
    finally:
        if loaded is not None:
            unload(loaded)
    # Same abstain rule and per-model floor as GET /api/search (preached.abstain).
    if confidence.abstain and hits and args.hide_low_confidence:
        print_hits(args.query, mode_label, model_name, [])
        print(f"({len(hits)} low-confidence passages hidden by --hide-low-confidence.)")
        return
    print_hits(args.query, mode_label, model_name, hits)
    if confidence.note and hits:
        print(f"\nnote: {confidence.note}")


def print_side(args, connection, hits, confidence, mode_label: str, model_name: str | None, vector) -> None:
    """Classic section, then your church. A missing church file is not an error."""
    classic_slug = connection_slug(args.index, "wesley")
    church_path = resolve_church_path(
        INDEX_DIR,
        classic=args.index,
        church_index=args.church_index,
        church_library=args.church_library,
    )
    church_hits = []
    church_confidence = None
    church_note = None
    church_mode = None
    church_title = church_heading(None, None)
    if church_path is not None:
        church_slug = connection_slug(church_path, "church")
        church_conn = open_readonly(church_path)
        try:
            church_title = church_heading(church_conn, church_slug)
            church_hits, church_confidence, church_mode, _model, church_note = search_index(
                church_conn, args, vector, model_name, fallback_bm25=True
            )
        finally:
            church_conn.close()
    print(f"query: {clean(args.query)}")
    print(f"mode: {mode_label}" + (f"  model: {model_name}" if model_name else ""))
    print()
    print(
        format_side_section(
            classic_heading(connection, classic_slug),
            hits,
            confidence,
            hide_low=args.hide_low_confidence,
            empty_message=None,
        )
    )
    print()
    mode_note = None
    if church_note:
        mode_note = church_note
    elif church_mode is not None and church_mode != args.mode:
        mode_note = f"mode: {church_mode}"
    print(
        format_side_section(
            church_title,
            church_hits,
            church_confidence,
            hide_low=args.hide_low_confidence,
            empty_message=CHURCH_EMPTY,
            mode_note=mode_note,
        )
    )


def connection_slug(path: Path, default: str) -> str:
    stem = Path(path).stem
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", stem):
        return stem
    return default


if __name__ == "__main__":
    main()
